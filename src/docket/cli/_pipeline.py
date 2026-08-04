"""``docket pipeline`` — validate, plan, and run a docket-native pipeline.

Four subcommands:
  * ``validate <file>`` — pure structural validation of a pipeline YAML file
    (``core.pipeline.validate_pipeline``); no project or pod involved.
  * ``plan <project> [--file <path>]`` — render the resolved step plan for
    *project*'s pod, from the real executor (``core.orchestrator.
    resolve_plan``/``render_plan``) — never a second, drift-prone
    pretty-printer. ``--file`` omitted resolves the pod's zero-migration
    default pipeline, identical to what ``run``/``docket pod <project>
    dispatch`` would actually execute.
  * ``run <project> [--file <path>] [--resume] [--timeout <seconds>] [--follow]`` —
    dispatch *project*'s pending tasks through the given (or default)
    pipeline. This delegates straight to ``cli._pod._pod_dispatch`` (the
    exact same rendering/run-registry logic ``docket pod <project>
    dispatch`` uses) with the loaded spec forwarded — one shared
    implementation, not a parallel copy. ``--follow``
    runs that same call on a background thread while tailing new trace
    events for *project* to stdout, so an operator watching the command sees
    hop-by-hop progress rather than only the final summary — see
    :func:`_run_and_follow`.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

import typer

from docket import ui
from docket.core import archetypes as _archetypes
from docket.core import dispatch as _dispatch
from docket.core import orchestrator as _orch
from docket.core import pipeline as _pipeline
from docket.core import trace as _trace

#: How often ``--follow`` polls the trace store for new lines while the
#: background dispatch is in flight. Cheap (a filesystem read of files
#: already written by the dispatch itself), so a sub-second poll is fine.
_FOLLOW_POLL_S = 0.5


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
    if sub == "run":
        return _run(args)
    ui.error(
        "Unknown subcommand "
        f"'{sub}'. Use: validate <file> | plan <project> [--file <path>] | "
        "run <project> [--file <path>] [--resume] [--timeout <seconds>] [--follow]."
    )
    return 1


def _load_spec_file(path_str: str) -> tuple[_pipeline.PipelineSpec | None, list[str]]:
    """Load and validate a pipeline file. Returns ``(spec, errors)``."""
    path = Path(path_str)
    if not path.is_file():
        return None, [f"file not found: {path_str}"]
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


def _validate(args: list[str]) -> int:
    if not args:
        ui.error("Usage: docket pipeline validate <file>")
        return 1
    path_str = args[0]
    path = Path(path_str)
    if not path.is_file():
        ui.error(f"File not found: {path_str}")
        return 1
    errors = _pipeline.validate_pipeline(path.read_text(encoding="utf-8"))
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

    try:
        _dispatch.pod_pipeline(project)  # validates the project has a pod/lead
        roster = _dispatch.pod_full_roster(project)
    except _dispatch.DispatchError as ex:
        ui.error(str(ex))
        return 1

    effective = spec if spec is not None else _dispatch.effective_pipeline(project, None)
    registry = _archetypes.load_registry()
    plan = _orch.resolve_plan(effective, roster, registry=registry)
    ui.header(f"Pipeline plan — {project}")
    ui.console.print()
    # render_plan's own `[step-id]` bracket style is plain text, not Rich
    # markup -- markup=False keeps a literal "[" from being parsed as a
    # (bogus) style tag and silently swallowed.
    ui.console.print(_orch.render_plan(plan), markup=False)
    ui.console.print()
    return 0


def _run(args: list[str]) -> int:
    if not args:
        ui.error(
            "Usage: docket pipeline run <project> [--file <path>] [--resume] "
            "[--timeout <seconds>] [--follow]"
        )
        return 1
    project = args[0]
    rest = args[1:]
    follow = "--follow" in rest
    rest = [a for a in rest if a != "--follow"]
    spec, errors = _resolve_spec_arg(rest)
    if errors:
        _print_errors("Pipeline file is invalid:", errors)
        return 1

    # `_pod_dispatch` renders results directly and raises `typer.Exit(1)` on
    # its own failure paths (the exact same call `docket pod <project>
    # dispatch` makes) — nothing further to do here on success.
    from docket.cli._pod import _pod_dispatch

    if follow:
        return _run_and_follow(project, rest, spec)
    _pod_dispatch(project, rest, spec=spec)
    return 0


def _utc_now_iso() -> str:
    """UTC timestamp matching ``core/trace.py``'s own record format exactly,
    so a plain string comparison against a trace line's ``ts`` field works."""
    import datetime as _dt

    return _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _run_and_follow(project: str, rest: list[str], spec: _pipeline.PipelineSpec | None) -> int:
    """``--follow``: run the dispatch on a background thread while the
    foreground thread tails new trace events for *project*
    to stdout, so an operator watching the command sees hop-by-hop progress
    instead of only the final summary once dispatch returns.

    Streams from ``core/trace.py`` — the same durable per-session JSONL store
    every hop already writes to synchronously as it completes (see
    ``core/dispatch.py``'s ``_trace.trace_event`` calls) — rather than a
    second, speculative progress channel of its own. ``_pod_dispatch`` itself
    is untouched: it still renders its own final summary and still raises
    ``typer.Exit`` on its own failure paths; this wrapper only adds a
    concurrent tail on top and converts that ``typer.Exit`` into a plain
    return code, since a background thread cannot propagate an exception back
    to its caller on its own. Ctrl-C stops *watching* — the dispatch itself
    keeps running (and recording) in the background, exactly like closing a
    log-tail window doesn't kill the process being tailed.
    """
    from docket.cli._pod import _pod_dispatch

    start_ts = _utc_now_iso()
    done = threading.Event()
    exit_code = [0]

    def _worker() -> None:
        try:
            _pod_dispatch(project, rest, spec=spec)
        except typer.Exit as exc:
            exit_code[0] = exc.exit_code or 0
        finally:
            done.set()

    ui.info(f"Following dispatch for '{project}' (Ctrl-C stops watching, not the dispatch)")
    ui.console.print()
    seen: set[str] = set()
    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    try:
        while not done.wait(_FOLLOW_POLL_S):
            _print_new_trace_lines(project, start_ts, seen)
        _print_new_trace_lines(project, start_ts, seen)  # catch any trailing events
    except KeyboardInterrupt:
        ui.console.print()
        ui.warn("Stopped watching — dispatch keeps running in the background.")
        return 0
    t.join()
    return exit_code[0]


def _print_new_trace_lines(project: str, since: str, seen: set[str]) -> None:
    """Render any trace line for *project* since *since* not already in *seen*."""
    for line in _trace.export_lines(project, since=since):
        if line in seen:
            continue
        seen.add(line)
        _render_trace_line(line)


def _render_trace_line(line: str) -> None:
    try:
        r: dict[str, Any] = json.loads(line)
    except json.JSONDecodeError:
        return
    ts = str(r.get("ts", "?"))[:19]
    etype = str(r.get("event_type", "?"))
    role = str(r.get("agent_role", "") or "")
    role_str = f"  ({role})" if role and role != "unknown" else ""
    # Plain text, not Rich markup -- a payload could legitimately contain a
    # literal '[' that markup=True would try (and fail) to parse as a tag.
    ui.console.print(f"  {ts}  {etype:<25}{role_str}", markup=False)
