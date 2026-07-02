"""docket cost — token usage and cost breakdown (+ --history).

``run_cost(...)`` returns the process exit code; the coordinator wraps it in
a Typer command and raises ``typer.Exit(code)``. Dollar figures are the
daemon's recorded spend from session data
(``~/.openclaw/agents/*/sessions/*.jsonl``); the bundled model-pricing table
only powers the comparative estimate shown alongside it.
"""

from __future__ import annotations

import json as _json
import os

import docket.config as _cfg
from docket import ui
from docket.core import models_policy as _mp
from docket.core.utils import (
    CostTotals,
    DayRecord,
    aggregate_cost,
    cost_history,
    model_source,
    project_ids,
    si_format,
)
from docket.edges import store


def run_cost(
    agent_id: str | None,
    *,
    json_out: bool,
    history: bool,
    days: int,
) -> int:
    """Dispatch `docket cost`. Returns the process exit code."""
    if history:
        return _cmd_cost_history(agent_id, days, json_out)
    if json_out:
        _cmd_cost_json()
        return 0
    if agent_id:
        return _cmd_cost_single(agent_id)
    _cmd_cost_all()
    return 0


def _cmd_cost_json() -> None:
    ids = project_ids()
    agents_out = []
    total = 0.0
    for pid in ids:
        raw = store.read_json(_cfg.meta_path(pid))
        model = str(raw.get("model", _cfg.DEFAULT_MODEL))
        budget_raw = raw.get("budgetUsd")
        totals: CostTotals = aggregate_cost(pid)
        cost = totals.cost_usd
        total += cost
        budget_val = float(budget_raw) if budget_raw and str(budget_raw) not in ("", "0") else None
        agents_out.append(
            {
                "id": pid,
                "model": model,
                "input": totals.input_tokens,
                "output": totals.output_tokens,
                "costUsd": round(cost, 6),
                "pricingKnown": True,
                "turns": totals.turns,
                "budgetUsd": budget_val,
            }
        )
    print(_json.dumps({"agents": agents_out, "totalUsd": round(total, 6)}, indent=2))


def _cmd_cost_single(agent_id: str) -> int:
    ws = _cfg.workspace_dir(agent_id)
    if not ws.is_dir():
        ui.error(f"Project '{agent_id}' not found.")
        return 1
    raw = store.read_json(_cfg.meta_path(agent_id))
    name = str(raw.get("name", agent_id))
    ui.header(f"Token Usage: {name} ({agent_id})")
    ui.console.print()
    _render_agent_cost(agent_id)
    ui.console.print()
    return 0


def _cmd_cost_all() -> None:
    ids = project_ids()
    if not ids:
        ui.warn("No project agents found.")
        return

    ui.header("Token Usage — All Project Agents")
    ui.console.print()

    hdr = (
        f"{'AGENT':<16} {'MODEL':<10} {'INPUT':>10} {'OUTPUT':>10}"
        f" {'COST (USD)':>12}  {'SOURCE':<8}  {'BUDGET':<12}"
    )
    ui.console.print(f"[bold]{hdr}[/bold]")
    ui.console.print("─" * 90)

    total_cost = 0.0
    runaway: list[str] = []

    for pid in ids:
        raw = store.read_json(_cfg.meta_path(pid))
        model = str(raw.get("model", _cfg.DEFAULT_MODEL))
        src = model_source(pid)
        budget_raw = raw.get("budgetUsd")
        totals = aggregate_cost(pid)

        model_short = model.split("/")[-1] if "/" in model else model
        cost_str = f"${totals.cost_usd:.4f}"

        budget_col = "—"
        if budget_raw and str(budget_raw) not in ("", "0"):
            bval = float(budget_raw)
            pct = int(totals.cost_usd / bval * 100) if bval > 0 else 0
            # Display the raw budget value (e.g. "10", "10.50") exactly as Bash
            # does — not a forced .2f — so "$10 (0%)" matches the contract.
            budget_col = f"${budget_raw} ({pct}%)"

        ui.console.print(
            f"{pid:<16} {model_short:<10} {si_format(totals.input_tokens):>10}"
            f" {si_format(totals.output_tokens):>10} {cost_str:>12}"
            f"  {src:<8}  {budget_col:<12}"
        )

        total_cost += totals.cost_usd

        runaway_turns = int(os.environ.get("RUNAWAY_TURNS_THRESHOLD", "200"))
        runaway_cost_t = float(os.environ.get("RUNAWAY_COST_THRESHOLD", "20"))
        if totals.turns > runaway_turns or totals.cost_usd >= runaway_cost_t:
            runaway.append(f"{pid} ({totals.turns} turns, ${totals.cost_usd:.4f})")

    ui.console.print()
    total_amount = f"${total_cost:.4f}"
    ui.console.print(f"[bold]{'Total:':>69} {total_amount:>12}[/bold]")

    if runaway:
        ui.console.print()
        for r in runaway:
            ui.warn(f"  Runaway session: {r}")

    ui.console.print()
    ui.dim("  Recorded spend from session data in ~/.openclaw/agents/*/sessions/*.jsonl")
    ui.dim(
        f"  Comparative estimates use a price snapshot (as of {_mp.MODEL_PRICING_AS_OF})"
        " — see: docket models"
    )
    ui.console.print()


