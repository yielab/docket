"""Project-level status views for the current directory or every pod."""

from __future__ import annotations

import json
import json as _json
import os
from collections import Counter
from pathlib import Path
from typing import Any

import typer

import docket.config as _cfg
from docket import ui
from docket.cli._target import TargetError, resolve_pod
from docket.core import dispatch as _dispatch
from docket.core import fleet as _fleet
from docket.core import pod as _pod
from docket.core.utils import aggregate_cost, last_activity, project_ids
from docket.edges import store


def _project_ids() -> list[str]:
    """Return registered pod ids once each, excluding flat legacy agents."""
    projects: set[str] = set()
    for agent in _fleet.list_agents():
        raw = store.read_json(_cfg.meta_path(agent.id))
        project = str(raw.get("pod", "")) or (_pod.pod_of(agent.id) or "")
        if project:
            projects.add(project)
    return sorted(projects)


def _project_summary(project: str) -> dict[str, Any]:
    registered = {agent.id for agent in _fleet.list_agents()}
    members = _pod.members_of(sorted(registered), project)
    member_rows: list[dict[str, str]] = []
    roots: list[str] = []
    degraded = False

    for member_id, role, _index in members:
        raw = store.read_json(_cfg.meta_path(member_id))
        root = str(raw.get("workDir") or raw.get("codebase") or "")
        if root:
            roots.append(root)
        workspace = _cfg.workspace_dir(member_id)
        healthy = workspace.is_dir() and (workspace / _cfg.META_FILE).is_file()
        degraded = degraded or not healthy
        member_rows.append(
            {"id": member_id, "role": role, "status": "ready" if healthy else "missing"}
        )

    tasks = _dispatch.read_tasks(project)
    counts = Counter(str(task.get("status", "pending")) for task in tasks)
    if degraded or not members:
        state = "degraded"
    elif counts["waiting_approval"]:
        state = "waiting"
    elif counts["running"]:
        state = "active"
    elif counts["failed"]:
        state = "attention"
    else:
        state = "ready"

    return {
        "id": project,
        "path": roots[0] if roots else "",
        "status": state,
        "memberCount": len(member_rows),
        "isolation": "project workspaces; dispatch history scoped by step",
        "members": member_rows,
        "tasks": {
            "pending": counts["pending"],
            "running": counts["running"],
            "waitingApproval": counts["waiting_approval"],
            "failed": counts["failed"],
            "completed": counts["completed"],
        },
    }


def _render_current(summary: dict[str, Any]) -> None:
    tasks = summary["tasks"]
    roles = ", ".join(member["role"] for member in summary["members"])
    ui.console.print(f"[bold]Project:[/bold] {summary['id']}")
    ui.console.print(f"[bold]Path:[/bold] {summary['path'] or '—'}")
    ui.console.print(f"[bold]Status:[/bold] {summary['status']}")
    ui.console.print(f"[bold]Members:[/bold] {summary['memberCount']} ({roles})")
    ui.console.print(f"[bold]Isolation:[/bold] {summary['isolation']}")
    ui.console.print(
        "[bold]Tasks:[/bold] "
        f"{tasks['pending']} pending · {tasks['running']} running · "
        f"{tasks['waitingApproval']} waiting approval · {tasks['failed']} failed"
    )


def _render_all(summaries: list[dict[str, Any]]) -> None:
    from rich.table import Table

    if not summaries:
        ui.warn("No initialized projects. Run 'docket init' inside a project directory.")
        return
    table = Table(title="Docket projects — global status")
    table.add_column("PROJECT", style="bold")
    table.add_column("STATUS")
    table.add_column("MEMBERS", justify="right")
    table.add_column("TASKS")
    table.add_column("PATH", style="dim")
    for summary in summaries:
        tasks = summary["tasks"]
        task_text = (
            f"{tasks['pending']} pending / {tasks['running']} running / "
            f"{tasks['waitingApproval']} waiting"
        )
        table.add_row(
            summary["id"],
            summary["status"],
            str(summary["memberCount"]),
            task_text,
            summary["path"] or "—",
        )
    ui.console.print(table)


def run_status(*, all_projects: bool, json_out: bool, directory: Path | None = None) -> int:
    """Render current-project status by default, or one row per pod globally."""
    summaries = [_project_summary(project) for project in _project_ids()]
    if all_projects:
        if json_out:
            print(json.dumps({"projects": summaries}, indent=2))
        else:
            _render_all(summaries)
        return 0

    try:
        project = resolve_pod(None, env=os.environ, cwd=directory or Path.cwd())
    except TargetError as exc:
        ui.error(str(exc))
        return 1

    summary = next((item for item in summaries if item["id"] == project), _project_summary(project))
    if json_out:
        print(json.dumps(summary, indent=2))
    else:
        _render_current(summary)
    return 0


def cmd_status(
    all_projects: bool = typer.Option(False, "--all", help="Show every project"),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON"),
) -> None:
    """Show current-project status, or every project with --all.

    The current-project view shows state without mixing in the global agent
    inventory or workstation health: configured path, readiness, pod roles,
    and task counts. `docket list` remains the detailed global agent
    inventory; `docket doctor` remains the global technical health check."""
    from docket.cli._status import run_status

    raise typer.Exit(run_status(all_projects=all_projects, json_out=json_out))


