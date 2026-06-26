"""docket trace — view, follow, and export agent action traces.

``run_trace`` returns the process exit code; the coordinator wraps it in a Typer command.

  docket trace <session_id>            render one trace human-readable
  docket trace tail <project>          follow the most-recent session
  docket trace export <project>        raw JSONL passthrough  [--since DATE]
  docket trace ingest <project>        manually ingest daemon session logs
"""

from __future__ import annotations

import contextlib
import subprocess
import sys
from typing import Any

import docket.config as _cfg
from docket import ui
from docket.core import trace as _trace

_EVENT_COLOR: dict[str, str] = {
    "session_start": "green",
    "session_end": "green",
    "tool_call": "cyan",
    "tool_result": "cyan",
    "cost_charged": "yellow",
    "budget_warning": "yellow",
    "budget_exceeded": "red",
    "guardrail_check": "blue",
    "guardrail_block": "red",
    "approval_requested": "magenta",
    "approval_granted": "green",
    "approval_denied": "red",
    "drift_alert": "red",
    "error": "red",
}


def _help() -> None:
    ui.header("docket trace")
    ui.console.print()
    ui.console.print("  docket trace <session_id>              Render one trace human-readable")
    ui.console.print("  docket trace tail <project>            Follow the most-recent session")
    ui.console.print("  docket trace export <project>          Raw JSONL passthrough")
    ui.console.print("    [--since YYYY-MM-DD]                 Filter by date")
    ui.console.print("  docket trace ingest <project>          Manually ingest daemon session logs")
    ui.console.print()
    ui.console.print(f"  Traces live at: {_cfg.TRACES_DIR}/<project>/<session_id>.jsonl")
    ui.console.print()


def _render_event(r: dict[str, Any]) -> None:
    ts = str(r.get("ts", "?"))[:19]
    etype = str(r.get("event_type", "?"))
    role = str(r.get("agent_role", "") or "")
    payload = r.get("payload", {})
    cost = r.get("cost_usd")
    dur = r.get("duration_ms")

    color = _EVENT_COLOR.get(etype, "")

    summary_parts: list[str] = []
    if isinstance(payload, dict):
        for k in ("status", "action", "text", "task_id", "pct"):
            v = payload.get(k)
            if v is not None:
                summary_parts.append(f"{k}={v}")
    summary = "  " + "  ".join(summary_parts) if summary_parts else ""

    extras: list[str] = []
    if cost is not None:
        with contextlib.suppress(TypeError, ValueError):
            extras.append(f"${float(cost):.4f}")
    if dur is not None:
        extras.append(f"{dur}ms")
    extras_str = "  [" + "  ".join(extras) + "]" if extras else ""

    role_str = f"  ({role})" if role and role != "unknown" else ""
    head = f"{ts}  {etype:<25}"
    head_markup = f"[{color}]{head}[/{color}]" if color else head
    # Rich treats '[' as markup — escape the literal bracket in the extras block.
    extras_markup = extras_str.replace("[", r"\[")
    ui.console.print(f"  {head_markup}{role_str}{summary}{extras_markup}")


def _show(session_id: str) -> int:
    if not session_id:
        _help()
        return 0

    found = _trace.find_trace(session_id)
    if found is None:
        ui.error(f"No trace found for session: {session_id}")
        ui.info("Available sessions: docket trace export <project>")
        return 1

    ui.header(f"Trace: {session_id}")
    ui.console.print()
    for r in _trace.read_trace(found):
        _render_event(r)
    ui.console.print()
    return 0


def _tail(project: str) -> int:
    if not project:
        ui.error("Usage: docket trace tail <project>")
        return 1

    pdir = _trace.project_trace_dir(project)
    if not pdir.is_dir():
        _trace.trace_ingest(project)

    if not pdir.is_dir():
        ui.error(f"No traces for project: {project}")
        ui.info(f"Start tracing with: docket trace ingest {project}")
        return 1

    latest = _trace.latest_trace_file(project)
    if latest is None:
        ui.error(f"No trace files found for project: {project}")
        return 1

    ui.info(f"Following: {latest.name}  (Ctrl-C to stop)")
    ui.console.print()
    with contextlib.suppress(KeyboardInterrupt):
        subprocess.run(["tail", "-f", str(latest)], check=False)
    return 0


def _export(project: str, since: str = "") -> int:
    if not project:
        ui.error("Usage: docket trace export <project> [--since YYYY-MM-DD]")
        return 1

    pdir = _trace.project_trace_dir(project)
    if not pdir.is_dir():
        _trace.trace_ingest(project)

    if not pdir.is_dir():
        print("No trace directory found", file=sys.stderr)
        return 1

    for line in _trace.export_lines(project, since):
        print(line)
    return 0


def _ingest(project: str) -> int:
    if not project:
        ui.error("Usage: docket trace ingest <project>")
        return 1
    ui.info(f"Ingesting session logs for: {project}")
    _trace.trace_ingest(project)
    ui.success(f"Ingest complete → {_cfg.TRACES_DIR}/{project}/")
    return 0


def run_trace(
    sub: str | None = None,
    target: str | None = None,
    since: str | None = None,
) -> int:
    """Dispatch the trace subcommand.

    sub: subcommand or, when not one of tail/export/ingest, a session_id.
    target: project/session argument for the subcommand.
    since: --since YYYY-MM-DD filter (export only).
    """
    if sub is None or sub in ("", "-h", "--help"):
        _help()
        return 0
    if sub == "tail":
        return _tail(target or "")
    if sub == "export":
        return _export(target or "", since or "")
    if sub == "ingest":
        return _ingest(target or "")
    # Anything else is treated as a session_id.
    return _show(sub)
