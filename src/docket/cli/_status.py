"""The status command: where a pod stands, or every pod with --all."""

from __future__ import annotations

import datetime as _dt
import os
from collections import Counter
from pathlib import Path
from typing import Any

import typer

import docket.config as _cfg
from docket import ui
from docket.cli import _contract
from docket.cli._setup_sandbox import _off_label, sandbox_state
from docket.cli._target import TargetError, pod_option, resolve_pod
from docket.core import dispatch as _dispatch
from docket.core import fleet as _fleet
from docket.core import pod as _pod
from docket.core import runs as _runs
from docket.core import trace as _trace
from docket.core.utils import (
    DayRecord,
    aggregate_cost,
    cost_history,
    gating_cost,
    last_activity,
    project_ids,
    si_format,
)
from docket.edges import store


def pod_ids() -> list[str]:
    """Return registered pod ids once each, excluding flat legacy agents."""
    projects: set[str] = set()
    for agent in _fleet.list_agents():
        raw = store.read_json(_cfg.meta_path(agent.id))
        project = str(raw.get("pod", "")) or (_pod.pod_of(agent.id) or "")
        if project:
            projects.add(project)
    return sorted(projects)


def _last_activity_or_never(agent_id: str) -> str:
    """``last_activity`` with the ``never`` sentinel the HTTP status route also emits."""
    val = last_activity(agent_id)
    return "never" if val == "—" else val


def _start_running() -> bool:
    """True when ``docket start`` is running (the service's own pid-file check)."""
    from docket.cli import _service

    return _service.is_running()


def _approved_ready(task: dict[str, Any]) -> bool:
    """A pending task whose approval was granted and now only waits for ``docket run``."""
    return task.get("status") == "pending" and bool(
        task.get("pregrants") or task.get("gateOverridePipelineIndex") is not None
    )


def _isolation_phrase() -> str:
    """The sandbox posture in one phrase, from the reader `setup sandbox status` uses."""
    state = sandbox_state()
    backend, network = str(state["backend"]), state["network"]
    if state["isolation"] == "on":
        return f"on ({backend}, network {network})"
    found = "no backend found" if backend == "none" else f"{backend} found"
    return f"{_off_label(str(state['isolation']))}; {found}, network {network}"


def _usage(member_ids: list[str]) -> dict[str, Any]:
    tokens_in = tokens_out = 0
    estimate = 0.0
    for mid in member_ids:
        totals = aggregate_cost(mid)
        tokens_in += totals.input_tokens
        tokens_out += totals.output_tokens
        amount, _estimated = gating_cost(mid)
        estimate += amount
    return {"input": tokens_in, "output": tokens_out, "estimateUsd": round(estimate, 6)}


def _last_run(project: str) -> dict[str, Any] | None:
    runs = _runs.list_runs(project)
    if not runs:
        return None
    run = runs[0]
    return {
        "id": str(run.get("id", "")),
        "state": str(run.get("state", "")),
        "finishedAt": run.get("finishedAt"),
    }


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
    elif counts["waiting_approval"] or counts["waiting_input"]:
        state = "waiting"
    elif counts["running"]:
        state = "active"
    elif counts["failed"]:
        state = "attention"
    else:
        state = "ready"

    outcomes = _trace.terminal_outcomes(project, window=_cfg.METRICS_WINDOW)
    return {
        "id": project,
        "path": roots[0] if roots else "",
        "status": state,
        "memberCount": len(member_rows),
        "isolation": _isolation_phrase(),
        "members": member_rows,
        "tasks": {
            "pending": counts["pending"],
            "running": counts["running"],
            "waitingApproval": counts["waiting_approval"],
            "waitingInput": counts["waiting_input"],
            "failed": counts["failed"],
            "completed": counts["completed"] + counts["done"],
            "approvedReady": sum(1 for task in tasks if _approved_ready(task)),
        },
        "usage": _usage([m["id"] for m in member_rows]),
        "outcomes": {
            "success": outcomes.success,
            "failure": outcomes.failure,
            "aborted": outcomes.aborted,
            "meanMs": outcomes.mean_ms,
            "p95Ms": outcomes.p95_ms,
        },
        "lastRun": _last_run(project),
    }


def _inventory() -> dict[str, Any]:
    """The fleet inventory ``status --all --json`` adds beside the per-pod rows."""
    fleet_state = _fleet.load_fleet()
    registered = {a.id for a in _fleet.list_agents(fleet_state)}
    agents: list[dict[str, Any]] = []
    total = 0.0
    for pid in project_ids():
        raw = store.read_json(_cfg.meta_path(pid))
        cost = aggregate_cost(pid).cost_usd
        total += cost
        agents.append(
            {
                "id": pid,
                "name": str(raw.get("name", pid)),
                "kind": "project",
                "model": str(raw.get("model", _cfg.DEFAULT_MODEL)),
                "registered": pid in registered,
                "bindings": [
                    {"channel": b.channel, "peerId": b.peer_id}
                    for b in fleet_state.bindings
                    if b.agent_id == pid
                ],
                "lastActivity": _last_activity_or_never(pid),
                "costUsd": round(cost, 6),
            }
        )
    return {
        "timestamp": _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "channels": _fleet.channel_names(fleet_state),
        "agents": agents,
        "totalCostUsd": round(total, 6),
    }


