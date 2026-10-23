"""``docket pod update <dir>``: compose the pre-existing writers (``teams.roles.
add_user_archetype``, member provisioning, the pipeline bind, and ``teams.pod.PodSettings``)
into one operation, driven by a small ``pod.yaml`` manifest (``members``, ``settings``,
``pipeline``) alongside the same ``roles/*.yaml``/``pipeline.yaml`` shape the shipped recipes
already ship. A role goes into *project*'s own pod-scoped overlay (``core.config.
pod_config_dir(project)/roles.json``), never the global one: ``teams/pod.py``'s roster helpers
(``_role_names``/``parse_member_id``, which ``pod_full_roster``/``members_of`` depend on to
resolve a pipeline's roster) resolve that pod overlay too (see ``_plan_roles``), matching what
``docket pod update roles/<file>.yaml`` already did by hand. ``plan_apply`` is
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

import docket.kernel.templates as _templates
from docket.agent.tools import mcp_tools as _mcp_tools
from docket.governance import policy as _policy
from docket.governance.audit import audit_log
from docket.hops.workspace import prepare as _prepare
from docket.hops.workspace import protected_paths as _protected
from docket.kernel.errors import InvalidInput
from docket.kernel.home import current_home
from docket.models import document_fields as _documents
from docket.models import selection as _mp
from docket.observability import exporter as _exporter
from docket.pipeline.application import schedule as _sched
from docket.pipeline.application import steps as _steps
from docket.pipeline.domain import plan as _orch
from docket.pipeline.domain import spec as _pipeline
from docket.tasks.application import queue as _queue
from docket.tasks.domain import task as _task
from docket.teams import fleet as _fleet
from docket.teams import pod
from docket.teams import pod_provisioning as _pp
from docket.teams import roles as _arch

_MANIFEST_KEYS = frozenset(
    {
        "members",
        "settings",
        "pipeline",
        "kind",
        "name",
        "description",
        "exporters",
        "prepare",
        "protects",
    }
)

# The same name shape `observability.exporter.ExporterSpec` validates -- checked here too so a
# credential-shaped string or a URL is refused for what it is, before a catalog lookup
# (`Catalog.get` on a non-string would raise `TypeError` on the dict membership test).

ApplyAction = Literal["add", "replace", "skip"]


class PodApplyError(InvalidInput):
    """*dir*, or something inside it, cannot be applied to this pod -- an unresolvable role,
    an invalid setting, or a pipeline step the resulting roster cannot run. Raised only by
    ``plan_apply``, before anything is written."""


@dataclass(frozen=True)
class ApplyItem:
    """One planned change: ``kind`` (role/policy/plugin/member/pipeline/setting), the thing
    named, and whether applying it would add, replace, or skip (already matches disk)."""

    kind: Literal[
        "role", "policy", "plugin", "skill", "mcp-server", "member", "pipeline", "setting"
    ]
    name: str
    action: ApplyAction
    note: str = ""


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
class _NamedPipelineWrite:
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
class _McpServerWrite:
    """The complete pod-scoped server list to write: the pod's existing servers with each
    recipe-declared one added or replaced by name."""

    servers: tuple[_mcp_tools.McpServerConfig, ...]


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
    exporters: tuple[str, ...] = field(default=())
    _role_writes: tuple[_RoleWrite, ...] = field(default=())
    _policy_writes: tuple[_PolicyWrite, ...] = field(default=())
    _plugin_writes: tuple[_PluginWrite, ...] = field(default=())
    _named_pipeline_writes: tuple[_NamedPipelineWrite, ...] = field(default=())
    _skill_writes: tuple[_SkillWrite, ...] = field(default=())
    _mcp_server_write: _McpServerWrite | None = field(default=None)
    _member_writes: tuple[_MemberWrite, ...] = field(default=())
    _pipeline_write: _PipelineWrite | None = field(default=None)
    _setting_writes: tuple[_SettingWrite, ...] = field(default=())

    def has_changes(self) -> bool:
        return any(item.action != "skip" for item in self.items)


@dataclass(frozen=True)
class ApplyResult:
    """What ``apply`` actually did -- the same items ``plan_apply`` returned, now written.
    ``exporters`` is this pod's recorded destination names (ADR 0014 rule 7) -- reported, not
    activated; the CLI renders each one's state from ``observability.exporter.activation_state``."""

    project: str
    items: tuple[ApplyItem, ...]
    exporters: tuple[str, ...] = ()


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
    ``docket pod set pipeline`` and this module so the two can never disagree."""
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
    ``Home.user_recipes_dir/<name>``, else a shipped recipe under ``templates.RECIPES_DIR``.
    Raises ``PodApplyError`` naming both scopes' recipe names when none resolves."""
    candidate = Path(name_or_dir)
    if candidate.is_dir():
        return candidate
    operator_dir = current_home().user_recipes_dir
    operator_candidate = operator_dir / name_or_dir
    if operator_candidate.is_dir():
        return operator_candidate
    shipped = _templates.RECIPES_DIR / name_or_dir
    if shipped.is_dir():
        return shipped
    operator_names = (
        sorted(p.name for p in operator_dir.iterdir() if p.is_dir())
        if operator_dir.is_dir()
        else []
    )
    shipped_names = sorted(p.name for p in _templates.RECIPES_DIR.iterdir() if p.is_dir())
    raise PodApplyError(
        f"unknown recipe {name_or_dir!r}; operator: {', '.join(operator_names)}; "
        f"shipped: {', '.join(shipped_names)}"
    )


