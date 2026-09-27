"""``docket pod <p> apply <dir>``: compose the pre-existing writers (``core.archetypes.
add_user_archetype``, member provisioning, the pipeline bind, and ``core.pod.PodSettings``)
into one operation, driven by a small ``pod.yaml`` manifest (``members``, ``settings``,
``pipeline``) alongside the same ``roles/*.yaml``/``pipeline.yaml`` shape the shipped recipes
already ship. A role goes into *project*'s own pod-scoped overlay (``core.config.
pod_config_dir(project)/roles.json``), never the global one: ``core/pod.py``'s roster helpers
(``_role_names``/``parse_member_id``, which ``pod_full_roster``/``members_of`` depend on to
resolve a pipeline's roster) resolve that pod overlay too (see ``_plan_roles``), matching what
``docket roles add --pod <p> roles/<file>.yaml`` already did by hand. ``plan_apply`` is
pure (reads only) and validates everything -- roles, the roster the pipeline would resolve
against *after* ``members``, and every setting -- before ``apply`` writes anything. Idempotent:
an item already matching what is on disk plans as ``skip``; nothing is ever removed."""

from __future__ import annotations

import contextlib
import hashlib
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import docket.config as _cfg
from docket.core import archetypes as _arch
from docket.core import dispatch as _dispatch
from docket.core import fleet as _fleet
from docket.core import models_policy as _mp
from docket.core import orchestrator as _orch
from docket.core import pipeline as _pipeline
from docket.core import pod
from docket.core import pod_provisioning as _pp
from docket.core import policy as _policy
from docket.core import schedule as _sched
from docket.core.audit import audit_log

_MANIFEST_KEYS = frozenset({"members", "settings", "pipeline", "kind", "name", "description"})

ApplyAction = Literal["add", "replace", "skip"]


class PodApplyError(ValueError):
    """*dir*, or something inside it, cannot be applied to this pod -- an unresolvable role,
    an invalid setting, or a pipeline step the resulting roster cannot run. Raised only by
    ``plan_apply``, before anything is written."""


@dataclass(frozen=True)
class ApplyItem:
    """One planned change: ``kind`` (role/policy/plugin/member/pipeline/setting), the thing
    named, and whether applying it would add, replace, or skip (already matches disk)."""

    kind: Literal["role", "policy", "plugin", "skill", "member", "pipeline", "setting"]
    name: str
    action: ApplyAction


@dataclass(frozen=True)
class _RoleWrite:
    doc: dict[str, Any]


@dataclass(frozen=True)
class _PolicyWrite:
    name: str
    text: str


@dataclass(frozen=True)
class _PluginWrite:
    name: str
    source: bytes


@dataclass(frozen=True)
class _SkillWrite:
    """One skill's complete file set to write into the pod's own ``config/skills/<name>/`` --
    every relative path (POSIX-separated) inside the skill's own directory paired with its
    bytes, ``SKILL.md`` included."""

    name: str
    files: tuple[tuple[str, bytes], ...]


@dataclass(frozen=True)
class _MemberWrite:
    member: pod.PodMember
    codebase: str
    stack: str
    description: str
    project_key: str
    work_dir: str
    blueprint_name: str


@dataclass(frozen=True)
class _PipelineWrite:
    text: str
    digest: str


@dataclass(frozen=True)
class _SettingWrite:
    key: str
    value: float | int | str


@dataclass(frozen=True)
class ApplyPlan:
    """The full set of planned items plus the data ``apply`` needs to write them --
    opaque to a caller beyond ``items`` and ``has_changes``."""

    project: str
    directory: Path
    items: tuple[ApplyItem, ...]
    _role_writes: tuple[_RoleWrite, ...] = field(default=())
    _policy_writes: tuple[_PolicyWrite, ...] = field(default=())
    _plugin_writes: tuple[_PluginWrite, ...] = field(default=())
    _skill_writes: tuple[_SkillWrite, ...] = field(default=())
    _member_writes: tuple[_MemberWrite, ...] = field(default=())
    _pipeline_write: _PipelineWrite | None = field(default=None)
    _setting_writes: tuple[_SettingWrite, ...] = field(default=())

    def has_changes(self) -> bool:
        return any(item.action != "skip" for item in self.items)


