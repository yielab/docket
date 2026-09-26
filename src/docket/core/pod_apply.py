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

_MANIFEST_KEYS = frozenset({"members", "settings", "pipeline"})

ApplyAction = Literal["add", "replace", "skip"]


class PodApplyError(ValueError):
    """*dir*, or something inside it, cannot be applied to this pod -- an unresolvable role,
    an invalid setting, or a pipeline step the resulting roster cannot run. Raised only by
    ``plan_apply``, before anything is written."""


@dataclass(frozen=True)
class ApplyItem:
    """One planned change: ``kind`` (role/policy/member/pipeline/setting), the thing named, and
    whether applying it would add, replace, or skip (already matches disk)."""

    kind: Literal["role", "policy", "member", "pipeline", "setting"]
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


def _load_yaml_mapping(path: Path) -> dict[str, Any]:
    """Parse *path* as a YAML mapping, or ``{}`` for a missing/empty file."""
    if not path.is_file():
        return {}
    try:
        import yaml as _yaml  # type: ignore[import-untyped]
    except ImportError:
        raise PodApplyError("PyYAML not installed -- run: pip install pyyaml") from None
    try:
        doc = _yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise PodApplyError(f"{path}: YAML parse error: {exc}") from exc
    if doc is None:
        return {}
    if not isinstance(doc, dict):
        raise PodApplyError(f"{path}: must be a mapping")
    return doc