def cmd_cost(
    agent_id: str | None = typer.Argument(None),
    json_out: bool = typer.Option(False, "--json"),
    history: bool = typer.Option(False, "--history"),
    days: int = typer.Option(0, "--days"),
) -> None:
    """Token usage and cost breakdown, with per-agent budget caps and
    runaway-session detection.

    With no agent id, aggregates all agents; with one, shows its own
    breakdown. `--json` emits machine-readable output for either form.
    `--history` shows a per-day cost breakdown instead of the current
    totals; `--days N` (default 0 = no limit) restricts `--history` to the
    last N days.

    Token counts (input/output/cache read/cache write, turns) are real and
    measured -- reported by the model endpoint per call and accumulated by
    docket's own session storage. The dollar total is not: docket's own turn
    loop (DocketDriver) reports no billed spend at all, so `Total cost`
    always reads as "none recorded for these sessions" rather than a dollar
    figure -- a known, plainly-stated gap, not a bug, because converting a
    token count into a dollar figure is exactly the estimate-to-billing-claim
    conversion docket refuses to make inside this command. See
    `docket models` for a comparative, clearly-labelled estimate (never
    presented as billed spend), and the same estimate's use by the
    budget-auto-pause gate. docket does not print a projected "savings if
    you switched models" figure either -- that would compound one estimate
    on top of another. `--history`/`--days` currently return no rows against
    the production driver: per-day breakdowns aren't tracked by docket's own
    session store (a session's usage is one running total for its lifetime,
    not timestamped per turn) -- a documented, known limitation. The pricing
    table (`docket models`) is a manual snapshot, not a live feed, and is
    not surfaced inside this command. Useful for detecting runaway sessions
    by turn count; budget management works off the token-based estimate the
    pod-dispatch gate itself computes, not this command's dollar column."""
    from docket.cli._cost import run_cost

    raise typer.Exit(run_cost(agent_id, json_out=json_out, history=history, days=days))


def _last_activity_or_never(agent_id: str) -> str:
    """Like ``last_activity`` but returns ``"never"`` for no logs -- mirrors
    ``serve.py``'s ``_last_activity_or_never`` so ``docket snapshot`` and
    ``/status.json`` emit the same sentinel (cli-json-shapes.spec.md)."""
    val = last_activity(agent_id)
    return "never" if val == "—" else val


def cmd_snapshot(
    output: str | None = typer.Option(None, "--output", "-o", help="Write JSON to file"),
) -> None:
    """Export system state snapshot as JSON.

    Every project agent, its model, registration/binding
    status, last activity, and measured cost, plus the channel list. `-o`/
    `--output <path>` writes the JSON to a file instead of stdout.
    `costUsd`/`totalCostUsd` are 0.0 for the same reason `docket cost` shows
    no recorded spend today:
    this is a snapshot of measured-token agents, not of billed dollars.
    Useful for backups, dashboards, or feeding fleet state into another
    tool."""
    import datetime as _dt

    fleet_state = _fleet.load_fleet()
    channels = _fleet.channel_names(fleet_state)
    registered_ids = {a.id for a in _fleet.list_agents(fleet_state)}

    def _agent_bindings(aid: str) -> list[dict[str, Any]]:
        return [
            {"channel": b.channel, "peerId": b.peer_id}
            for b in fleet_state.bindings
            if b.agent_id == aid
        ]

    agents_out: list[dict[str, Any]] = []
    total_cost = 0.0

    for pid in project_ids():
        try:
            raw = store.read_json(_cfg.meta_path(pid))
        except Exception:
            raw = {}
        cost = aggregate_cost(pid).cost_usd
        total_cost += cost
        agents_out.append(
            {
                "id": pid,
                "name": str(raw.get("name", pid)),
                "kind": "project",
                "model": str(raw.get("model", _cfg.DEFAULT_MODEL)),
                "registered": pid in registered_ids,
                "bindings": _agent_bindings(pid),
                "lastActivity": _last_activity_or_never(pid),
                "costUsd": round(cost, 6),
            }
        )

    timestamp = _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    result = {
        "timestamp": timestamp,
        "channels": channels,
        "agents": agents_out,
        "totalCostUsd": round(total_cost, 6),
    }

    out = _json.dumps(result, indent=2)
    if output:
        Path(output).write_text(out + "\n", encoding="utf-8")
        ui.success(f"Snapshot written to {output}")
    else:
        print(out)


def cmd_metrics(
    role: str = typer.Option("", "--role", "-r", help="Restrict to one role"),
    project: str = typer.Option("", "--project", "-p", help="Restrict to one project"),
    window: int | None = typer.Option(None, "--window", "-w", help="Window in days"),
    escalation: bool = typer.Option(
        False, "--escalation", help="Show escalation metrics (task starts, questions, latency)"
    ),
) -> None:
    """Show session success-rate and drift metrics.

    Computes success rate, latency, cost, and guardrail trip counts from
    trace data. `-r`/`--role` filters to a specific agent role; `-p`/
    `--project` to a specific project; `-w`/`--window N` (default 50,
    METRICS_WINDOW env-overridable) sets the rolling window size in
    sessions. Output: success rate, duration (mean/p95), cost (total/mean),
    and guardrail trip counts.

    `--escalation` prints escalation metrics instead: task starts (dispatch claims),
    operator questions by kind and outcome, and decision latency."""
    from docket.cli._metrics import run_escalation_metrics, run_metrics

    if escalation:
        raise typer.Exit(run_escalation_metrics())
    raise typer.Exit(run_metrics(role=role, project=project, window=window))