@dataclass(frozen=True)
class ApplyResult:
    """What ``apply`` actually did -- the same items ``plan_apply`` returned, now written."""

    project: str
    items: tuple[ApplyItem, ...]


def _dump_yaml_file(path: Path, doc: dict[str, Any], *, schema_header: str = "") -> None:
    """Write *doc* to *path* as YAML, key order preserved. *schema_header* -- when given -- is
    written first, an editor-autocomplete comment pointing at the copied schema copy."""
    try:
        import yaml as _yaml  # type: ignore[import-untyped]
    except ImportError:
        raise PodApplyError("PyYAML not installed -- run: pip install pyyaml") from None
    body = _yaml.safe_dump(doc, sort_keys=False)
    path.write_text(f"{schema_header}{body}" if schema_header else body, encoding="utf-8")


def _schema_header(directory: Path, dest_path: Path, kind: str) -> str:
    """The `# yaml-language-server:` comment line for a file ``export_pod`` writes at
    *dest_path*, pointing at *kind*'s schema copied into ``<directory>/.schemas/``."""
    schema_path = directory / ".schemas" / f"{kind}.schema.json"
    rel = os.path.relpath(schema_path, start=dest_path.parent).replace(os.sep, "/")
    if not rel.startswith("."):
        rel = f"./{rel}"
    return f"# yaml-language-server: $schema={rel}\n"


def unresolvable_pipeline_steps(plan: _orch.ExecutionPlan, project: str) -> list[str]:
    """Every unit step this pod's roster cannot run against *plan* -- shared by
    ``docket pod <p> config set pipeline`` and this module so the two can never disagree."""
    problems: list[str] = []
    for node in plan.nodes:
        units = node.children if isinstance(node, _orch.PlannedGroup) else (node,)
        for unit in units:
            if unit.run:
                continue
            if unit.role is not None and unit.skipped:
                problems.append(f"step '{unit.step_id}': role '{unit.role}' not in pod '{project}'")
            elif unit.agent is not None and pod.pod_of(unit.agent) != project:
                problems.append(
                    f"step '{unit.step_id}': agent '{unit.agent}' is not a member of pod '{project}'"
                )
    return problems


def resolve_recipe(name_or_dir: str) -> Path:
    """*name_or_dir* as a directory path, else the operator's own
    ``config.user_recipes_dir()/<name>``, else a shipped recipe under ``config.recipes_dir()``.
    Raises ``PodApplyError`` naming both scopes' recipe names when none resolves."""
    candidate = Path(name_or_dir)
    if candidate.is_dir():
        return candidate
    operator_dir = _cfg.user_recipes_dir()
    operator_candidate = operator_dir / name_or_dir
    if operator_candidate.is_dir():
        return operator_candidate
    shipped = _cfg.recipes_dir() / name_or_dir
    if shipped.is_dir():
        return shipped
    operator_names = (
        sorted(p.name for p in operator_dir.iterdir() if p.is_dir())
        if operator_dir.is_dir()
        else []
    )
    shipped_names = sorted(p.name for p in _cfg.recipes_dir().iterdir() if p.is_dir())
    raise PodApplyError(
        f"unknown recipe {name_or_dir!r}; operator: {', '.join(operator_names)}; "
        f"shipped: {', '.join(shipped_names)}"
    )


@dataclass(frozen=True)
class RecipeSummary:
    """What a directory brings, derived from its contents, never a declared field (ADR 0013
    §1 rule 1). ``pipeline`` is the bound pipeline's own ``name`` (or ``""``); ``description``
    is ``pod.yaml``'s own optional prose (or ``""``)."""

    roles: int
    policies: int
    plugins: int
    skills: int
    members: int
    settings: int
    pipeline: str
    description: str

    def render(self) -> str:
        """One line, every count always shown, in a fixed order."""
        return (
            f"roles {self.roles} · policies {self.policies} · members {self.members} · "
            f"pipeline {self.pipeline} · plugins {self.plugins} · skills {self.skills} · "
            f"settings {self.settings}"
        )