def _render_agent_cost(agent_id: str) -> None:
    raw = store.read_json(_cfg.meta_path(agent_id))
    model = str(raw.get("model", _cfg.DEFAULT_MODEL))
    src = model_source(agent_id)
    budget_raw = raw.get("budgetUsd")
    totals = aggregate_cost(agent_id)

    ui.console.print(f"  [bold]{'Model:':<16}[/bold] {model}")
    ui.console.print(f"  [bold]{'Source:':<16}[/bold] {src}")
    ui.console.print(f"  [bold]{'Turns:':<16}[/bold] {totals.turns}")
    ui.console.print()
    ui.console.print(f"  [bold]{'Input:':<16}[/bold] {totals.input_tokens:,} tokens")
    ui.console.print(f"  [bold]{'Output:':<16}[/bold] {totals.output_tokens:,} tokens")
    ui.console.print(f"  [bold]{'Cache read:':<16}[/bold] {totals.cache_read:,} tokens")
    ui.console.print(f"  [bold]{'Cache write:':<16}[/bold] {totals.cache_write:,} tokens")
    ui.console.print()

    if totals.cost_usd > 0:
        ui.console.print(
            f"  [bold]{'Total cost:':<16}[/bold] [green]${totals.cost_usd:.4f}[/green]"
            " [dim](recorded)[/dim]"
        )
    else:
        ui.console.print(
            f"  [bold]{'Total cost:':<16}[/bold] "
            "[dim]none recorded by the daemon for these sessions[/dim]"
        )

    if budget_raw and str(budget_raw) not in ("", "0"):
        bval = float(budget_raw)
        pct = int(totals.cost_usd / bval * 100) if bval > 0 else 0
        color = "green"
        if pct >= 80:
            color = "yellow"
        if pct >= 100:
            color = "red"
        ui.console.print(
            f"  [bold]{'Budget:':<16}[/bold] [{color}]{pct}%[/{color}] of ${bval:.2f} cap"
        )

    runaway_turns = int(os.environ.get("RUNAWAY_TURNS_THRESHOLD", "200"))
    runaway_cost_t = float(os.environ.get("RUNAWAY_COST_THRESHOLD", "20"))
    if totals.turns > runaway_turns:
        ui.console.print()
        ui.warn(f"  High turn count: {totals.turns} turns (threshold: {runaway_turns})")
    if totals.cost_usd >= runaway_cost_t:
        ui.console.print()
        ui.warn(
            f"  High cost session: ${totals.cost_usd:.4f} exceeds ${runaway_cost_t:.0f} threshold"
        )


def _cmd_cost_history(
    agent_id: str | None,
    days: int,
    json_out: bool,
) -> int:
    if agent_id:
        ws = _cfg.workspace_dir(agent_id)
        if not ws.is_dir():
            ui.error(f"Project '{agent_id}' not found.")
            return 1
        agent_list = [agent_id]
    else:
        agent_list = project_ids()

    agg: dict[str, DayRecord] = {}
    for aid in agent_list:
        for rec in cost_history(aid):
            if rec.date in agg:
                ex = agg[rec.date]
                agg[rec.date] = DayRecord(
                    date=rec.date,
                    turns=ex.turns + rec.turns,
                    input_tokens=ex.input_tokens + rec.input_tokens,
                    output_tokens=ex.output_tokens + rec.output_tokens,
                    cost_usd=round(ex.cost_usd + rec.cost_usd, 6),
                )
            else:
                agg[rec.date] = rec

    ordered = sorted(agg.values(), key=lambda r: r.date)
    if days > 0:
        ordered = ordered[-days:]

    scope = agent_id or "all agents"

    if json_out:
        rows = [
            {
                "date": r.date,
                "turns": r.turns,
                "input": r.input_tokens,
                "output": r.output_tokens,
                "costUsd": r.cost_usd,
            }
            for r in ordered
        ]
        print(_json.dumps({"scope": scope, "history": rows}, indent=2))
        return 0

    ui.header(f"Cost history — {scope}")
    ui.console.print()

    if not ordered:
        ui.console.print("  (no dated session data yet)")
        ui.console.print()
        return 0

    ui.console.print(f"  {'DATE':<12} {'TURNS':>7} {'INPUT':>12} {'OUTPUT':>12} {'COST (USD)':>12}")
    costs = [r.cost_usd for r in ordered]
    for i, r in enumerate(ordered):
        flag = ""
        if i >= 3:
            avg = sum(costs[i - 3 : i]) / 3
            if avg > 0 and r.cost_usd > 2 * avg:
                flag = "  <- spike (>2x trailing avg)"
        ui.console.print(
            f"  {r.date:<12} {r.turns:>7} {r.input_tokens:>12}"
            f" {r.output_tokens:>12} {r.cost_usd:>12.4f}{flag}"
        )
    ui.console.print(f"  {'':12} {'':>7} {'':>12} {'':>12} {sum(costs):>12.4f}  total")
    ui.console.print()
    return 0
