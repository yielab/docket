"""docket metrics — role/project success-rate, latency, cost, guardrail stats.

Ports lib/commands/metrics.sh. The Bash command shelled out to an embedded
python3 heredoc that computed metrics from JSONL traces; that logic is reproduced
here directly. `run_metrics(...)` returns the process exit code:

  0  metrics printed (or no sessions / no traces-dir handled per Bash)
  1  traces directory missing

The coordinator wraps the return value in typer.Exit(code).

Output uses raw ANSI escape codes via plain print() — exactly as the Bash
heredoc did — to preserve byte parity rather than routing through the Rich UI.
"""

from __future__ import annotations

import datetime
import glob
import json
import os
import statistics
from typing import Any

import docket.config as _cfg
from docket import ui

METRICS_WINDOW = int(os.environ.get("METRICS_WINDOW", "50"))


def _metrics_help() -> None:
    """Mirror _metrics_help() in metrics.sh."""
    ui.header("docket metrics")
    ui.console.print()
    ui.console.print("  docket metrics                    All agents, default window")
    ui.console.print("  docket metrics --role programmer  Filter by agent role")
    ui.console.print("  docket metrics --project myapp    Filter by project")
    ui.console.print("  docket metrics --window 20        Use last 20 terminal sessions")
    ui.console.print()
    ui.console.print(f"  Metrics computed from JSONL traces at {_cfg.TRACES_DIR}")
    ui.console.print("  Run 'docket trace ingest <project>' to populate traces first.")
    ui.console.print()


def _compute_and_print(traces_dir: str, role_filter: str, project_filter: str, window: int) -> None:
    """Port of the embedded python3 heredoc in metrics.sh (verbatim logic)."""
    # Collect all session_end records (terminal sessions), keyed by (project, session_id).
    terminal_sessions: list[dict[str, Any]] = []
    guardrail_trips: dict[str, int] = {}  # action -> count

    pattern = os.path.join(traces_dir, "**", "*.jsonl")
    for tf in sorted(glob.glob(pattern, recursive=True)):
        parts = tf.replace(traces_dir + "/", "").split("/")
        project = parts[0] if len(parts) > 1 else "unknown"
        if project_filter and project != project_filter:
            continue

        session_data: dict[str, Any] = {
            "project": project,
            "session_id": os.path.basename(tf).replace(".jsonl", ""),
            "role": None,
            "status": None,
            "cost_usd": 0.0,
            "duration_ms": None,
            "start_ts": None,
            "end_ts": None,
            "guardrail_trips": 0,
        }
        has_end = False
        try:
            with open(tf) as f:
                for raw_line in f:
                    line = raw_line.strip()
                    if not line:
                        continue
                    try:
                        r = json.loads(line)
                    except Exception:
                        continue
                    etype = r.get("event_type", "")
                    if etype == "session_start":
                        session_data["start_ts"] = r.get("ts")
                        session_data["role"] = r.get("agent_role") or session_data["role"]
                    elif etype == "session_end":
                        has_end = True
                        session_data["status"] = r.get("payload", {}).get("status", "success")
                        session_data["end_ts"] = r.get("ts")
                        session_data["role"] = r.get("agent_role") or session_data["role"]
                    elif etype == "cost_charged":
                        c = r.get("cost_usd") or 0
                        session_data["cost_usd"] += float(c)
                    elif etype in ("guardrail_block", "approval_requested"):
                        action = r.get("payload", {}).get("action", etype)
                        guardrail_trips[action] = guardrail_trips.get(action, 0) + 1
                        session_data["guardrail_trips"] += 1
                    if not session_data["role"]:
                        session_data["role"] = r.get("agent_role")
        except Exception:
            continue

        if not has_end:
            continue  # skip open sessions

        # Compute duration
        if session_data["start_ts"] and session_data["end_ts"]:
            try:
                s = datetime.datetime.strptime(session_data["start_ts"][:19], "%Y-%m-%dT%H:%M:%S")
                e = datetime.datetime.strptime(session_data["end_ts"][:19], "%Y-%m-%dT%H:%M:%S")
                session_data["duration_ms"] = int((e - s).total_seconds() * 1000)
            except Exception:
                pass

        terminal_sessions.append(session_data)

    # Filter by role
    if role_filter:
        terminal_sessions = [s for s in terminal_sessions if (s["role"] or "") == role_filter]

    # Rolling window (most recent N)
    terminal_sessions = terminal_sessions[-window:]

    if not terminal_sessions:
        print("No terminal sessions found (run: docket trace ingest <project>)")
        return

    # Compute metrics
    total = len(terminal_sessions)
    success = sum(1 for s in terminal_sessions if s["status"] == "success")
    failure = sum(1 for s in terminal_sessions if s["status"] == "failure")
    aborted = sum(1 for s in terminal_sessions if s["status"] == "aborted")
    s_rate = round(success / total * 100, 1) if total else 0

    durations = [s["duration_ms"] for s in terminal_sessions if s["duration_ms"] is not None]
    costs = [s["cost_usd"] for s in terminal_sessions]

    mean_dur = round(statistics.mean(durations)) if durations else None
    p95_dur = round(sorted(durations)[int(len(durations) * 0.95)]) if durations else None
    total_cost = round(sum(costs), 4)
    mean_cost = round(statistics.mean(costs), 4) if costs else 0

    bold = "\033[1m"
    reset = "\033[0m"
    green = "\033[32m"
    red = "\033[31m"
    yellow = "\033[33m"

    print(f"\n{bold}docket metrics{reset}  (window: {total} terminal sessions)")
    if role_filter:
        print(f"  Role:    {role_filter}")
    if project_filter:
        print(f"  Project: {project_filter}")
    print()
    col = green if s_rate >= 80 else (yellow if s_rate >= 60 else red)
    print(
        f"  Success rate   {col}{s_rate}%{reset}  "
        f"({success} success / {failure} failure / {aborted} aborted)"
    )
    if mean_dur is not None:
        print(f"  Duration       mean={mean_dur}ms  p95={p95_dur}ms")
    print(f"  Cost           total=${total_cost}  mean=${mean_cost}/session")
    if guardrail_trips:
        print("  Guardrail trips:")
        for act, cnt in sorted(guardrail_trips.items(), key=lambda x: -x[1]):
            print(f"    {act:<30} {cnt}")
    print()


def run_metrics(
    role: str = "",
    project: str = "",
    window: int | None = None,
    show_help: bool = False,
) -> int:
    """Compute and print metrics from JSONL traces.

    role/project: optional filters. window: rolling terminal-session count
    (defaults to METRICS_WINDOW). show_help: print usage and return 0.
    """
    if show_help:
        _metrics_help()
        return 0

    win = METRICS_WINDOW if window is None else window
    traces_dir = _cfg.TRACES_DIR

    if not traces_dir.is_dir():
        # fail() prints without exiting; info() is the cyan-arrow hint.
        ui.console.print(f"[red]✗[/red] No traces directory found at {traces_dir}")
        ui.info("Start tracing: docket trace ingest <project>")
        return 1

    _compute_and_print(str(traces_dir), role, project, win)
    return 0