def _recipe_manifest(directory: Path) -> dict[str, Any]:
    """*directory*'s ``pod.yaml``, loaded and refined like ``plan_apply`` does, or ``{}`` when
    absent or unreadable -- ``summarize_recipe`` reads only, it never raises for an invalid
    manifest (``plan_apply`` is what refuses to apply one)."""
    manifest_file = directory / "pod.yaml"
    if not manifest_file.is_file():
        return {}
    from docket.core import config_docs as _config_docs

    try:
        return _config_docs.load_document(manifest_file, kind="pod").doc
    except _config_docs.ConfigDocError:
        return {}


def _recipe_pipeline_file(directory: Path, pipeline_name: str | None) -> Path | None:
    """The pipeline file a bare *directory* (no project, no roster) would bind -- the same
    filename resolution ``_plan_pipeline`` uses before it goes on to validate against a roster."""
    if pipeline_name:
        candidate = directory / str(pipeline_name)
        return candidate if candidate.is_file() else None
    default_file = directory / "pipeline.yaml"
    return default_file if default_file.is_file() else None


def _config_glob(directory: Path) -> list[Path]:
    """Every ``*.yaml``/``*.yml``/``*.json`` directly under *directory* -- the same file set
    ``core.config_docs.discover_config_paths`` counts for ``roles/``/``policies/``."""
    return [p for pattern in ("*.yaml", "*.yml", "*.json") for p in directory.glob(pattern)]


def summarize_recipe(directory: Path) -> RecipeSummary:
    """Derive what *directory* brings: read-only, independent of any pod or role registry
    (unlike ``plan_apply``). Used by ``docket validate``, ``docket pod <p> apply``, and
    ``init --recipe`` so a recipe's scope is always shown the same way, wherever applied."""
    manifest = _recipe_manifest(directory)

    roles_dir = directory / "roles"
    roles = len(_config_glob(roles_dir)) if roles_dir.is_dir() else 0

    policies_dir = directory / "policies"
    policies = len(_config_glob(policies_dir)) if policies_dir.is_dir() else 0

    plugins_dir = directory / "plugins"
    plugins = len(list(plugins_dir.glob("*.py"))) if plugins_dir.is_dir() else 0

    skills_dir = directory / "skills"
    skills = (
        sum(1 for p in skills_dir.iterdir() if p.is_dir() and (p / "SKILL.md").is_file())
        if skills_dir.is_dir()
        else 0
    )

    members_raw = manifest.get("members")
    members = len(members_raw) if isinstance(members_raw, list) else 0
    settings_raw = manifest.get("settings")
    settings = len(settings_raw) if isinstance(settings_raw, dict) else 0

    pipeline_name = manifest.get("pipeline")
    pipeline_file = _recipe_pipeline_file(
        directory, pipeline_name if isinstance(pipeline_name, str) else None
    )
    pipeline = ""
    if pipeline_file is not None:
        result = _pipeline.load_pipeline(pipeline_file.read_text(encoding="utf-8"))
        if result.spec is not None:
            pipeline = result.spec.name

    description_raw = manifest.get("description")
    description = description_raw if isinstance(description_raw, str) else ""

    return RecipeSummary(
        roles=roles,
        policies=policies,
        plugins=plugins,
        skills=skills,
        members=members,
        settings=settings,
        pipeline=pipeline,
        description=description,
    )


@dataclass(frozen=True)
class RecipeInfo:
    """One recipe reachable by name: which scope resolved it (nearest wins, ADR 0013 SS1 rule
    4), where it lives on disk, and what it brings (``summarize_recipe``)."""

    name: str
    scope: Literal["operator", "shipped"]
    directory: Path
    summary: RecipeSummary


