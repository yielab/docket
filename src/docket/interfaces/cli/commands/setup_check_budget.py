from __future__ import annotations

from docket.hops.application.usage import aggregate_cost
from docket.interfaces.cli.render import ui
from docket.kernel.home import current_home
from docket.platform import read_json
from docket.tasks.application import queue as _queue
from docket.tasks.application.repository import TaskRepository
from docket.tasks.domain.state import Status
from docket.teams import agent_memory as _mem
from docket.teams import pod as _pod


def _batch_cost(agent_ids: list[str]) -> dict[str, tuple[str, float, int]]:
    """Return {agent_id: (budgetTokens_str, cost_float, turns_int)} for all agents, using
    recorded spend only (the runaway check's figures)."""
    out: dict[str, tuple[str, float, int]] = {}
    for aid in agent_ids:
        raw = read_json(current_home().meta_path(aid))
        budget = str(raw.get("budgetTokens", "") or "")
        totals = aggregate_cost(aid)
        out[aid] = (budget, totals.cost_usd, totals.turns)
    return out


def counted_tokens(agent_id: str) -> int:
    """*agent_id*'s counted tokens: input minus cache reads, plus output, the budget's measure."""
    totals = aggregate_cost(agent_id)
    return max(0, totals.input_tokens - totals.cache_read) + totals.output_tokens


def _batch_tokens(agent_ids: list[str]) -> dict[str, tuple[str, int]]:
    """Return {agent_id: (budgetTokens_str, counted_tokens)} -- the figures `_check_budget` and the
    JSON budget rows compare."""
    out: dict[str, tuple[str, int]] = {}
    for aid in agent_ids:
        raw = read_json(current_home().meta_path(aid))
        out[aid] = (str(raw.get("budgetTokens", "") or ""), counted_tokens(aid))
    return out


def _check_budget(ids: list[str], tokens: dict[str, tuple[str, int]]) -> int:
    """Per-agent budget cap usage: counted tokens against the agent's ``budgetTokens``."""
    if not ids:
        return 0
    ui.section("Budget check:")
    issues = 0
    for aid in ids:
        budget_s, used = tokens.get(aid, ("", 0))
        if not budget_s:
            ui.dim(f"  {aid}: no cap")
            continue
        budget = int(budget_s)
        pct = int(used / budget * 100)
        if pct >= 100:
            ui.console.print(
                f"[red]✗[/red]   {aid}: over budget — {pct}% of {budget} tokens ({used} counted)"
            )
            issues += 1
        elif pct >= 80:
            ui.warn(f"  {aid}: {pct}% of {budget} tokens ({used} counted)")
        else:
            ui.success(f"  {aid}: {used} / {budget} tokens ({pct}%)")
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
