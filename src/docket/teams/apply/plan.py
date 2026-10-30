"""``docket pod update <dir>``: compose the pre-existing writers (``teams.roles.
add_user_archetype``, member provisioning, the pipeline bind, and ``teams.pod_settings.PodSettings``)
into one operation, driven by a small ``pod.yaml`` manifest (``members``, ``settings``,
``pipeline``) alongside the same ``roles/*.yaml``/``pipeline.yaml`` shape the shipped recipes
already ship. A role goes into *project*'s own pod-scoped overlay (``Home.
pod_config_dir(project)/roles/``) as its authored file, never the global one: ``teams/pod.py``'s roster helpers
(``_role_names``/``parse_member_id``, which ``pod_full_roster``/``members_of`` depend on to
resolve a pipeline's roster) resolve that pod overlay too (see ``_plan_roles``), matching what
``docket pod update roles/<file>.yaml`` already did by hand. ``plan_apply`` is
pure (reads only) and validates everything -- roles, the roster the pipeline would resolve
against *after* ``members``, and every setting -- before ``apply`` writes anything. Idempotent:
an item already matching what is on disk plans as ``skip``; nothing is ever removed."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from docket.governance import policy as _policy
from docket.governance import review as _reviewed
from docket.governance.review import RunItem
from docket.kernel import protected_paths as _protected
from docket.kernel.errors import CanonicalFormRefused, DispatchError
from docket.kernel.home import current_home
from docket.models import document_fields as _documents
from docket.observability import exporter as _exporter
from docket.pipeline.domain import plan as _orch
from docket.pipeline.domain import spec as _pipeline
from docket.teams import config_docs as _config_docs
from docket.teams import fleet as _fleet
from docket.teams import model_selection as _mp
from docket.teams import pod
from docket.teams import pod_provisioning as _pp
from docket.teams import pod_settings as _pod_settings
from docket.teams import prompts as _prompts
from docket.teams import role_schema as _role_schema
from docket.teams import roles as _arch
from docket.teams.apply import lock as _lock
from docket.teams.apply.check import (
    directory_send_problems,
    member_names,
    unresolved_members,
    unsupplied_inputs,
)
from docket.teams.apply.external import plan_mcp_servers, plan_services
from docket.teams.apply.model import (
    ApplyAction,
    ApplyItem,
    ApplyPlan,
    PodApplyError,
    PodApplyRefused,
    _MemberWrite,
    _NamedPipelineWrite,
    _PipelineWrite,
    _PluginWrite,
    _PolicyWrite,
    _PromptWrite,
    _RoleWrite,
    _SettingWrite,
    _SkillWrite,
)
from docket.teams.apply.recipes import (
    _config_glob,
    _directory_files,
    _named_pipeline_files,
    _skill_digest,
    unresolvable_pipeline_steps,
)
from docket.teams.apply.review import (
    PlanReview,
    RunChange,
    classify_directory,
    repo_root,
    review_decision,
    runs_changed,
)
from docket.teams.apply.routines import plan_routines
from docket.teams.apply.write import apply
from docket.teams.config_docs import _MANIFEST_KEYS


def _plan_roles(
    directory: Path, base_registry: _arch.ArchetypeRegistry, project: str
) -> tuple[list[ApplyItem], list[_RoleWrite], dict[str, _role_schema.RoleArchetype]]:
    """Plan ``roles/*.yaml|yml|json`` into *project*'s own pod-scoped role overlay, the same target
    ``docket pod update --pod <project>`` writes to -- never the global overlay
    (see module docstring)."""
    items: list[ApplyItem] = []
    writes: list[_RoleWrite] = []
    merged = dict(base_registry.archetypes)
    roles_dir = directory / "roles"
    overlay_dir = current_home().pod_config_dir(project) / "roles"
    if not roles_dir.is_dir():
        return items, writes, merged

    for role_file in sorted(_config_glob(roles_dir)):
        try:
            doc = _config_docs.load_document(role_file, kind="role").doc
        except _config_docs.CanonicalFormError as exc:
            raise PodApplyRefused(str(exc)) from exc
        except _config_docs.ConfigDocError as exc:
            raise PodApplyError(str(exc)) from exc
        name = str(doc.get("name", "")).strip()
        if not name:
            raise PodApplyError(f"{role_file}: archetype has no top-level 'name'")
        try:
            arch = _role_schema.from_wire(name, doc)
        except _role_schema.ArchetypeError as exc:
            raise PodApplyError(f"{role_file}: {exc}") from exc
        try:
            files = _arch.role_overlay_files(role_file)
        except _role_schema.ArchetypeError as exc:
            raise PodApplyError(str(exc)) from exc
        existing = base_registry.get(name)
        already_pod = base_registry.source_of(name) == f"pod:{project}"
        same_bytes = all(
            (overlay_dir / rel).is_file() and (overlay_dir / rel).read_bytes() == data
            for rel, data in files.items()
        )
        # The same role in other bytes (an export regenerates the short form) is still `skip`: its
        # overlay copy is refreshed so that it hashes to what `applied.lock` records.
        same_role = already_pod and existing is not None and existing.to_wire() == arch.to_wire()
        action: ApplyAction = (
            "skip" if same_bytes or same_role else "replace" if already_pod else "add"
        )
        if not same_bytes:
            writes.append(_RoleWrite(files=tuple(files.items())))
        merged[name] = arch
        items.append(ApplyItem(kind="role", name=name, action=action))
    return items, writes, merged


def _plan_prompts(directory: Path, project: str) -> tuple[list[ApplyItem], list[_PromptWrite]]:
    """Plan ``prompts/<layer>/<name>.md`` -- and the tests file each names -- into *project*'s own
    ``prompts/`` (the pod scope of ``teams.prompts.resolve_prompt``), by bytes. A file that does
    not parse, or a ``tests:`` path that escapes ``prompts/`` or names no file, is refused."""
    items: list[ApplyItem] = []
    writes: list[_PromptWrite] = []
    overlay_dir = current_home().pod_config_dir(project) / "prompts"
    for prompt_file in _config_docs.prompt_files(directory):
        try:
            prompt = _prompts.load_prompt_file(prompt_file)
            tests = _config_docs.prompt_tests_file(prompt_file, directory)
        except _prompts.PromptError as exc:
            raise PodApplyError(str(exc)) from exc
        changed: list[_PromptWrite] = []
        exists = False
        for path in (prompt_file, tests):
            if path is None:
                continue
            rel = path.relative_to(directory / "prompts").as_posix()
            source = path.read_bytes()
            dest = overlay_dir / rel
            exists = exists or dest.is_file()
            if not (dest.is_file() and dest.read_bytes() == source):
                changed.append(_PromptWrite(rel=rel, source=source))
        writes.extend(w for w in changed if w not in writes)
        action: ApplyAction = ("replace" if exists else "add") if changed else "skip"
        items.append(ApplyItem(kind="prompt", name=f"{prompt.layer}/{prompt.name}", action=action))
    return items, writes


def _plan_policies(directory: Path, project: str) -> tuple[list[ApplyItem], list[_PolicyWrite]]:
    """Plan ``policies/*.json|*.yaml|*.yml`` into *project*'s own policy directory -- the same
    one ``governance.policy.policy_files`` reads and ``_export_policies`` copies, never the fleet-wide
    ``$POLICIES_DIR``. Each file must pass ``governance.policy.validate_policy`` first."""
    items: list[ApplyItem] = []
    writes: list[_PolicyWrite] = []
    policies_dir = directory / "policies"
    if not policies_dir.is_dir():
        return items, writes
    dest_dir = current_home().pod_config_dir(project) / "policies"
    policy_files = sorted(
        p for pattern in ("*.json", "*.yaml", "*.yml") for p in policies_dir.glob(pattern)
    )
    for policy_file in policy_files:
        try:
            _policy.read_policy(policy_file)
        except CanonicalFormRefused as exc:
            raise PodApplyRefused(f"{policy_file}: {exc}") from exc
        except Exception:
            raise PodApplyError(f"{policy_file}: {_policy.validate_policy(policy_file)}") from None
        error = _policy.validate_policy(policy_file)
        if error:
            raise PodApplyError(f"{policy_file}: {error}")
        text = policy_file.read_text(encoding="utf-8")
        dest = dest_dir / policy_file.name
        # Compared by parsed (canonical) content, not raw text: an export's regenerated
        # short-form YAML -- reordered keys, an added `# yaml-language-server` header --
        # otherwise never plans `skip` even when it is the exact same policy already applied.
        if dest.is_file() and _policy.read_policy(dest) == _policy.read_policy(policy_file):
            action: ApplyAction = "skip"
        else:
            action = "replace" if dest.is_file() else "add"
            writes.append(_PolicyWrite(name=policy_file.name, text=text))
        items.append(ApplyItem(kind="policy", name=policy_file.name, action=action))
    return items, writes


def _plan_plugins(directory: Path, project: str) -> tuple[list[ApplyItem], list[_PluginWrite]]:
    """Plan ``plugins/*.py`` into *project*'s own ``config/plugins/`` -- the same directory
    ``governance.plugins.discover`` reads and ``_export_plugins`` copies back, by sha256: an installed
    copy with the same hash is left alone, any other content is replaced."""
    items: list[ApplyItem] = []
    writes: list[_PluginWrite] = []
    plugins_dir = directory / "plugins"
    if not plugins_dir.is_dir():
        return items, writes
    dest_dir = current_home().pod_config_dir(project) / "plugins"
    for plugin_file in sorted(plugins_dir.glob("*.py")):
        source = plugin_file.read_bytes()
        dest = dest_dir / plugin_file.name
        if (
            dest.is_file()
            and hashlib.sha256(dest.read_bytes()).digest() == hashlib.sha256(source).digest()
        ):
            action: ApplyAction = "skip"
        else:
            action = "replace" if dest.is_file() else "add"
            writes.append(_PluginWrite(name=plugin_file.name, source=source))
        items.append(ApplyItem(kind="plugin", name=plugin_file.name, action=action))
    return items, writes


def _plan_named_pipelines(
    directory: Path, project: str
) -> tuple[list[ApplyItem], list[_NamedPipelineWrite]]:
    """Plan ``pipelines/<name>.yaml`` into *project*'s own ``config/pipelines/``, the directory
    dispatch resolves a task's ``pipeline`` in, by bytes. A file dispatch could not run (an
    invalid pipeline, or a stem that is not a task pipeline name) raises PodApplyError."""
    items: list[ApplyItem] = []
    writes: list[_NamedPipelineWrite] = []
    dest_dir = current_home().pod_config_dir(project) / "pipelines"
    seen: set[str] = set()
    for pipeline_file in _named_pipeline_files(directory):
        rel = f"pipelines/{pipeline_file.name}"
        if not pod.TASK_PIPELINE_NAME.match(pipeline_file.stem):
            raise PodApplyError(f"{rel}: {pipeline_file.stem!r} is not a pipeline name")
        if pipeline_file.stem in seen:
            raise PodApplyError(f"{rel}: two files name pipeline {pipeline_file.stem!r}")
        seen.add(pipeline_file.stem)
        source = pipeline_file.read_bytes()
        loaded = _pipeline.load_pipeline(source.decode("utf-8"))
        if loaded.spec is None:
            refused = PodApplyRefused if loaded.canonical else PodApplyError
            raise refused(f"{rel}: {'; '.join(loaded.errors)}")
        dest = dest_dir / pipeline_file.name
        if dest.is_file() and dest.read_bytes() == source:
            action: ApplyAction = "skip"
        else:
            action = "replace" if dest.is_file() else "add"
            writes.append(_NamedPipelineWrite(name=pipeline_file.name, source=source))
        items.append(ApplyItem(kind="pipeline", name=rel, action=action))
    return items, writes


def _plan_skills(directory: Path, project: str) -> tuple[list[ApplyItem], list[_SkillWrite]]:
    """Plan each ``skills/<name>/`` whole into *project*'s own ``config/skills/<name>/``, by a
    sha256 over the skill's own sorted relative paths and bytes: an installed copy with the
    same hash plans ``skip``, any other content or none yet plans ``replace``/``add``."""
    items: list[ApplyItem] = []
    writes: list[_SkillWrite] = []
    skills_dir = directory / "skills"
    if not skills_dir.is_dir():
        return items, writes
    dest_root = current_home().pod_config_dir(project) / "skills"
    for skill_dir in sorted(p for p in skills_dir.iterdir() if p.is_dir()):
        if not (skill_dir / "SKILL.md").is_file():
            continue
        name = skill_dir.name
        source_files = _directory_files(skill_dir)
        dest = dest_root / name
        if dest.is_dir() and _skill_digest(_directory_files(dest)) == _skill_digest(source_files):
            action: ApplyAction = "skip"
        else:
            action = "replace" if dest.is_dir() else "add"
            writes.append(_SkillWrite(name=name, files=source_files))
        items.append(ApplyItem(kind="skill", name=name, action=action))
    return items, writes


def _plan_members(
    project: str,
    member_roles: list[str],
    registry: _arch.ArchetypeRegistry,
) -> tuple[list[ApplyItem], list[_MemberWrite], dict[str, str]]:
    items: list[ApplyItem] = []
    writes: list[_MemberWrite] = []
    roster = dict(pod.pod_full_roster(project))

    base_ids = _pp.pod_member_ids(project)
    if not base_ids:
        raise PodApplyError(f"no pod found for '{project}'")
    base_id = base_ids[0]
    codebase = _fleet.meta_get(base_id, "codebase", "")
    stack = _fleet.meta_get(base_id, "stack", "")
    description = _fleet.meta_get(base_id, "description", "")
    project_key = _fleet.meta_get(base_id, "projectKey", "default") or "default"
    work_dir = _fleet.meta_get(base_id, "workDir", "")
    blueprint_name = _fleet.meta_get(base_id, "blueprint", "")
    role_models, _tiers, _default_model = _mp.load_registry()

    for raw_role in member_roles:
        canon = str(raw_role).strip().lower()
        if not canon:
            continue
        arch = registry.get(canon)
        if arch is None:
            raise PodApplyError(f"pod.yaml: unknown pod role {raw_role!r}")
        if canon in roster:
            items.append(ApplyItem(kind="member", name=canon, action="skip"))
            continue
        mid = pod.member_id(project, canon)
        model = _mp.resolve_role_model(arch.name, role_models, project=project)
        member = pod.PodMember(
            project=project,
            role=canon,
            index=1,
            member_id=mid,
            model=model,
            session_key=pod.session_key(project, project_key),
        )
        writes.append(
            _MemberWrite(
                member=member,
                codebase=codebase,
                stack=stack,
                description=description,
                project_key=project_key,
                work_dir=work_dir,
                blueprint_name=blueprint_name,
            )
        )
        roster[canon] = mid
        items.append(ApplyItem(kind="member", name=canon, action="add"))
    return items, writes, roster


def _plan_pipeline(
    directory: Path,
    pipeline_name: str | None,
    project: str,
    roster: dict[str, str],
    registry: _arch.ArchetypeRegistry,
) -> tuple[ApplyItem | None, _PipelineWrite | None]:
    pipeline_file: Path | None
    if pipeline_name:
        pipeline_file = directory / str(pipeline_name)
        if not pipeline_file.is_file():
            raise PodApplyError(f"pod.yaml: pipeline file not found: {pipeline_file}")
    else:
        default_file = directory / "pipeline.yaml"
        pipeline_file = default_file if default_file.is_file() else None
    if pipeline_file is None:
        return None, None

    text = pipeline_file.read_text(encoding="utf-8")
    result = _pipeline.load_pipeline(text)
    if result.spec is None:
        refused = PodApplyRefused if result.canonical else PodApplyError
        raise refused(f"{pipeline_file}: invalid pipeline: {'; '.join(result.errors)}")
    exec_plan = _orch.resolve_plan(result.spec, roster, registry=registry)
    problems = unresolvable_pipeline_steps(exec_plan, project)
    if problems:
        raise PodApplyError(f"{pipeline_file}: " + "; ".join(problems))

    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    current = _fleet.meta_get(pod.member_id(project, "lead"), "pipeline", "")
    if current == digest:
        return ApplyItem(kind="pipeline", name=pipeline_file.name, action="skip"), None
    action: ApplyAction = "replace" if current else "add"
    return (
        ApplyItem(kind="pipeline", name=pipeline_file.name, action=action),
        _PipelineWrite(text=text, digest=digest),
    )


def _pipeline_bound(project: str) -> bool:
    """Whether *project* already has a bound pipeline (unreadable settings are reported by
    ``_plan_settings``, not here)."""
    try:
        return bool(_pod_settings.PodSettings.load_for(project).pipeline)
    except _pod_settings.PodSettingsError:
        return False


def _plan_settings(
    project: str, raw_settings: dict[str, Any], mcp_extra: tuple[str, ...] = ()
) -> tuple[list[ApplyItem], list[_SettingWrite]]:
    items: list[ApplyItem] = []
    writes: list[_SettingWrite] = []
    if not raw_settings:
        return items, writes
    try:
        settings_now = _pod_settings.PodSettings.load_for(project)
    except _pod_settings.PodSettingsError as exc:
        raise PodApplyError(str(exc)) from exc
    for key, value in raw_settings.items():
        if key == "pipeline":
            raise PodApplyError("pod.yaml: 'pipeline' belongs at the top level, not 'settings'")
        if key == _pod_settings.NETWORK_GRANT_KEY:
            note = _pod_settings.NETWORK_GRANT_SKIPPED
            items.append(ApplyItem(kind="setting", name=key, action="skip", note=note))
            continue
        if key not in _pod_settings.PodSettings.KEYS:
            raise PodApplyError(f"pod.yaml: unknown pod setting {key!r}")
        str_value = ",".join(str(v) for v in value) if isinstance(value, list) else str(value)
        try:
            coerced = _pod_settings.PodSettings.coerce(
                key, str_value, project=project, mcp_extra=mcp_extra
            )
        except _pod_settings.PodSettingsError as exc:
            raise PodApplyError(str(exc)) from exc
        current_value, source = settings_now.value_and_source(key, project)
        if current_value == coerced:
            note = "already the default" if source == "default" else ""
            items.append(ApplyItem(kind="setting", name=key, action="skip", note=note))
            continue
        items.append(
            ApplyItem(kind="setting", name=key, action="replace" if source == "set" else "add")
        )
        writes.append(_SettingWrite(key=key, value=coerced))
    return items, writes


def _settings_with_top_level(
    raw_settings: dict[str, Any], manifest: dict[str, Any]
) -> dict[str, Any]:
    """*raw_settings* plus the manifest's top-level ``prepare`` (blank means ``none``) and
    ``protects`` (a list of globs); either one inside ``settings`` is refused, as ``pipeline``
    is."""
    for key in ("prepare", "protects"):
        if key in raw_settings:
            raise PodApplyError(f"pod.yaml: '{key}' belongs at the top level, not 'settings'")
    merged = dict(raw_settings)
    raw = manifest.get("prepare")
    if raw is not None:
        if not isinstance(raw, str):
            raise PodApplyError("pod.yaml: 'prepare' must be a string")
        merged["prepare"] = raw.strip() or "none"
    patterns = manifest.get("protects")
    if patterns is not None:
        merged["protects"] = _protects_list(patterns)
    return merged


def _protects_list(raw: Any) -> list[str]:
    if not isinstance(raw, list) or not all(isinstance(e, str) for e in raw):
        raise PodApplyError("pod.yaml: 'protects' must be a list of strings")
    try:
        return [_protected.check_pattern(entry) for entry in raw]
    except ValueError as exc:
        raise PodApplyError(f"pod.yaml: 'protects' entry is invalid ({exc})") from exc


def _plan_exporters(manifest: dict[str, Any]) -> tuple[str, ...]:
    """Validate `pod.yaml`'s optional `exporters` list against the live exporter catalog
    (ADR 0014 rule 7): a recipe may *name* a destination, never carry one. A malformed or
    unknown entry raises `PodApplyError` naming `exporters` before anything is written."""
    raw = manifest.get("exporters")
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise PodApplyError("pod.yaml: 'exporters' must be a list")
    catalog = _exporter.load_catalog()
    names: list[str] = []
    for entry in raw:
        if not isinstance(entry, str) or not _documents.NAME_RE.match(entry):
            raise PodApplyError(f"pod.yaml: 'exporters' entry {entry!r} is not an exporter name")
        if catalog.get(entry) is None:
            raise PodApplyError(f"pod.yaml: 'exporters' names unknown exporter {entry!r}")
        names.append(entry)
    return tuple(names)


def plan_apply(project: str, directory: Path) -> ApplyPlan:
    """Validate applying *directory* to *project* and return the plan. Read-only:
    no role overlay, policy, member, pipeline, or setting is ever written here."""
    if not directory.is_dir():
        raise PodApplyError(f"recipe directory not found: {directory}")
    try:
        pod.pod_pipeline(project)
    except DispatchError as exc:
        raise PodApplyError(str(exc)) from exc

    manifest_file = directory / "pod.yaml"
    if manifest_file.is_file():
        try:
            manifest = _config_docs.load_document(manifest_file, kind="pod").doc
        except _config_docs.ConfigDocError as exc:
            raise PodApplyError(str(exc)) from exc
    else:
        manifest = {}
    unknown_keys = set(manifest) - _MANIFEST_KEYS
    if unknown_keys:
        raise PodApplyError(f"pod.yaml: unknown key(s): {', '.join(sorted(unknown_keys))}")

    member_roles = manifest.get("members", [])
    if not isinstance(member_roles, list):
        raise PodApplyError("pod.yaml: 'members' must be a list")
    raw_settings = manifest.get("settings", {}) or {}
    if not isinstance(raw_settings, dict):
        raise PodApplyError("pod.yaml: 'settings' must be a mapping")
    description = manifest.get("description")
    if description is not None and not isinstance(description, str):
        raise PodApplyError("pod.yaml: 'description' must be a string")
    pipeline_name = manifest.get("pipeline")
    exporter_names = _plan_exporters(manifest)

    base_registry = _arch.load_registry(project)
    role_items, role_writes, merged_archetypes = _plan_roles(directory, base_registry, project)
    augmented = _arch.ArchetypeRegistry(merged_archetypes, project=project)
    unresolved = unresolved_members(
        member_roles, {name: a.version for name, a in merged_archetypes.items()}
    )
    if unresolved:
        raise PodApplyError(f"pod.yaml: members: {'; '.join(unresolved)}")
    member_roles = member_names(member_roles)
    unsupplied = unsupplied_inputs(directory)
    if unsupplied:
        raise PodApplyError("; ".join(unsupplied))
    conflicting = directory_send_problems(directory, project)
    if conflicting:
        raise PodApplyError("; ".join(conflicting))

    prompt_items, prompt_writes = _plan_prompts(directory, project)

    policy_items, policy_writes = _plan_policies(directory, project)

    plugin_items, plugin_writes = _plan_plugins(directory, project)

    named_items, named_writes = _plan_named_pipelines(directory, project)
    routine_items, routine_writes = plan_routines(directory, project)
    skill_items, skill_writes = _plan_skills(directory, project)

    member_items, member_writes, roster_after = _plan_members(project, member_roles, augmented)

    pipeline_item, pipeline_write = _plan_pipeline(
        directory, pipeline_name, project, roster_after, augmented
    )

    mcp_items, mcp_write = plan_mcp_servers(directory, project)
    service_items, service_writes = plan_services(directory, project)

    all_settings = _settings_with_top_level(raw_settings, manifest)
    if "maxReworkCycles" in all_settings and (
        pipeline_item is not None or _pipeline_bound(project)
    ):
        raise PodApplyRefused(f"pod.yaml: {_pod_settings.REWORK_BOUND_BY_PIPELINE}")
    setting_items, setting_writes = _plan_settings(
        project, all_settings, tuple(i.name for i in mcp_items)
    )

    items = [
        *role_items,
        *prompt_items,
        *policy_items,
        *plugin_items,
        *skill_items,
        *mcp_items,
        *service_items,
        *member_items,
    ]
    if pipeline_item is not None:
        items.append(pipeline_item)
    items.extend(named_items)
    items.extend(routine_items)
    items.extend(setting_items)

    return ApplyPlan(
        project=project,
        directory=directory,
        items=tuple(items),
        exporters=exporter_names,
        _role_writes=tuple(role_writes),
        _prompt_writes=tuple(prompt_writes),
        _policy_writes=tuple(policy_writes),
        _plugin_writes=tuple(plugin_writes),
        _named_pipeline_writes=tuple(named_writes),
        _routine_writes=tuple(routine_writes),
        _skill_writes=tuple(skill_writes),
        _mcp_server_write=mcp_write,
        _service_writes=tuple(service_writes),
        _member_writes=tuple(member_writes),
        _pipeline_write=pipeline_write,
        _setting_writes=tuple(setting_writes),
    )


@dataclass(frozen=True)
class DirectoryOutcome:
    """What ``apply_directory`` did: ``status`` ``applied``/``planned`` carry ``items``;
    ``needs_code``/``code_mismatch`` carry ``code`` (needs_code only) and the ``runs`` to review;
    ``refused`` carries the shell names."""

    status: Literal["applied", "planned", "needs_code", "code_mismatch", "refused"]
    items: tuple[ApplyItem, ...] = ()
    code: str = ""
    runs: tuple[RunItem, ...] = ()
    refused: tuple[str, ...] = ()


def apply_directory(
    project: str, directory: Path, root: Path, *, accept: str | None, dry_run: bool, channel: str
) -> DirectoryOutcome:
    """Off-terminal ``pod update``: plan, enforce the review rule against *root*, apply.
    Raises PodApplyError when the directory cannot be planned."""

    plan = plan_apply(project, directory)
    if dry_run:
        return DirectoryOutcome("planned", plan.items)
    decision = review_decision(root, project, directory, accept)
    if decision.status == "refused":
        return DirectoryOutcome("refused", refused=decision.review.refused)
    if decision.status == "needs_code":
        return DirectoryOutcome("needs_code", code=decision.code, runs=decision.review.runs)
    if decision.status == "code_mismatch":
        found = _reviewed.lookup(root, project)
        was = {(i.kind, i.name): i.runs for i in found.items} if found else {}
        changed = tuple(i for i in decision.review.runs if was.get((i.kind, i.name)) != i.runs)
        return DirectoryOutcome("code_mismatch", runs=changed)
    if decision.status == "accepted":
        _reviewed.remember(root, project, decision.review.runs)
    return DirectoryOutcome("applied", apply(plan, channel=channel).items)


@dataclass(frozen=True)
class RepoChanges:
    """What a repository's ``.docket/`` changed since it was applied to a pod: the read-only
    ``plan``, its non-skip ``adds_changed`` lines, ``runs_changed`` and the ``review``."""

    plan: ApplyPlan
    adds_changed: tuple[str, ...]
    runs_changed: tuple[RunChange, ...]
    review: PlanReview
    allowed_on: str


def repo_changes(project: str, repo_dir: Path) -> RepoChanges | None:
    """Compare *repo_dir* with what was last applied to *project*; None when it is not the
    pod's recorded configuration of record or has not changed. Read-only."""

    lead = pod.member_id(project, "lead")
    source = _fleet.meta_get(lead, "configSource", "")
    recorded = _fleet.meta_get(lead, "configDigest", "")
    if not (repo_dir.is_dir() and recorded and source == str(repo_dir.resolve())):
        return None
    if _lock.source_digest(repo_dir) == recorded:
        return None
    plan = plan_apply(project, repo_dir)
    found = _reviewed.lookup(repo_root(repo_dir), project)
    return RepoChanges(
        plan=plan,
        adds_changed=tuple(f"{i.kind} {i.name}" for i in plan.items if i.action != "skip"),
        runs_changed=runs_changed(project, repo_dir),
        review=classify_directory(repo_dir),
        allowed_on=found.date if found else "",
    )
