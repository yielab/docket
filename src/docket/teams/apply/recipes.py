from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import docket.kernel.templates as _templates
from docket.kernel import mcp as _mcp
from docket.kernel.home import current_home
from docket.pipeline.domain import plan as _orch
from docket.pipeline.domain import spec as _pipeline
from docket.teams import config_docs as _config_docs
from docket.teams import mcp_servers as _mcp_servers
from docket.teams import pod
from docket.teams.apply.model import PodApplyError


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


def _declared_servers(directory: Path) -> list[_mcp.McpServerConfig]:
    """Each readable ``mcp-servers/*`` document; an invalid one is skipped here (``plan_apply``
    and ``validate`` are what refuse it)."""
    servers: list[_mcp.McpServerConfig] = []
    for path in _server_files(directory):
        try:
            servers.append(_mcp_servers.load_mcp_server_document(path))
        except _mcp_servers.McpServerDocError:
            continue
    return servers


def _named_pipeline_files(directory: Path) -> list[Path]:
    """``pipelines/*.yaml|yml`` directly under *directory*, sorted by name."""
    pipelines_dir = directory / "pipelines"
    if not pipelines_dir.is_dir():
        return []
    return sorted([*pipelines_dir.glob("*.yaml"), *pipelines_dir.glob("*.yml")])


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


def directory_digest(directory: Path) -> str:
    """Sha256 hex digest over the sorted relative paths and bytes of every file
    `discover_config_paths` returns, plus any `plugins/*.py` and any `skills/**` file
    (never the generated `.schemas/`); `apply` records it as `configDigest`."""

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