def list_recipes() -> list[RecipeInfo]:
    """Every recipe reachable by name across both scopes, operator recipes winning over a
    same-named shipped one -- the same resolution order ``resolve_recipe`` applies to a single
    lookup. Sorted by name; used by ``docket recipes list``/``show``."""
    by_name: dict[str, RecipeInfo] = {}
    shipped_dir = _cfg.recipes_dir()
    if shipped_dir.is_dir():
        for entry in sorted(shipped_dir.iterdir()):
            if entry.is_dir():
                by_name[entry.name] = RecipeInfo(
                    name=entry.name,
                    scope="shipped",
                    directory=entry,
                    summary=summarize_recipe(entry),
                )
    operator_dir = _cfg.user_recipes_dir()
    if operator_dir.is_dir():
        for entry in sorted(operator_dir.iterdir()):
            if entry.is_dir():
                by_name[entry.name] = RecipeInfo(
                    name=entry.name,
                    scope="operator",
                    directory=entry,
                    summary=summarize_recipe(entry),
                )
    return sorted(by_name.values(), key=lambda info: info.name)


def _plan_roles(
    directory: Path, base_registry: _arch.ArchetypeRegistry, project: str
) -> tuple[list[ApplyItem], list[_RoleWrite], dict[str, _arch.RoleArchetype]]:
    """Plan ``roles/*.yaml`` into *project*'s own pod-scoped role overlay, the same target
    ``docket roles add --pod <project>`` writes to -- never the global overlay
    (see module docstring)."""
    items: list[ApplyItem] = []
    writes: list[_RoleWrite] = []
    merged = dict(base_registry.archetypes)
    roles_dir = directory / "roles"
    if not roles_dir.is_dir():
        return items, writes, merged
    from docket.core import config_docs as _config_docs

    for role_file in sorted(roles_dir.glob("*.yaml")):
        try:
            doc = _config_docs.load_document(role_file, kind="role").doc
        except _config_docs.ConfigDocError as exc:
            raise PodApplyError(str(exc)) from exc
        name = str(doc.get("name", "")).strip()
        if not name:
            raise PodApplyError(f"{role_file}: archetype has no top-level 'name'")
        try:
            arch = _arch.from_wire(name, doc)
        except _arch.ArchetypeError as exc:
            raise PodApplyError(f"{role_file}: {exc}") from exc
        existing = base_registry.get(name)
        already_pod = base_registry.source_of(name) == f"pod:{project}"
        if already_pod and existing is not None and existing.to_wire() == arch.to_wire():
            action: ApplyAction = "skip"
        else:
            action = "replace" if already_pod else "add"
            writes.append(_RoleWrite(doc=doc))
        merged[name] = arch
        items.append(ApplyItem(kind="role", name=name, action=action))
    return items, writes, merged