def _dump_yaml_file(path: Path, doc: dict[str, Any]) -> None:
    """Write *doc* to *path* as YAML, key order preserved (``export_pod``'s writer side
    of ``_load_yaml_mapping``)."""
    try:
        import yaml as _yaml
    except ImportError:
        raise PodApplyError("PyYAML not installed -- run: pip install pyyaml") from None
    path.write_text(_yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")


def unresolvable_pipeline_steps(plan: _orch.ExecutionPlan, project: str) -> list[str]:
    """Every unit step this pod's roster cannot run against *plan* -- shared by
    ``docket pod <p> config set pipeline`` and this module so the two can never disagree."""
    problems: list[str] = []
    for node in plan.nodes:
        units = node.children if isinstance(node, _orch.PlannedGroup) else (node,)
        for unit in units:
            if unit.role is not None and unit.skipped:
                problems.append(f"step '{unit.step_id}': role '{unit.role}' not in pod '{project}'")
            elif unit.agent is not None and pod.pod_of(unit.agent) != project:
                problems.append(
                    f"step '{unit.step_id}': agent '{unit.agent}' is not a member of pod '{project}'"
                )
    return problems


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
    for role_file in sorted(roles_dir.glob("*.yaml")):
        doc = _arch.parse_yaml_file(str(role_file))
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
        if dest.is_file() and dest.read_text(encoding="utf-8") == text:
            action: ApplyAction = "skip"
        else:
            action = "replace" if dest.is_file() else "add"
            writes.append(_PolicyWrite(name=policy_file.name, text=text))
        items.append(ApplyItem(kind="policy", name=policy_file.name, action=action))
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
        model = _mp.resolve_role_model(arch.resolved_policy_role, role_models)
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


def plan_apply(project: str, directory: Path) -> ApplyPlan:
    """Validate applying *directory* to *project* and return the plan. Read-only:
    no role overlay, policy, member, pipeline, or setting is ever written here."""
    if not directory.is_dir():
        raise PodApplyError(f"recipe directory not found: {directory}")
    try:
        _dispatch.pod_pipeline(project)
    except _dispatch.DispatchError as exc:
        raise PodApplyError(str(exc)) from exc

    manifest = _load_yaml_mapping(directory / "pod.yaml")
    unknown_keys = set(manifest) - _MANIFEST_KEYS
    if unknown_keys:
        raise PodApplyError(f"pod.yaml: unknown key(s): {', '.join(sorted(unknown_keys))}")

    member_roles = manifest.get("members", [])
    if not isinstance(member_roles, list):
        raise PodApplyError("pod.yaml: 'members' must be a list")
    raw_settings = manifest.get("settings", {}) or {}
    if not isinstance(raw_settings, dict):
        raise PodApplyError("pod.yaml: 'settings' must be a mapping")
    pipeline_name = manifest.get("pipeline")

    base_registry = _arch.load_registry(project)
    role_items, role_writes, merged_archetypes = _plan_roles(directory, base_registry, project)
    augmented = _arch.ArchetypeRegistry(merged_archetypes, project=project)

    policy_items, policy_writes = _plan_policies(directory, project)

    member_items, member_writes, roster_after = _plan_members(project, member_roles, augmented)

    pipeline_item, pipeline_write = _plan_pipeline(
        directory, pipeline_name, project, roster_after, augmented
    )

    setting_items, setting_writes = _plan_settings(project, raw_settings)

    items = [*role_items, *policy_items, *member_items]
    if pipeline_item is not None:
        items.append(pipeline_item)
    items.extend(setting_items)

    return ApplyPlan(
        project=project,
        directory=directory,
        items=tuple(items),
        _role_writes=tuple(role_writes),
        _policy_writes=tuple(policy_writes),
        _member_writes=tuple(member_writes),
        _pipeline_write=pipeline_write,
        _setting_writes=tuple(setting_writes),
    )


def apply(plan: ApplyPlan) -> ApplyResult:
    """Write every non-``skip`` item in *plan*, in role -> policy -> member -> pipeline ->
    setting order (a member's role must exist before it is provisioned). Audits once as
    ``pod.apply``, only when at least one item actually changed something."""
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

    return ApplyResult(project=plan.project, items=plan.items)


def _export_roles(project: str, directory: Path) -> None:
    """Write *project*'s own pod-overlay role entries -- never a built-in, starter, or
    global-``user`` one -- as ``roles/<name>.yaml``, via the same ``to_wire()`` format
    ``docket roles show``/``roles/*.yaml`` already share."""
    registry = _arch.load_registry(project)
    names = sorted(n for n in registry.role_names() if registry.source_of(n) == f"pod:{project}")
    if not names:
        return
    roles_dir = directory / "roles"
    roles_dir.mkdir(parents=True, exist_ok=True)
    for name in names:
        arch = registry.get(name)
        assert arch is not None  # name came from this same registry's role_names()
        _dump_yaml_file(roles_dir / f"{name}.yaml", arch.to_wire())


def _export_policies(project: str, directory: Path) -> None:
    """Copy *project*'s own policy directory's files byte-for-byte as ``policies/<name>.json``
    -- never a file from the fleet-wide ``$POLICIES_DIR``."""
    src_dir = _cfg.pod_config_dir(project) / "policies"
    files = sorted(src_dir.glob("*.json")) if src_dir.is_dir() else []
    if not files:
        return
    dest_dir = directory / "policies"
    dest_dir.mkdir(parents=True, exist_ok=True)
    for f in files:
        (dest_dir / f.name).write_text(f.read_text(encoding="utf-8"), encoding="utf-8")


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

    manifest: dict[str, Any] = {"members": members}
    if settings_out:
        manifest["settings"] = settings_out
    _dump_yaml_file(directory / "pod.yaml", manifest)


def export_pod(project: str, directory: Path) -> None:
    """Write *project*'s own scope (roles, policies, pipeline, manifest) into *directory*,
    the same shape ``plan_apply``/``apply`` read back. Global scope is never written; the
    non-empty-*directory*/``--force`` refusal is the CLI's job (``cli/_pod.py``), not this one's."""
    if not _pp.pod_member_ids(project):
        raise PodApplyError(f"no pod found for '{project}'")
    directory.mkdir(parents=True, exist_ok=True)
    _export_roles(project, directory)
    _export_policies(project, directory)
    _export_pipeline(project, directory)
    _export_manifest(project, directory)
