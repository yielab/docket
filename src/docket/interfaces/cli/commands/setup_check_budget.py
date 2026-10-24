from __future__ import annotations

from docket.hops.application.usage import aggregate_cost, gating_cost
from docket.interfaces.cli.render import ui
from docket.kernel.home import current_home
from docket.platform import read_json
from docket.tasks.application import queue as _queue
from docket.tasks.application.repository import TaskRepository
from docket.tasks.domain.state import Status
from docket.teams import agent_memory as _mem
from docket.teams import pod as _pod


def _batch_cost(agent_ids: list[str]) -> dict[str, tuple[str, float, int]]:
    """Return {agent_id: (budgetUsd_str, cost_float, turns_int)} for all agents, using
    recorded spend only -- see ``_batch_gating_cost`` for the budget-warning figure."""
    out: dict[str, tuple[str, float, int]] = {}
    for aid in agent_ids:
        raw = read_json(current_home().meta_path(aid))
        budget = str(raw.get("budgetUsd", "") or "")
        totals = aggregate_cost(aid)
        out[aid] = (budget, totals.cost_usd, totals.turns)
    return out


def _batch_gating_cost(agent_ids: list[str]) -> dict[str, tuple[str, float, bool]]:
    """Return {agent_id: (budgetUsd_str, gating_cost, estimated)} -- the recorded-or-estimated
    figure ``teams/utils.gating_cost`` computes, so ``_check_budget`` can fire even though the
    driver's recorded cost is always 0.0."""
    out: dict[str, tuple[str, float, bool]] = {}
    for aid in agent_ids:
        raw = read_json(current_home().meta_path(aid))
        budget = str(raw.get("budgetUsd", "") or "")
        cost_f, estimated = gating_cost(aid)
        out[aid] = (budget, cost_f, estimated)
    return out


def _fmt_num(s: str) -> str:
    """Render a numeric string the way Bash printed it ('10' not '10.0')."""
    try:
        f = float(s)
    except ValueError:
        return s
    return str(int(f)) if f == int(f) else str(f)


def _check_budget(ids: list[str], cost: dict[str, tuple[str, float, bool]]) -> int:
    """Per-agent budget cap usage. ``cost_f`` is ``_batch_gating_cost``'s gating figure
    (recorded spend, or a token-based estimate when recorded is 0.0), rendered with the
    same ``~$… (estimated — no cost recorded)`` label the dispatch gate uses."""
    if not ids:
        return 0
    ui.section("Budget check:")
    issues = 0
    for aid in ids:
        budget_s, cost_f, estimated = cost.get(aid, ("", 0.0, False))
        if not budget_s or budget_s == "0":
            ui.dim(f"  {aid}: no cap")
            continue
        budget_f = float(budget_s)
        pct = int((cost_f / budget_f) * 100) if budget_f else 0
        budget_disp = _fmt_num(budget_s)
        cost_disp = (
            f"~${cost_f:.6f} (estimated — no cost recorded)" if estimated else f"${cost_f:.6f}"
        )
        if pct >= 100:
            ui.console.print(
                f"[red]✗[/red]   {aid}: over budget — {pct}% of ${budget_disp} ({cost_disp} used)"
            )
            issues += 1
        elif pct >= 80:
            ui.warn(f"  {aid}: {pct}% of ${budget_disp} ({cost_disp} used)")
        else:
            ui.success(f"  {aid}: {cost_disp} / ${budget_disp} ({pct}%)")
    return issues


def _check_runaway(ids: list[str], cost: dict[str, tuple[str, float, int]]) -> int:
    """Per-agent runaway session detection (high turns or high cost)."""
    if not ids:
        return 0
    ui.section("Runaway session check:")
    issues = 0
    for aid in ids:
        _budget, cost_f, turns = cost.get(aid, ("", 0.0, 0))
        runaway = (
            turns > current_home().runaway_turns_threshold
            or cost_f >= current_home().runaway_cost_threshold
        )
        if runaway:
            ui.console.print(f"[red]✗[/red]   {aid}: runaway — {turns} turns, ${cost_f:.6f}")
            issues += 1
        else:
            ui.success(f"  {aid}: ok ({turns} turns, ${cost_f:.6f})")
    return issues


def _check_dispatch_ledger(do_fix: bool) -> int:
    """TASK_LIST.json (``status: "running"``) vs. the pod Lead's HEARTBEAT.md dispatch ledger —
    must agree.

    ``tasks/application/queue.py`` keeps the ledger synced mechanically; this check catches whatever slips
    through anyway (an old docket version, a hand-edited file, a crash mid-write). See
    specs/functional/pod-dispatch.spec.md, "Mechanical HEARTBEAT ledger". ``--fix`` re-syncs the
    ledger to exactly what TASK_LIST.json says now — always safe, since the ledger's dispatch
    region is entirely docket-owned and TASK_LIST.json is dispatch's own source of truth."""

    pods = _queue.dispatchable_pods()
    if not pods:
        return 0

    ui.section("Dispatch task ledger (TASK_LIST.json <-> HEARTBEAT.md):")
    issues = 0
    for project in pods:
        lead_id = _pod.member_id(project, "lead")
        ws = current_home().workspace_dir(lead_id)
        tasks = TaskRepository.for_pod(project).list()
        running_ids = {t.id for t in tasks if t.status == Status.running}
        ledger_ids = set(_mem.read_dispatch_task_ids(ws))
        missing = running_ids - ledger_ids
        stale = ledger_ids - running_ids
        if not missing and not stale:
            ui.success(f"  {project}: in sync ({len(running_ids)} running)")
            continue

        detail = []
        if missing:
            detail.append(f"missing from ledger: {', '.join(sorted(missing))}")
        if stale:
            detail.append(f"stale in ledger: {', '.join(sorted(stale))}")
        ui.console.print(f"[red]✗[/red]   {project}: " + "; ".join(detail))
        issues += 1
        if do_fix:
            _mem.sync_dispatch_tasks(ws, [t.model_dump(by_alias=True, mode="json") for t in tasks])
            ui.success(f"  {project}: ledger re-synced from TASK_LIST.json")
            issues -= 1
        else:
            ui.console.print("    Fix with: docket setup --fix")
    return issues