def _plan_policies(directory: Path, project: str) -> tuple[list[ApplyItem], list[_PolicyWrite]]:
    """Plan ``policies/*.json|*.yaml|*.yml`` into *project*'s own policy directory -- the same
    one ``core.policy.policy_files`` reads and ``_export_policies`` copies, never the fleet-wide
    ``$POLICIES_DIR``. Each file must pass ``core.policy.validate_policy`` first."""
    items: list[ApplyItem] = []
    writes: list[_PolicyWrite] = []
    policies_dir = directory / "policies"
    if not policies_dir.is_dir():
        return items, writes
    dest_dir = _cfg.pod_config_dir(project) / "policies"
    policy_files = sorted(
        p for pattern in ("*.json", "*.yaml", "*.yml") for p in policies_dir.glob(pattern)
    )
    for policy_file in policy_files:
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
    ``core.plugins.discover`` reads and ``_export_plugins`` copies back, by sha256: an installed
    copy with the same hash is left alone, any other content is replaced."""
    items: list[ApplyItem] = []
    writes: list[_PluginWrite] = []
    plugins_dir = directory / "plugins"
    if not plugins_dir.is_dir():
        return items, writes
    dest_dir = _cfg.pod_config_dir(project) / "plugins"
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


def _directory_files(directory: Path) -> tuple[tuple[str, bytes], ...]:
    """Every regular file under *directory*, as (posix-relative-path, bytes) pairs, sorted by
    path -- the shape both the sha256 comparison and the actual write in ``apply`` use."""
    return tuple(
        (p.relative_to(directory).as_posix(), p.read_bytes())
        for p in sorted(p for p in directory.rglob("*") if p.is_file())
    )


def _skill_digest(files: tuple[tuple[str, bytes], ...]) -> bytes:
    """Sha256 digest over *files*' sorted relative paths and bytes -- the same shape
    ``directory_digest`` hashes a whole recipe directory with, scoped to one skill."""
    digest = hashlib.sha256()
    for rel, data in files:
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(data)
        digest.update(b"\0")
    return digest.digest()


def _plan_skills(directory: Path, project: str) -> tuple[list[ApplyItem], list[_SkillWrite]]:
    """Plan each ``skills/<name>/`` whole into *project*'s own ``config/skills/<name>/``, by a
    sha256 over the skill's own sorted relative paths and bytes: an installed copy with the
    same hash plans ``skip``, any other content or none yet plans ``replace``/``add``."""
    items: list[ApplyItem] = []
    writes: list[_SkillWrite] = []
    skills_dir = directory / "skills"
    if not skills_dir.is_dir():
        return items, writes
    dest_root = _cfg.pod_config_dir(project) / "skills"
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
    roster = dict(_dispatch.pod_full_roster(project))

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
        if canon == "programmer":
            canon = "implementer"
        if not canon:
            continue
        arch = registry.get(canon)
        if arch is None:
            raise PodApplyError(f"pod.yaml: unknown pod role {raw_role!r}")
        if canon in roster:
            items.append(ApplyItem(kind="member", name=canon, action="skip"))
            continue
        mid = pod.member_id(project, canon)
        model = _mp.resolve_role_model(arch.resolved_policy_role, role_models, project=project)
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
        raise PodApplyError(f"{pipeline_file}: invalid pipeline: {'; '.join(result.errors)}")
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


def _plan_settings(
    project: str, raw_settings: dict[str, Any]
) -> tuple[list[ApplyItem], list[_SettingWrite]]:
    items: list[ApplyItem] = []
    writes: list[_SettingWrite] = []
    if not raw_settings:
        return items, writes
    try:
        settings_now = pod.PodSettings.load_for(project)
    except pod.PodSettingsError as exc:
        raise PodApplyError(str(exc)) from exc
    for key, value in raw_settings.items():
        if key == "pipeline":
            raise PodApplyError("pod.yaml: 'pipeline' belongs at the top level, not 'settings'")
        if key not in pod.PodSettings.KEYS:
            raise PodApplyError(f"pod.yaml: unknown pod setting {key!r}")
        str_value = ",".join(str(v) for v in value) if isinstance(value, list) else str(value)
        try:
            coerced = pod.PodSettings.coerce(key, str_value)
        except pod.PodSettingsError as exc:
            raise PodApplyError(str(exc)) from exc
        current_value, source = settings_now.value_and_source(key, project)
        if current_value == coerced:
            items.append(ApplyItem(kind="setting", name=key, action="skip"))
            continue
        items.append(
            ApplyItem(kind="setting", name=key, action="replace" if source == "set" else "add")
        )
        writes.append(_SettingWrite(key=key, value=coerced))
    return items, writes


def directory_digest(directory: Path) -> str:
    """Sha256 hex digest over the sorted relative paths and bytes of every file
    `discover_config_paths` returns, plus any `plugins/*.py` and any `skills/**` file
    (never the generated `.schemas/`); `apply` records it as `configDigest`."""
    from docket.core import config_docs as _config_docs

    paths = list(_config_docs.discover_config_paths(directory))
    plugins_dir = directory / "plugins"
    if plugins_dir.is_dir():
        paths.extend(sorted(plugins_dir.glob("*.py")))
    skills_dir = directory / "skills"
    if skills_dir.is_dir():
        paths.extend(sorted(p for p in skills_dir.rglob("*") if p.is_file()))
    ordered = sorted(paths, key=lambda p: p.relative_to(directory).as_posix())

    digest = hashlib.sha256()
    for path in ordered:
        digest.update(path.relative_to(directory).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def plan_apply(project: str, directory: Path) -> ApplyPlan:
    """Validate applying *directory* to *project* and return the plan. Read-only:
    no role overlay, policy, member, pipeline, or setting is ever written here."""
    if not directory.is_dir():
        raise PodApplyError(f"recipe directory not found: {directory}")
    try:
        _dispatch.pod_pipeline(project)
    except _dispatch.DispatchError as exc:
        raise PodApplyError(str(exc)) from exc

    from docket.core import config_docs as _config_docs

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

    base_registry = _arch.load_registry(project)
    role_items, role_writes, merged_archetypes = _plan_roles(directory, base_registry, project)
    augmented = _arch.ArchetypeRegistry(merged_archetypes, project=project)

    policy_items, policy_writes = _plan_policies(directory, project)

    plugin_items, plugin_writes = _plan_plugins(directory, project)

    skill_items, skill_writes = _plan_skills(directory, project)

    member_items, member_writes, roster_after = _plan_members(project, member_roles, augmented)

    pipeline_item, pipeline_write = _plan_pipeline(
        directory, pipeline_name, project, roster_after, augmented
    )

    setting_items, setting_writes = _plan_settings(project, raw_settings)

    items = [*role_items, *policy_items, *plugin_items, *skill_items, *member_items]
    if pipeline_item is not None:
        items.append(pipeline_item)
    items.extend(setting_items)

    return ApplyPlan(
        project=project,
        directory=directory,
        items=tuple(items),
        _role_writes=tuple(role_writes),
        _policy_writes=tuple(policy_writes),
        _plugin_writes=tuple(plugin_writes),
        _skill_writes=tuple(skill_writes),
        _member_writes=tuple(member_writes),
        _pipeline_write=pipeline_write,
        _setting_writes=tuple(setting_writes),
    )


def apply(plan: ApplyPlan) -> ApplyResult:
    """Write every non-``skip`` item in *plan* (role -> policy -> plugin -> member -> pipeline
    -> setting order). Audits ``pod.apply`` only on change; records ``configSource``/
    ``configDigest`` every time, all-``skip`` included (see below)."""
    lead_id = pod.member_id(plan.project, "lead")

    for role_write in plan._role_writes:
        _arch.add_user_archetype(role_write.doc, plan.project)

    if plan._policy_writes:
        policies_dir = _cfg.pod_config_dir(plan.project) / "policies"
        policies_dir.mkdir(parents=True, exist_ok=True)
        with contextlib.suppress(OSError):
            _cfg.PODS_DIR.chmod(0o700)
            policies_dir.parent.parent.chmod(0o700)  # PODS_DIR/<project>
            policies_dir.parent.chmod(0o700)  # pod_config_dir(project)
            policies_dir.chmod(0o700)
        for policy_write in plan._policy_writes:
            dest = policies_dir / policy_write.name
            dest.write_text(policy_write.text, encoding="utf-8")
            dest.chmod(0o600)

    if plan._plugin_writes:
        plugins_dir = _cfg.pod_config_dir(plan.project) / "plugins"
        plugins_dir.mkdir(parents=True, exist_ok=True)
        with contextlib.suppress(OSError):
            _cfg.PODS_DIR.chmod(0o700)
            plugins_dir.parent.parent.chmod(0o700)  # PODS_DIR/<project>
            plugins_dir.parent.chmod(0o700)  # pod_config_dir(project)
            plugins_dir.chmod(0o700)
        for plugin_write in plan._plugin_writes:
            dest = plugins_dir / plugin_write.name
            dest.write_bytes(plugin_write.source)
            dest.chmod(0o600)

    if plan._skill_writes:
        skills_dir = _cfg.pod_config_dir(plan.project) / "skills"
        skills_dir.mkdir(parents=True, exist_ok=True)
        with contextlib.suppress(OSError):
            _cfg.PODS_DIR.chmod(0o700)
            skills_dir.parent.parent.chmod(0o700)  # PODS_DIR/<project>
            skills_dir.parent.chmod(0o700)  # pod_config_dir(project)
            skills_dir.chmod(0o700)
        for skill_write in plan._skill_writes:
            dest = skills_dir / skill_write.name
            dest.mkdir(parents=True, exist_ok=True)
            with contextlib.suppress(OSError):
                dest.chmod(0o700)
            for rel, data in skill_write.files:
                file_dest = dest / rel
                file_dest.parent.mkdir(parents=True, exist_ok=True)
                file_dest.write_bytes(data)
                file_dest.chmod(0o600)

    for member_write in plan._member_writes:
        ok, msg, _fallback = _pp.provision_member(
            member_write.member,
            codebase=member_write.codebase,
            stack=member_write.stack,
            description=member_write.description,
            project=plan.project,
            project_key=member_write.project_key,
            work_dir=member_write.work_dir,
            blueprint_name=member_write.blueprint_name,
        )
        if not ok:
            raise PodApplyError(f"failed to provision {member_write.member.member_id}: {msg}")

    if plan._pipeline_write is not None:
        dest = pod.bound_pipeline_path(plan.project)
        dest.write_text(plan._pipeline_write.text, encoding="utf-8")
        dest.chmod(0o600)
        _fleet.meta_set(lead_id, "pipeline", plan._pipeline_write.digest)

    for setting_write in plan._setting_writes:
        if setting_write.key == "schedule":
            _sched.set_schedule(_cfg.SCHEDULE_FILE, plan.project, str(setting_write.value))
        _fleet.meta_set(lead_id, setting_write.key, setting_write.value)

    if plan.has_changes():
        summary = ";".join(f"{item.kind}:{item.name}:{item.action}" for item in plan.items)
        audit_log("pod.apply", f"project={plan.project} dir={plan.directory} items={summary}")

    # The configuration-of-record (ADR 0012 §2 rule 5): recorded after every plan
    # `plan_apply` validated, an all-`skip` plan included, so composing a second, identical
    # directory at another path still moves the record -- never by `docket pod <p> config set`
    # (see `pod.PodSettings.RECORDED_KEYS`). The audit entry above keeps its own,
    # narrower "only when something changed" rule.
    _fleet.meta_set(lead_id, "configSource", str(plan.directory.resolve()))
    _fleet.meta_set(lead_id, "configDigest", directory_digest(plan.directory))

    return ApplyResult(project=plan.project, items=plan.items)


def _export_roles(project: str, directory: Path) -> None:
    """Write *project*'s own pod-overlay role entries -- never a built-in, starter, or
    global-``user`` one -- as short-form ``roles/<name>.yaml`` (``to_short_role``, the inverse
    of ``normalize_role``) plus its paired ``roles/<name>.md`` instructions file."""
    registry = _arch.load_registry(project)
    names = sorted(n for n in registry.role_names() if registry.source_of(n) == f"pod:{project}")
    if not names:
        return
    roles_dir = directory / "roles"
    roles_dir.mkdir(parents=True, exist_ok=True)
    for name in names:
        arch = registry.get(name)
        assert arch is not None  # name came from this same registry's role_names()
        doc, markdown = _arch.to_short_role(arch)
        role_path = roles_dir / f"{name}.yaml"
        _dump_yaml_file(role_path, doc, schema_header=_schema_header(directory, role_path, "role"))
        (roles_dir / f"{name}.md").write_text(markdown, encoding="utf-8")


def _export_policies(project: str, directory: Path) -> None:
    """Write *project*'s own policy directory's files as short-form YAML ``policies/<stem>.yaml``
    (``core.policy.to_short_policy``, the inverse of ``normalize_policy``) -- never a file from
    the fleet-wide ``$POLICIES_DIR``."""
    src_dir = _cfg.pod_config_dir(project) / "policies"
    files = (
        sorted(p for pattern in ("*.json", "*.yaml", "*.yml") for p in src_dir.glob(pattern))
        if src_dir.is_dir()
        else []
    )
    if not files:
        return
    dest_dir = directory / "policies"
    dest_dir.mkdir(parents=True, exist_ok=True)
    for f in files:
        short = _policy.to_short_policy(_policy.read_policy(f))
        policy_path = dest_dir / f"{f.stem}.yaml"
        _dump_yaml_file(
            policy_path, short, schema_header=_schema_header(directory, policy_path, "policy")
        )


def _export_plugins(project: str, directory: Path) -> None:
    """Copy *project*'s own ``config/plugins/`` files byte-for-byte as ``plugins/<name>.py``
    -- never a file from a codebase, since a plugin is only ever applied through this pod's
    own scope."""
    src_dir = _cfg.pod_config_dir(project) / "plugins"
    files = sorted(src_dir.glob("*.py")) if src_dir.is_dir() else []
    if not files:
        return
    dest_dir = directory / "plugins"
    dest_dir.mkdir(parents=True, exist_ok=True)
    for f in files:
        (dest_dir / f.name).write_bytes(f.read_bytes())


def _export_skills(project: str, directory: Path) -> None:
    """Copy *project*'s own ``config/skills/`` byte-for-byte into ``skills/<name>/`` -- unlike
    a role or policy, a skill is not regenerated, since it carries its own files rather than a
    wire document this module knows how to re-render."""
    src_dir = _cfg.pod_config_dir(project) / "skills"
    names = sorted(p.name for p in src_dir.iterdir() if p.is_dir()) if src_dir.is_dir() else []
    if not names:
        return
    dest_root = directory / "skills"
    for name in names:
        src = src_dir / name
        if not (src / "SKILL.md").is_file():
            continue
        dest = dest_root / name
        for rel, data in _directory_files(src):
            file_dest = dest / rel
            file_dest.parent.mkdir(parents=True, exist_ok=True)
            file_dest.write_bytes(data)


def _export_pipeline(project: str, directory: Path) -> None:
    """Copy *project*'s bound pipeline copy (if ``PodSettings.pipeline`` is set) as
    ``pipeline.yaml`` -- the default filename ``apply`` resolves with no explicit
    ``pod.yaml`` ``pipeline`` key."""
    src = pod.bound_pipeline_path(project)
    if not src.is_file():
        return
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "pipeline.yaml").write_text(src.read_text(encoding="utf-8"), encoding="utf-8")


def _export_manifest(project: str, directory: Path) -> None:
    """Write ``pod.yaml`` with ``members`` (every non-Lead role this pod's roster has) and
    ``settings`` (every ``PodSettings`` key whose stored value differs from that model's own
    default) -- never a ``pipeline`` key (see ``_export_pipeline``'s docstring)."""
    roster = _dispatch.pod_full_roster(project)
    members = [role for role, _mid in sorted(roster.items()) if role != "lead"]

    settings_doc = pod.PodSettings.load_for(project)
    settings_out: dict[str, Any] = {}
    for key in pod.PodSettings.KEYS:
        if key == "pipeline":
            continue  # top-level file, never a `settings` entry (see `_plan_settings`)
        value, source = settings_doc.value_and_source(key, project)
        if source == "set" and value is not None:
            settings_out[key] = value

    manifest: dict[str, Any] = {"kind": "pod", "name": project, "members": members}
    if settings_out:
        manifest["settings"] = settings_out
    pod_path = directory / "pod.yaml"
    _dump_yaml_file(pod_path, manifest, schema_header=_schema_header(directory, pod_path, "pod"))


def _export_schemas(directory: Path) -> None:
    """Copy the four published config-v1 JSON Schemas into ``<directory>/.schemas/`` so every
    exported YAML's `# yaml-language-server:` header resolves without reaching outside the
    export -- ``apply``/``discover_config_paths`` never look under ``.schemas/``."""
    src_dir = _cfg.config_schemas_dir()
    dest_dir = directory / ".schemas"
    dest_dir.mkdir(parents=True, exist_ok=True)
    for kind in ("role", "pipeline", "policy", "pod"):
        src = src_dir / f"{kind}.schema.json"
        if src.is_file():
            (dest_dir / src.name).write_text(src.read_text(encoding="utf-8"), encoding="utf-8")


def export_pod(project: str, directory: Path) -> None:
    """Write *project*'s own scope into *directory*, the same shape ``apply`` reads back.
    Global scope is never written; the non-empty-*directory* refusal is the CLI's job."""
    if not _pp.pod_member_ids(project):
        raise PodApplyError(f"no pod found for '{project}'")
    directory.mkdir(parents=True, exist_ok=True)
    _export_roles(project, directory)
    _export_policies(project, directory)
    _export_plugins(project, directory)
    _export_skills(project, directory)
    _export_pipeline(project, directory)
    _export_manifest(project, directory)
    _export_schemas(directory)