@dataclass(frozen=True)
class RecipeSummary:
    """What a directory brings, derived from its contents, never a declared field (ADR 0013
    §1 rule 1); ``pipeline``/``description`` are the pipeline's own `name` and `pod.yaml`'s
    prose; ``exporters`` is its declared list, unvalidated here (ADR 0014 rule 7)."""

    roles: int
    policies: int
    plugins: int
    skills: int
    members: int
    settings: int
    pipeline: str
    description: str
    exporters: tuple[str, ...] = ()
    mcp_servers: tuple[str, ...] = ()
    pipelines: tuple[str, ...] = ()

    def render(self) -> str:
        """One line, every count always shown, in a fixed order; `pipeline none` when unbound;
        `· exporters`, `· mcp-servers` and `· pipelines <name>, ...` appended only when present."""
        line = (
            f"roles {self.roles} · policies {self.policies} · members {self.members} · "
            f"pipeline {self.pipeline or 'none'} · plugins {self.plugins} · skills {self.skills} · "
            f"settings {self.settings}"
        )
        if self.exporters:
            line += f" · exporters {', '.join(self.exporters)}"
        if self.mcp_servers:
            line += f" · mcp-servers {', '.join(self.mcp_servers)}"
        if self.pipelines:
            line += f" · pipelines {', '.join(self.pipelines)}"
        return line


