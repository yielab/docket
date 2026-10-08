"""``docket pipeline`` — validate, plan, and run a docket-native pipeline.

Two subcommands:
  * ``validate <file>`` — pure structural validation of a pipeline YAML file
    (``core.pipeline.load_pipeline``); no project or pod involved.
  * ``plan <project> [--file <path>]`` — render the resolved step plan for
    *project*'s pod, from the real executor (``core.orchestrator.
    resolve_plan``/``render_plan``) — never a second, drift-prone
    pretty-printer. ``--file`` omitted resolves the pod's zero-migration
    default pipeline, identical to what ``docket run`` would execute.
"""

from __future__ import annotations

from pathlib import Path

from docket import ui
from docket.core import archetypes as _archetypes
from docket.core import config_docs as _config_docs
from docket.core import dispatch as _dispatch
from docket.core import models_policy as _models_policy
from docket.core import orchestrator as _orch
from docket.core import pipeline as _pipeline


def _flag(args: list[str], name: str) -> str | None:
    """Return the value after ``--name`` (or ``--name=value``), else None."""
    for i, a in enumerate(args):
        if a == name and i + 1 < len(args):
            return args[i + 1]
        if a.startswith(name + "="):
            return a.split("=", 1)[1]
    return None


def run_pipeline(sub: str | None, args: list[str]) -> int:
    """Dispatch ``docket pipeline <sub> ...``. Returns a process exit code."""
    sub = (sub or "").lower()
    if sub == "validate":
        return _validate(args)
    if sub == "plan":
        return _plan(args)
    ui.error(f"Unknown subcommand '{sub}'. Use: validate <file> | plan <project> [--file <path>].")
    return 1


def _load_spec_file(path_str: str) -> tuple[_pipeline.PipelineSpec | None, list[str]]:
    """Load and validate a pipeline file. Returns ``(spec, errors)``."""
    path = Path(path_str)
    if not path.is_file():
        return None, [f"file not found: {path_str}"]
    try:
        _config_docs.load_document(path, kind="pipeline")
    except _config_docs.ConfigDocError as exc:
        return None, [str(exc)]
    result = _pipeline.load_pipeline(path.read_text(encoding="utf-8"))
    return result.spec, result.errors


def _resolve_spec_arg(args: list[str]) -> tuple[_pipeline.PipelineSpec | None, list[str]]:
    """``--file <path>`` in *args*, loaded and validated; ``(None, [])`` if
    omitted (the caller resolves the pod's zero-migration default itself)."""
    file_path = _flag(args, "--file")
    if file_path is None:
        return None, []
    return _load_spec_file(file_path)


def _print_errors(title: str, errors: list[str]) -> None:
    ui.error(title)
    for e in errors:
        ui.console.print(f"  [red]✗[/red] {e}")


def _iter_all_steps(steps: list[_pipeline.Step]) -> list[_pipeline.Step]:
    """*steps* plus every child of a ``parallel`` group, flattened one level."""
    out: list[_pipeline.Step] = []
    for step in steps:
        if step.parallel:
            out.extend(step.parallel)
        else:
            out.append(step)
    return out


def _step_model_errors(spec: _pipeline.PipelineSpec) -> list[str]:
    """Every step whose own ``model`` names a provider absent from the catalog --
    the same "caught before dispatch" posture an unresolvable role/agent target gets.
    See pod-dispatch.spec.md "Per-hop execution" requirement 5."""
    errors: list[str] = []
    for step in _iter_all_steps(spec.steps):
        if not step.model:
            continue
        try:
            _models_policy.resolve_step_model(step.model)
        except ValueError as exc:
            errors.append(f"step {step.id!r}: {exc}")
    return errors


def _validate(args: list[str]) -> int:
    if not args:
        ui.error("Usage: docket pipeline validate <file>")
        return 1
    path_str = args[0]
    path = Path(path_str)
    if not path.is_file():
        ui.error(f"File not found: {path_str}")
        return 1
    result = _pipeline.load_pipeline(path.read_text(encoding="utf-8"))
    errors = list(result.errors)
    if result.spec is not None:
        errors.extend(_step_model_errors(result.spec))
    if errors:
        _print_errors(f"Pipeline '{path_str}' is invalid:", errors)
        return 1
    ui.success(f"Pipeline '{path_str}' is valid")
    return 0


def _plan(args: list[str]) -> int:
    if not args:
        ui.error("Usage: docket pipeline plan <project> [--file <path>]")
        return 1
    project = args[0]
    spec, errors = _resolve_spec_arg(args[1:])
    if errors:
        _print_errors("Pipeline file is invalid:", errors)
        return 1

    file_path = _flag(args[1:], "--file")
    try:
        _dispatch.pod_pipeline(project)  # validates the project has a pod/lead
        roster = _dispatch.pod_full_roster(project)
        effective = spec if spec is not None else _dispatch.effective_pipeline(project, None)
        source_label = (
            f"file '{file_path}'"
            if spec is not None
            else _dispatch.effective_pipeline_source(project)
        )
    except _dispatch.DispatchError as ex:
        ui.error(str(ex))
        return 1

    model_errors = _step_model_errors(effective)
    if model_errors:
        _print_errors("Pipeline file is invalid:", model_errors)
        return 1

    registry = _archetypes.load_registry()
    plan = _orch.resolve_plan(effective, roster, registry=registry)
    ui.header(f"Pipeline plan — {project}")
    ui.console.print(f"Source: {source_label}")
    ui.console.print()
    # render_plan's own `[step-id]` bracket style is plain text, not Rich
    # markup -- markup=False keeps a literal "[" from being parsed as a
    # (bogus) style tag and silently swallowed.
    ui.console.print(_orch.render_plan(plan), markup=False)
    ui.console.print()
    return 0
