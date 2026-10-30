from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import docket.kernel.templates as _templates
from docket.governance import review as _reviewed
from docket.governance.review import RunItem
from docket.kernel.home import current_home
from docket.pipeline.domain import spec as _pipeline
from docket.teams import config_docs as _config_docs
from docket.teams import pod_settings as _pod_settings
from docket.teams import records as _records
from docket.teams import roles as _arch
from docket.teams import services as _services
from docket.teams.apply.recipes import _config_glob, _declared_servers, _named_pipeline_files
from docket.teams.apply.routines import routine_files
from docket.teams.workspace import prepare as _prepare

# `allowCommands` and `network` are run items; `networkGrant` is never applied from a repository.
_NOT_ADDED_SETTINGS = ("allowCommands", "network", _pod_settings.NETWORK_GRANT_KEY)
REPO_REFUSED_COMMANDS: tuple[str, ...] = ("sh", "bash", "zsh", "dash", "sudo", "ssh", "nc", "socat")


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


def _run_steps(steps: list[Any], prefix: str = "") -> list[RunItem]:
    found: list[RunItem] = []
    for step in steps:
        if step.run is not None:
            env = "".join(f" {k}={v}" for k, v in sorted((step.env or {}).items()))
            found.append(RunItem("pipeline-step", prefix + step.id, f"{step.run}{env}"))
        if step.until is not None:
            found.append(RunItem("pipeline-step", prefix + step.id, step.until.run))
        command = getattr(step.gate, "command", None)
        if command:
            kind = "gate" if step.gate.type == "external" else "verify"
            found.append(RunItem(kind, prefix + step.id, command))
        found.extend(_run_steps(step.parallel or [], prefix))
    return found


def _config_docs_doc(path: Path, kind: str) -> dict[str, Any]:
    try:
        return dict(_config_docs.load_document(path, kind=kind).doc)
    except _config_docs.ConfigDocError:
        return {}


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


def _is_repo_config_dir(directory: Path) -> bool:
    return directory.name == ".docket" or (
        directory.parent.name == "teams" and directory.parent.parent.name == ".docket"
    )


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
    adds.extend(("routine", f"routines/{r.name}") for r in routine_files(directory))
    adds.extend(("service", f"services/{f.name}") for f in _services.service_files(directory))
    adds.extend(("records", f"records/{f.name}") for f in _records.records_files(directory))
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
    adds.extend(("setting", k) for k in sorted(settings) if k not in _NOT_ADDED_SETTINGS)
    if "prepare" in manifest:
        adds.append(("setting", "prepare"))
    if "protects" in manifest:
        adds.append(("setting", "protects"))
    refused = tuple(n for n in names if n in REPO_REFUSED_COMMANDS)
    return PlanReview(tuple(adds), tuple(runs), refused)


def review_decision(
    repo_root: Path, project: str, directory: Path, accept: str | None
) -> ReviewDecision:
    """Whether *directory*'s run-on-this-machine items are cleared by the shipped-recipe
    exemption, a set *project* remembered for *repo_root*, or the matching *accept* code.
    Read-only."""

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
class RunChange:
    """A run-on-this-machine item the repository changed: its new ``item`` and ``before`` text
    (None when the operator never allowed an item of that name)."""

    item: RunItem
    before: str | None


def runs_changed(project: str, repo_dir: Path) -> tuple[RunChange, ...]:
    """The run-on-this-machine items of *repo_dir* that differ from the latest set *project*
    remembered for its repository (every item when none was remembered)."""

    found = _reviewed.lookup(repo_root(repo_dir), project)
    was = {(i.kind, i.name): i.runs for i in found.items} if found else {}
    return tuple(
        RunChange(i, was.get((i.kind, i.name)))
        for i in classify_directory(repo_dir).runs
        if was.get((i.kind, i.name)) != i.runs
    )