def _recipe_manifest(directory: Path) -> dict[str, Any]:
    """*directory*'s ``pod.yaml``, loaded and refined like ``plan_apply`` does, or ``{}`` when
    absent or unreadable -- ``summarize_recipe`` reads only, it never raises for an invalid
    manifest (``plan_apply`` is what refuses to apply one)."""
    manifest_file = directory / "pod.yaml"
    if not manifest_file.is_file():
        return {}
    from docket.teams import config_docs as _config_docs

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
    ``teams.config_docs.discover_config_paths`` counts for ``roles/``/``policies/``."""
    return [p for pattern in ("*.yaml", "*.yml", "*.json") for p in directory.glob(pattern)]


def _server_files(directory: Path) -> list[Path]:
    servers_dir = directory / "mcp-servers"
    return sorted(_config_glob(servers_dir)) if servers_dir.is_dir() else []


def _declared_servers(directory: Path) -> list[_mcp_tools.McpServerConfig]:
    """Each readable ``mcp-servers/*`` document; an invalid one is skipped here (``plan_apply``
    and ``validate`` are what refuse it)."""
    servers: list[_mcp_tools.McpServerConfig] = []
    for path in _server_files(directory):
        try:
            servers.append(_mcp_tools.load_mcp_server_document(path))
        except _mcp_tools.McpServerDocError:
            continue
    return servers


def summarize_recipe(directory: Path) -> RecipeSummary:
    """Derive what *directory* brings: read-only, independent of any pod or role registry
    (unlike ``plan_apply``). Used by ``docket pod validate``, ``docket pod update``, and
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

    exporters_raw = manifest.get("exporters")
    exporters = (
        tuple(e for e in exporters_raw if isinstance(e, str))
        if isinstance(exporters_raw, list)
        else ()
    )

    servers = _declared_servers(directory)
    return RecipeSummary(
        mcp_servers=tuple(s.name for s in servers),
        pipelines=tuple(f.stem for f in _named_pipeline_files(directory)),
        roles=roles,
        policies=policies,
        plugins=plugins,
        skills=skills,
        members=members,
        settings=settings,
        pipeline=pipeline,
        description=description,
        exporters=exporters,
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
    lookup. Sorted by name; used by ``docket pod recipes``."""
    by_name: dict[str, RecipeInfo] = {}
    shipped_dir = _templates.RECIPES_DIR
    if shipped_dir.is_dir():
        for entry in sorted(shipped_dir.iterdir()):
            if entry.is_dir():
                by_name[entry.name] = RecipeInfo(
                    name=entry.name,
                    scope="shipped",
                    directory=entry,
                    summary=summarize_recipe(entry),
                )
    operator_dir = current_home().user_recipes_dir
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
    """Plan ``roles/*.yaml|yml|json`` into *project*'s own pod-scoped role overlay, the same target
    ``docket pod update --pod <project>`` writes to -- never the global overlay
    (see module docstring)."""
    items: list[ApplyItem] = []
    writes: list[_RoleWrite] = []
    merged = dict(base_registry.archetypes)
    roles_dir = directory / "roles"
    if not roles_dir.is_dir():
        return items, writes, merged
    from docket.teams import config_docs as _config_docs

    for role_file in sorted(_config_glob(roles_dir)):
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


def _named_pipeline_files(directory: Path) -> list[Path]:
    """``pipelines/*.yaml|yml`` directly under *directory*, sorted by name."""
    pipelines_dir = directory / "pipelines"
    if not pipelines_dir.is_dir():
        return []
    return sorted([*pipelines_dir.glob("*.yaml"), *pipelines_dir.glob("*.yml")])


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
        if not _steps.TASK_PIPELINE_NAME.match(pipeline_file.stem):
            raise PodApplyError(f"{rel}: {pipeline_file.stem!r} is not a pipeline name")
        if pipeline_file.stem in seen:
            raise PodApplyError(f"{rel}: two files name pipeline {pipeline_file.stem!r}")
        seen.add(pipeline_file.stem)
        source = pipeline_file.read_bytes()
        loaded = _pipeline.load_pipeline(source.decode("utf-8"))
        if loaded.spec is None:
            raise PodApplyError(f"{rel}: {'; '.join(loaded.errors)}")
        dest = dest_dir / pipeline_file.name
        if dest.is_file() and dest.read_bytes() == source:
            action: ApplyAction = "skip"
        else:
            action = "replace" if dest.is_file() else "add"
            writes.append(_NamedPipelineWrite(name=pipeline_file.name, source=source))
        items.append(ApplyItem(kind="pipeline", name=rel, action=action))
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


def _plan_mcp_servers(
    directory: Path, project: str
) -> tuple[list[ApplyItem], _McpServerWrite | None]:
    """Plan ``mcp-servers/*`` into *project*'s own pod-scoped server file. A name equal to a
    global server is refused (never shadowed); a server already stored identically plans
    ``skip``; servers the recipe does not name are kept."""
    items: list[ApplyItem] = []
    declared: dict[str, _mcp_tools.McpServerConfig] = {}
    for path in _server_files(directory):
        try:
            config = _mcp_tools.load_mcp_server_document(path)
        except _mcp_tools.McpServerDocError as exc:
            raise PodApplyError(str(exc)) from exc
        if config.name in declared:
            raise PodApplyError(f"{path}: MCP server {config.name!r} is declared twice")
        declared[config.name] = config
    if not declared:
        return items, None
    global_names = {s.name for s in _mcp_tools.load_mcp_servers()}
    for name in declared:
        if name in global_names:
            raise PodApplyError(
                f"mcp-servers: {name!r} collides with a global MCP server; "
                "rename it or remove the global one"
            )
    current = {s.name: s for s in _mcp_tools.load_pod_mcp_servers(project)}
    changed = False
    for name, config in declared.items():
        if name in current and current[name] == config:
            action: ApplyAction = "skip"
        else:
            action = "replace" if name in current else "add"
            changed = True
        items.append(ApplyItem(kind="mcp-server", name=name, action=action))
    if not changed:
        return items, None
    return items, _McpServerWrite(servers=tuple({**current, **declared}.values()))


def _plan_members(
    project: str,
    member_roles: list[str],
    registry: _arch.ArchetypeRegistry,
) -> tuple[list[ApplyItem], list[_MemberWrite], dict[str, str]]:
    items: list[ApplyItem] = []
    writes: list[_MemberWrite] = []
    roster = dict(_queue.pod_full_roster(project))

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
    project: str, raw_settings: dict[str, Any], mcp_extra: tuple[str, ...] = ()
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
            coerced = pod.PodSettings.coerce(key, str_value, project=project, mcp_extra=mcp_extra)
        except pod.PodSettingsError as exc:
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


def directory_digest(directory: Path) -> str:
    """Sha256 hex digest over the sorted relative paths and bytes of every file
    `discover_config_paths` returns, plus any `plugins/*.py` and any `skills/**` file
    (never the generated `.schemas/`); `apply` records it as `configDigest`."""
    from docket.teams import config_docs as _config_docs

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
        _steps.pod_pipeline(project)
    except _task.DispatchError as exc:
        raise PodApplyError(str(exc)) from exc

    from docket.teams import config_docs as _config_docs

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

    policy_items, policy_writes = _plan_policies(directory, project)

    plugin_items, plugin_writes = _plan_plugins(directory, project)

    named_items, named_writes = _plan_named_pipelines(directory, project)

    skill_items, skill_writes = _plan_skills(directory, project)

    member_items, member_writes, roster_after = _plan_members(project, member_roles, augmented)

    pipeline_item, pipeline_write = _plan_pipeline(
        directory, pipeline_name, project, roster_after, augmented
    )

    mcp_items, mcp_write = _plan_mcp_servers(directory, project)

    setting_items, setting_writes = _plan_settings(
        project, _settings_with_top_level(raw_settings, manifest), tuple(i.name for i in mcp_items)
    )

    items = [*role_items, *policy_items, *plugin_items, *skill_items, *mcp_items, *member_items]
    if pipeline_item is not None:
        items.append(pipeline_item)
    items.extend(named_items)
    items.extend(setting_items)

    return ApplyPlan(
        project=project,
        directory=directory,
        items=tuple(items),
        exporters=exporter_names,
        _role_writes=tuple(role_writes),
        _policy_writes=tuple(policy_writes),
        _plugin_writes=tuple(plugin_writes),
        _named_pipeline_writes=tuple(named_writes),
        _skill_writes=tuple(skill_writes),
        _mcp_server_write=mcp_write,
        _member_writes=tuple(member_writes),
        _pipeline_write=pipeline_write,
        _setting_writes=tuple(setting_writes),
    )


REPO_REFUSED_COMMANDS: tuple[str, ...] = ("sh", "bash", "zsh", "dash", "sudo", "ssh", "nc", "socat")


@dataclass(frozen=True)
class RunItem:
    """One thing a directory would run on this machine: its ``kind``, ``name`` and the
    exact ``runs`` text the operator is asked to allow."""

    kind: str
    name: str
    runs: str


@dataclass(frozen=True)
class PlanReview:
    """A directory split into ``adds`` (``kind name`` lines) and ``runs`` (RunItems), plus the
    shell-like ``allowCommands`` names ``REPO_REFUSED_COMMANDS`` refuses."""

    adds: tuple[tuple[str, str], ...]
    runs: tuple[RunItem, ...]
    refused: tuple[str, ...] = ()


def is_shipped_recipe(directory: Path) -> bool:
    """Whether *directory* is a recipe docket ships (exempt from the operator review)."""
    try:
        directory.resolve().relative_to(_templates.RECIPES_DIR.resolve())
    except ValueError:
        return False
    return True


@dataclass(frozen=True)
class ReviewDecision:
    """The review rule's verdict: ``go`` (nothing to ask), ``refused``, ``needs_code`` (no
    ``accept`` given), ``code_mismatch`` or ``accepted``. ``code`` is the current review code."""

    status: Literal["go", "refused", "needs_code", "code_mismatch", "accepted"]
    review: PlanReview
    code: str = ""


def review_decision(
    repo_root: Path, project: str, directory: Path, accept: str | None
) -> ReviewDecision:
    """Whether *directory*'s run-on-this-machine items are cleared by the shipped-recipe
    exemption, a set *project* remembered for *repo_root*, or the matching *accept* code.
    Read-only."""
    from docket.governance import review as _reviewed

    empty = PlanReview((), ())
    if is_shipped_recipe(directory):
        return ReviewDecision("go", empty)
    review = classify_directory(directory)
    if review.refused:
        return ReviewDecision("refused", review)
    if not review.runs or _reviewed.is_reviewed(repo_root, project, review.runs):
        return ReviewDecision("go", review)
    code = _reviewed.review_code(review.runs, repo_root)
    if accept is None:
        return ReviewDecision("needs_code", review, code)
    return ReviewDecision("accepted" if accept == code else "code_mismatch", review, code)


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
    from docket.governance import review as _reviewed

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


def _run_steps(steps: list[Any], prefix: str = "") -> list[RunItem]:
    found: list[RunItem] = []
    for step in steps:
        if step.run is not None:
            env = "".join(f" {k}={v}" for k, v in sorted((step.env or {}).items()))
            found.append(RunItem("pipeline-step", prefix + step.id, f"{step.run}{env}"))
        command = getattr(step.gate, "command", None)
        if command:
            kind = "gate" if step.gate.type == "external" else "verify"
            found.append(RunItem(kind, prefix + step.id, command))
        found.extend(_run_steps(step.parallel or [], prefix))
    return found


def _loosened_denials(directory: Path) -> list[RunItem]:
    found: list[RunItem] = []
    builtin = _arch.load_registry()
    roles_dir = directory / "roles"
    for role_file in sorted(_config_glob(roles_dir)) if roles_dir.is_dir() else []:
        doc = _config_docs_doc(role_file, "role")
        name = str(doc.get("name", "")).strip()
        base = builtin.get(name)
        if base is None:
            continue
        removed = sorted(set(base.denied_tools) - {str(t) for t in doc.get("deniedTools", [])})
        if removed:
            found.append(RunItem("role-loosens", name, "removes denial of " + ", ".join(removed)))
    return found


def _config_docs_doc(path: Path, kind: str) -> dict[str, Any]:
    from docket.teams import config_docs as _config_docs

    try:
        return dict(_config_docs.load_document(path, kind=kind).doc)
    except _config_docs.ConfigDocError:
        return {}


def _prepare_runs(directory: Path, manifest: dict[str, Any]) -> list[RunItem]:
    """The install command a task worktree runs: the directory's own ``prepare:``, else -- for a
    repository's ``.docket/`` -- the one derived from a lockfile at the repository root."""
    raw = manifest.get("prepare")
    if isinstance(raw, str):
        command = raw.strip()
    elif raw is None and _is_repo_config_dir(directory):
        found = _prepare.lockfile_in(repo_root(directory))
        command = found[1] if found else ""
    else:
        command = ""
    return [] if _prepare.is_off(command) else [RunItem("prepare", "prepare", command)]


def _is_repo_config_dir(directory: Path) -> bool:
    return directory.name == ".docket" or (
        directory.parent.name == "teams" and directory.parent.parent.name == ".docket"
    )


def classify_directory(directory: Path) -> PlanReview:
    """Read-only split of *directory* into adds and run-on-this-machine items; needs no pod."""
    manifest_file = directory / "pod.yaml"
    manifest = _config_docs_doc(manifest_file, "pod") if manifest_file.is_file() else {}
    settings = manifest.get("settings") or {}
    runs: list[RunItem] = []
    adds: list[tuple[str, str]] = []
    pipeline_file = directory / str(manifest.get("pipeline") or "pipeline.yaml")
    if pipeline_file.is_file():
        spec = _pipeline.load_pipeline(pipeline_file.read_text(encoding="utf-8")).spec
        runs.extend(_run_steps(spec.steps if spec is not None else []))
        adds.append(("pipeline", pipeline_file.name))
    for named in _named_pipeline_files(directory):
        spec = _pipeline.load_pipeline(named.read_text(encoding="utf-8")).spec
        runs.extend(_run_steps(spec.steps if spec is not None else [], f"{named.stem}/"))
        adds.append(("pipeline", f"pipelines/{named.name}"))
    for server in _declared_servers(directory):
        runs.append(RunItem("mcp-server", server.name, " ".join([server.command, *server.args])))
    plugins_dir = directory / "plugins"
    for plugin in sorted(plugins_dir.glob("*.py")) if plugins_dir.is_dir() else []:
        sha = hashlib.sha256(plugin.read_bytes()).hexdigest()[:12]
        runs.append(RunItem("plugin", plugin.name, f"{plugin.name} sha256:{sha}"))
    raw_allow = settings.get("allowCommands", [])
    allowed = raw_allow if isinstance(raw_allow, list) else str(raw_allow).split(",")
    names = sorted({str(n).strip() for n in allowed if str(n).strip()})
    if names:
        runs.append(RunItem("allow-commands", "allowCommands", ", ".join(names)))
    if str(settings.get("network", "")) == "open":
        runs.append(RunItem("network", "network", "open"))
    runs.extend(_prepare_runs(directory, manifest))
    runs.extend(_loosened_denials(directory))
    for sub, kind in (("roles", "role"), ("policies", "policy")):
        sub_dir = directory / sub
        if sub_dir.is_dir():
            adds.extend((kind, p.stem) for p in sorted(_config_glob(sub_dir)))
    skills_dir = directory / "skills"
    if skills_dir.is_dir():
        adds.extend(("skill", p.name) for p in sorted(skills_dir.iterdir()) if p.is_dir())
    adds.extend(("setting", k) for k in sorted(settings) if k not in ("allowCommands", "network"))
    if "prepare" in manifest:
        adds.append(("setting", "prepare"))
    if "protects" in manifest:
        adds.append(("setting", "protects"))
    refused = tuple(n for n in names if n in REPO_REFUSED_COMMANDS)
    return PlanReview(tuple(adds), tuple(runs), refused)


@dataclass(frozen=True)
class RunChange:
    """A run-on-this-machine item the repository changed: its new ``item`` and ``before`` text
    (None when the operator never allowed an item of that name)."""

    item: RunItem
    before: str | None


@dataclass(frozen=True)
class RepoChanges:
    """What a repository's ``.docket/`` changed since it was applied to a pod: the read-only
    ``plan``, its non-skip ``adds_changed`` lines, ``runs_changed`` and the ``review``."""

    plan: ApplyPlan
    adds_changed: tuple[str, ...]
    runs_changed: tuple[RunChange, ...]
    review: PlanReview
    allowed_on: str


def runs_changed(project: str, repo_dir: Path) -> tuple[RunChange, ...]:
    """The run-on-this-machine items of *repo_dir* that differ from the latest set *project*
    remembered for its repository (every item when none was remembered)."""
    from docket.governance import review as _reviewed

    found = _reviewed.lookup(repo_root(repo_dir), project)
    was = {(i.kind, i.name): i.runs for i in found.items} if found else {}
    return tuple(
        RunChange(i, was.get((i.kind, i.name)))
        for i in classify_directory(repo_dir).runs
        if was.get((i.kind, i.name)) != i.runs
    )


def repo_config_dir(codebase: Path, project: str, *, create: bool = False) -> Path:
    """The pod's configuration-of-record directory: ``.docket/teams/<project>`` when it exists
    (or, with *create*, when ``.docket/teams/`` exists), else ``.docket``; never docket's own
    state root, whose team path is returned instead."""
    base = codebase / ".docket"
    team = base / "teams" / project
    if _is_state_root(base):
        return team
    if team.is_dir() or (create and (base / "teams").is_dir()):
        return team
    return base


def _is_state_root(directory: Path) -> bool:
    try:
        return directory.resolve() == current_home().root.resolve()
    except OSError:
        return False


def repo_root(repo_dir: Path) -> Path:
    """The codebase a configuration-of-record directory belongs to."""
    if repo_dir.parent.name == "teams" and repo_dir.parent.parent.name == ".docket":
        return repo_dir.parents[2]
    return repo_dir.parent


def repo_changes(project: str, repo_dir: Path) -> RepoChanges | None:
    """Compare *repo_dir* with what was last applied to *project*; None when it is not the
    pod's recorded configuration of record or has not changed. Read-only."""
    from docket.governance import review as _reviewed

    lead = pod.member_id(project, "lead")
    source = _fleet.meta_get(lead, "configSource", "")
    recorded = _fleet.meta_get(lead, "configDigest", "")
    if not (repo_dir.is_dir() and recorded and source == str(repo_dir.resolve())):
        return None
    if directory_digest(repo_dir) == recorded:
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


def apply(plan: ApplyPlan, channel: str = "") -> ApplyResult:
    """Write every non-``skip`` item in *plan* (role -> policy -> plugin -> skill -> mcp-server -> member -> pipeline
    -> setting order). Audits ``pod.apply`` only on change; records ``configSource``/
    ``configDigest`` every time, all-``skip`` included (see below)."""
    lead_id = pod.member_id(plan.project, "lead")

    for role_write in plan._role_writes:
        _arch.add_user_archetype(role_write.doc, plan.project)

    if plan._policy_writes:
        policies_dir = current_home().pod_config_dir(plan.project) / "policies"
        policies_dir.mkdir(parents=True, exist_ok=True)
        with contextlib.suppress(OSError):
            current_home().pods_dir.chmod(0o700)
            policies_dir.parent.parent.chmod(0o700)  # PODS_DIR/<project>
            policies_dir.parent.chmod(0o700)  # pod_config_dir(project)
            policies_dir.chmod(0o700)
        for policy_write in plan._policy_writes:
            dest = policies_dir / policy_write.name
            dest.write_text(policy_write.text, encoding="utf-8")
            dest.chmod(0o600)

    if plan._plugin_writes:
        plugins_dir = current_home().pod_config_dir(plan.project) / "plugins"
        plugins_dir.mkdir(parents=True, exist_ok=True)
        with contextlib.suppress(OSError):
            current_home().pods_dir.chmod(0o700)
            plugins_dir.parent.parent.chmod(0o700)  # PODS_DIR/<project>
            plugins_dir.parent.chmod(0o700)  # pod_config_dir(project)
            plugins_dir.chmod(0o700)
        for plugin_write in plan._plugin_writes:
            dest = plugins_dir / plugin_write.name
            dest.write_bytes(plugin_write.source)
            dest.chmod(0o600)

    if plan._named_pipeline_writes:
        pipelines_dir = current_home().pod_config_dir(plan.project) / "pipelines"
        pipelines_dir.mkdir(parents=True, exist_ok=True)
        with contextlib.suppress(OSError):
            current_home().pods_dir.chmod(0o700)
            pipelines_dir.parent.parent.chmod(0o700)  # PODS_DIR/<project>
            pipelines_dir.parent.chmod(0o700)  # pod_config_dir(project)
            pipelines_dir.chmod(0o700)
        for named_write in plan._named_pipeline_writes:
            dest = pipelines_dir / named_write.name
            dest.write_bytes(named_write.source)
            dest.chmod(0o600)

    if plan._skill_writes:
        skills_dir = current_home().pod_config_dir(plan.project) / "skills"
        skills_dir.mkdir(parents=True, exist_ok=True)
        with contextlib.suppress(OSError):
            current_home().pods_dir.chmod(0o700)
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

    if plan._mcp_server_write is not None:
        _mcp_tools.write_pod_mcp_servers(plan.project, list(plan._mcp_server_write.servers))

    for member_write in plan._member_writes:
        ok, msg = _pp.provision_member(
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
            _sched.set_schedule(
                current_home().schedule_file, plan.project, str(setting_write.value)
            )
        _fleet.meta_set(lead_id, setting_write.key, setting_write.value)

    if plan.has_changes():
        summary = ";".join(f"{item.kind}:{item.name}:{item.action}" for item in plan.items)
        via = f" channel={channel}" if channel else ""
        audit_log("pod.apply", f"project={plan.project} dir={plan.directory} items={summary}{via}")

    # The configuration-of-record (ADR 0012 §2 rule 5): recorded after every plan
    # `plan_apply` validated, an all-`skip` plan included, so composing a second, identical
    # directory at another path still moves the record -- never by `docket pod set`
    # (see `pod.PodSettings.RECORDED_KEYS`). The audit entry above keeps its own,
    # narrower "only when something changed" rule.
    _fleet.meta_set(lead_id, "configSource", str(plan.directory.resolve()))
    _fleet.meta_set(lead_id, "configDigest", directory_digest(plan.directory))

    # Recorded the same way, every apply, `exporters` included -- never merged with what a
    # prior apply named: an empty list here clears a previous recipe's destinations, matching
    # `configSource`/`configDigest` always describing the *last* directory applied (ADR 0014
    # rule 7). Activates nothing: no write ever reaches `docket-exporters.json` from this path.
    _fleet.meta_set(lead_id, "exporters", ",".join(plan.exporters))

    return ApplyResult(project=plan.project, items=plan.items, exporters=plan.exporters)


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
    (``governance.policy.to_short_policy``, the inverse of ``normalize_policy``) -- never a file from
    the fleet-wide ``$POLICIES_DIR``."""
    src_dir = current_home().pod_config_dir(project) / "policies"
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
    src_dir = current_home().pod_config_dir(project) / "plugins"
    files = sorted(src_dir.glob("*.py")) if src_dir.is_dir() else []
    if not files:
        return
    dest_dir = directory / "plugins"
    dest_dir.mkdir(parents=True, exist_ok=True)
    for f in files:
        (dest_dir / f.name).write_bytes(f.read_bytes())


def _export_named_pipelines(project: str, directory: Path) -> None:
    """Copy *project*'s own ``config/pipelines/`` files byte-for-byte as ``pipelines/<name>``."""
    files = _named_pipeline_files(current_home().pod_config_dir(project))
    if not files:
        return
    dest_dir = directory / "pipelines"
    dest_dir.mkdir(parents=True, exist_ok=True)
    for f in files:
        (dest_dir / f.name).write_bytes(f.read_bytes())


def _export_skills(project: str, directory: Path) -> None:
    """Copy *project*'s own ``config/skills/`` byte-for-byte into ``skills/<name>/`` -- unlike
    a role or policy, a skill is not regenerated, since it carries its own files rather than a
    wire document this module knows how to re-render."""
    src_dir = current_home().pod_config_dir(project) / "skills"
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


def _export_mcp_servers(project: str, directory: Path) -> None:
    """Write *project*'s own pod-scoped servers as ``mcp-servers/<name>.yaml`` documents --
    never a global server."""
    servers = _mcp_tools.load_pod_mcp_servers(project)
    if not servers:
        return
    dest_dir = directory / "mcp-servers"
    dest_dir.mkdir(parents=True, exist_ok=True)
    for server in servers:
        _dump_yaml_file(dest_dir / f"{server.name}.yaml", _mcp_tools.mcp_server_document(server))


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
    """Write ``pod.yaml`` with ``members``, ``settings`` (every non-default ``PodSettings``
    key), and ``exporters`` (this pod's recorded destinations, ADR 0014 rule 7, when set) --
    never a ``pipeline`` key (see ``_export_pipeline``'s docstring)."""
    roster = _queue.pod_full_roster(project)
    members = [role for role, _mid in sorted(roster.items()) if role != "lead"]

    settings_doc = pod.PodSettings.load_for(project)
    settings_out: dict[str, Any] = {}
    for key in pod.PodSettings.KEYS:
        if key in ("pipeline", "prepare", "protects"):
            continue  # top-level, never a `settings` entry (see `_settings_with_top_level`)
        value, source = settings_doc.value_and_source(key, project)
        if source == "set" and value is not None:
            settings_out[key] = value

    manifest: dict[str, Any] = {"kind": "pod", "name": project, "members": members}
    if settings_out:
        manifest["settings"] = settings_out
    if settings_doc.exporters:
        manifest["exporters"] = list(settings_doc.exporters)
    if settings_doc.prepare:
        manifest["prepare"] = settings_doc.prepare
    if settings_doc.protects:
        manifest["protects"] = list(settings_doc.protects)
    pod_path = directory / "pod.yaml"
    _dump_yaml_file(pod_path, manifest, schema_header=_schema_header(directory, pod_path, "pod"))


def _export_schemas(directory: Path) -> None:
    """Copy the four published config-v1 JSON Schemas into ``<directory>/.schemas/`` so every
    exported YAML's `# yaml-language-server:` header resolves without reaching outside the
    export -- ``apply``/``discover_config_paths`` never look under ``.schemas/``."""
    src_dir = _templates.CONFIG_SCHEMAS_DIR
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
    _export_named_pipelines(project, directory)
    _export_skills(project, directory)
    _export_mcp_servers(project, directory)
    _export_pipeline(project, directory)
    _export_manifest(project, directory)
    _export_schemas(directory)
