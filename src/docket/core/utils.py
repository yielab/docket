"""Shared utility functions for read-only command implementations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import docket.config as cfg
from docket.core import models_policy as _mp
from docket.edges import store

if TYPE_CHECKING:
    from docket.edges.adapters.system import RestartResult


def project_ids() -> list[str]:
    """Sorted list of project agent IDs (dirs containing .docket-meta.json)."""
    if not cfg.PROJECTS_DIR.is_dir():
        return []
    return sorted(
        d.name for d in cfg.PROJECTS_DIR.iterdir() if d.is_dir() and (d / cfg.META_FILE).is_file()
    )


def last_activity(agent_id: str) -> str:
    """Return the most recent memory-log date (YYYY-MM-DD) or '—'."""
    from docket.core import memory

    return memory.last_activity(cfg.workspace_dir(agent_id))


def gateway_active() -> bool:
    """Return True if a daemon gateway is active.

    Phase 19 P19-7b: there is no daemon gateway any more, so this always
    returns False -- see ``edges/adapters/system.py``'s ``gateway_active``,
    which this only forwards to.
    """
    from docket.edges.adapters import system as _system

    return _system.gateway_active()


def restart_gateway() -> RestartResult:
    """No daemon gateway exists any more -- nothing to restart.

    Honors DOCKET_NO_RESTART=1 for test hermeticity (moot now that both
    paths are no-ops). Thin pass-through to the edges adapter; returns a
    typed result (never prints — cli/ renders it via ui.*, since core has no
    knowledge of terminals).
    """
    from docket.edges.adapters import system as _system

    return _system.restart_gateway()


def si_format(n: int) -> str:
    """Format a token count with SI suffix (e.g. 1_234_567 → '1.2M')."""
    f = float(n)
    for unit in ("", "K", "M", "G", "T"):
        if abs(f) < 1000.0:
            return str(int(f)) if unit == "" else f"{f:.1f}{unit}"
        f /= 1000.0
    return f"{f:.1f}P"


@dataclass
class CostTotals:
    """Aggregated token/cost totals for one agent across all sessions."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read: int = 0
    cache_write: int = 0
    cost_usd: float = 0.0
    turns: int = 0


def aggregate_cost(agent_id: str) -> CostTotals:
    """Return aggregated token/cost totals for *agent_id*.

    Phase 18 L-1: the session-JSONL parsing this used to do directly now lives
    behind the RuntimeDriver port -- this is a pure translation from the
    driver's ``UsageTotals`` to the legacy ``CostTotals`` shape
    ``cli/_cost.py``, ``cli/_doctor.py``, and ``core/dispatch.py`` already
    depend on. See core/runtime_driver.py.

    Phase 19 P19-7a: resolves ``edges.adapters.docket_runtime.default_driver()``
    (``DocketDriver``), not the ACL's ``OpenClawDriver`` -- load-bearing for
    ``core/dispatch.py``'s own pod-budget gate (``pod_gating_cost`` calls this
    for every hop's member), which must see the same driver hops actually
    execute through or the budget cap silently stops tripping.
    """
    from docket.edges.adapters import docket_runtime as _dr

    t = _dr.default_driver().usage(agent_id).totals
    return CostTotals(
        input_tokens=t.input_tokens,
        output_tokens=t.output_tokens,
        cache_read=t.cache_read,
        cache_write=t.cache_write,
        cost_usd=t.cost_usd,
        turns=t.turns,
    )


def estimate_cost_usd(model: str, totals: CostTotals) -> float | None:
    """Token-based cost estimate for *model*, priced from ``MODEL_PRICING``.

    Returns ``None`` when *model* has no pricing entry — callers must not
    silently treat unknown pricing as "$0". This exists **only** for R-5's
    budget-gating/warning fallback, for when the daemon's own session JSONL
    never wrote a ``usage.cost.total`` (``aggregate_cost``'s ``cost_usd``
    then stays 0.0 forever — see ``core/runtime_driver.py``'s
    ``TurnResult.cost_usd`` note on daemon v2026.2.23). An estimate MUST
    NEVER be presented as, or summed into, recorded spend — `docket cost`
    stays exactly the daemon's own figure (see cli/_cost.py and the
    no-unfalsifiable-cost-claims discipline in CLAUDE.md/cost-tracking.spec).
    """
    pricing = _mp.MODEL_PRICING.get(model)
    if pricing is None:
        return None
    in_rate, out_rate, cache_read_rate, cache_write_rate = pricing
    usd = (
        totals.input_tokens / 1_000_000 * in_rate
        + totals.output_tokens / 1_000_000 * out_rate
        + totals.cache_read / 1_000_000 * cache_read_rate
        + totals.cache_write / 1_000_000 * cache_write_rate
    )
    return round(usd, 6)


@dataclass
class DayRecord:
    """Cost/token totals for a single calendar day."""

    date: str
    turns: int
    input_tokens: int
    output_tokens: int
    cost_usd: float


def cost_history(agent_id: str) -> list[DayRecord]:
    """Return per-day token/cost records for *agent_id*.

    Phase 18 L-1: delegates to the RuntimeDriver port's ``usage()`` (see
    ``aggregate_cost``'s docstring) instead of parsing session JSONL directly.

    Phase 19 P19-7a: same cutover as ``aggregate_cost`` -- resolves
    ``edges.adapters.docket_runtime.default_driver()``. Note ``DocketDriver``'s
    ``usage().by_day`` is always empty (see its docstring: a session's stored
    usage is one running total, not timestamped per turn), so this always
    returns ``[]`` against the production driver now -- an honest gap, not a
    regression this card papers over; see the report for what the daemon
    provided here that docket cannot yet.
    """
    from docket.edges.adapters import docket_runtime as _dr

    return [
        DayRecord(
            date=d.date,
            turns=d.turns,
            input_tokens=d.input_tokens,
            output_tokens=d.output_tokens,
            cost_usd=d.cost_usd,
        )
        for d in _dr.default_driver().usage(agent_id).by_day
    ]


def model_source(agent_id: str) -> str:
    """Return 'policy' or 'pinned' for an agent's model source.

    Reads modelSource from .docket-meta.json; defaults to 'policy' if absent.
    """
    raw = store.read_json(cfg.meta_path(agent_id))
    return str(raw.get("modelSource", "policy")) or "policy"