def cost_snapshot() -> dict[str, Any]:
    """Per-agent recorded cost and the fleet total, as a bare dict."""
    rows = []
    total = 0.0
    for pid in project_ids():
        raw = store.read_json(_cfg.meta_path(pid))
        totals = aggregate_cost(pid)
        budget = raw.get("budgetUsd")
        total += totals.cost_usd
        rows.append(
            {
                "id": pid,
                "model": str(raw.get("model", _cfg.DEFAULT_MODEL)),
                "input": totals.input_tokens,
                "output": totals.output_tokens,
                "costUsd": round(totals.cost_usd, 6),
                "pricingKnown": True,
                "turns": totals.turns,
                "budgetUsd": float(budget) if budget and str(budget) not in ("", "0") else None,
            }
        )
    return {"agents": rows, "totalUsd": round(total, 6)}


def _seconds(ms: int | None) -> str:
    return "—" if ms is None else f"{ms / 1000:.1f}s"


def _render_current(summary: dict[str, Any]) -> None:
    tasks = summary["tasks"]
    usage = summary["usage"]
    out = summary["outcomes"]
    roles = ", ".join(member["role"] for member in summary["members"])
    run = summary["lastRun"]
    tokens = (
        f"{si_format(usage['input'])} in / {si_format(usage['output'])} out "
        f"(~${usage['estimateUsd']:.2f} est.)"
        if usage["input"] or usage["output"]
        else "none yet"
    )
    rows = [
        ("Path", summary["path"] or "—"),
        ("Status", summary["status"]),
        ("Members", f"{summary['memberCount']} ({roles})"),
        ("Isolation", summary["isolation"]),
        (
            "Tasks",
            f"{tasks['pending']} pending · {tasks['running']} running · "
            f"{tasks['waitingApproval']} waiting approval · {tasks['waitingInput']} waiting input"
            f" · {tasks['failed']} failed",
        ),
        ("Approved, ready", str(tasks["approvedReady"])),
        ("Tokens", tokens),
        (
            "Done / failed / aborted",
            f"{out['success']} / {out['failure']} / {out['aborted']}"
            f" · latency mean {_seconds(out['meanMs'])}, p95 {_seconds(out['p95Ms'])}",
        ),
        ("Last run", f"{run['id']} {run['state']}" if run else "none"),
        ("docket start", "running" if summary["running"] else "not running"),
    ]
    ui.header("Pod", summary["id"])
    ui.console.print()
    for label, value in rows:
        ui.console.print(f"  {label + ':':<26}{value}", markup=False)


def _render_all(summaries: list[dict[str, Any]]) -> None:
    if not summaries:
        ui.warn("No initialized projects. Run docket init inside a project directory.")
        return
    rows = []
    for s in summaries:
        t = s["tasks"]
        rows.append(
            [
                s["id"],
                s["status"],
                str(s["memberCount"]),
                f"{t['pending']} pending / {t['running']} running / "
                f"{t['waitingApproval'] + t['waitingInput']} waiting / {t['failed']} failed",
                s["path"] or "—",
            ]
        )
    ui.table(rows, ["POD", "STATUS", "MEMBERS", "TASKS", "PATH"])


def _history(pods: list[str], days: int, json_out: bool) -> None:
    merged: dict[str, DayRecord] = {}
    registered = [a.id for a in _fleet.list_agents()]
    for pod_id in pods:
        for member_id, _role, _idx in _pod.members_of(registered, pod_id):
            for rec in cost_history(member_id):
                old = merged.get(rec.date)
                merged[rec.date] = (
                    rec
                    if old is None
                    else DayRecord(
                        date=rec.date,
                        turns=old.turns + rec.turns,
                        input_tokens=old.input_tokens + rec.input_tokens,
                        output_tokens=old.output_tokens + rec.output_tokens,
                        cost_usd=round(old.cost_usd + rec.cost_usd, 6),
                    )
                )
    ordered = sorted(merged.values(), key=lambda r: r.date)
    if days > 0:
        ordered = ordered[-days:]
    if json_out:
        _contract.emit_json(
            {
                "history": [
                    {
                        "date": r.date,
                        "turns": r.turns,
                        "input": r.input_tokens,
                        "output": r.output_tokens,
                        "costUsd": r.cost_usd,
                    }
                    for r in ordered
                ]
            }
        )
        return
    if not ordered:
        ui.dim("No dated session data yet")
        return
    ui.table(
        [
            [r.date, str(r.turns), si_format(r.input_tokens), si_format(r.output_tokens)]
            for r in ordered
        ],
        ["DATE", "TURNS", "INPUT", "OUTPUT"],
    )


def cmd_status(
    all_projects: bool = typer.Option(False, "--all", help="Show every pod"),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON"),
    history: bool = typer.Option(False, "--history", help="Show tokens per day"),
    days: int = typer.Option(0, "--days", min=0, help="With --history, only the last N days"),
    pod: str | None = pod_option(),
) -> None:
    """Show where a pod stands: tasks, tokens, outcomes and the last run; every pod with --all.

    Tokens are measured; the dollar figure is a labelled estimate, never billed spend.
    --all --json also carries the fleet inventory (agents, channels, total cost).

    Example: docket status --all
    """
    pods = pod_ids()
    if all_projects:
        if history:
            _history(pods, days, json_out)
            return
        summaries = [dict(_project_summary(p), running=_start_running()) for p in pods]
        if json_out:
            _contract.emit_json({"projects": summaries, **_inventory()})
        else:
            _render_all(summaries)
        return
    try:
        project = resolve_pod(pod, env=os.environ, cwd=Path.cwd())
    except TargetError as exc:
        ui.error(str(exc))
        raise typer.Exit(1) from exc
    if history:
        _history([project], days, json_out)
        return
    summary = dict(_project_summary(project), running=_start_running())
    if json_out:
        _contract.emit_json(summary)
    else:
        _render_current(summary)
