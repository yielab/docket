"""Shared utility functions for read-only command implementations."""

from __future__ import annotations

from docket.agent.ports import UsageDay, UsageTotals
from docket.kernel.home import current_home
from docket.models import selection as _mp
from docket.teams import fleet as _fleet


def project_ids() -> list[str]:
    """Sorted list of project agent IDs (dirs containing .docket-meta.json)."""
    if not current_home().projects_dir.is_dir():
        return []
    return sorted(
        d.name
        for d in current_home().projects_dir.iterdir()
        if d.is_dir() and (d / current_home().meta_file).is_file()
    )


def last_activity(agent_id: str) -> str:
    """The date (YYYY-MM-DD) of *agent_id*'s most recently updated session, or '—'."""
    from docket.agent import driver as _dr

    stamps = [s.last_active for s in _dr.default_driver().list_sessions(agent_id) if s.last_active]
    return max(stamps)[:10] if stamps else "—"


def si_format(n: int) -> str:
    """Format a token count with SI suffix (e.g. 1_234_567 → '1.2M')."""
    f = float(n)
    for unit in ("", "K", "M", "G", "T"):
        if abs(f) < 1000.0:
            return str(int(f)) if unit == "" else f"{f:.1f}{unit}"
        f /= 1000.0
    return f"{f:.1f}P"


def aggregate_cost(agent_id: str) -> UsageTotals:
    """Return aggregated token/cost totals for *agent_id*.

    Session-JSONL parsing lives behind the RuntimeDriver port: this returns the driver's
    ``UsageTotals`` as reported. See agent/ports.py.

    Resolves ``agent.driver.default_driver()``
    (``DocketDriver``) -- load-bearing for ``hops/gates/pre_hop.py``'s own
    pod-budget gate (``pod_gating_cost`` calls this for every hop's member),
    which must see the same driver hops actually execute through or the
    budget cap silently stops tripping.
    """
    from docket.agent import driver as _dr

    return _dr.default_driver().usage(agent_id).totals


def estimate_cost_usd(model: str, totals: UsageTotals) -> float | None:
    """Token-based cost estimate for *model*, priced from the provider catalog
    (``models_policy.price_for``).

    Returns ``None`` when *model* has no pricing entry — callers must not
    silently treat unknown pricing as "$0". This exists **only** as a
    budget-gating/warning fallback, for when the active driver's recorded
    usage never populates ``cost_usd`` (``aggregate_cost``'s ``cost_usd``
    then stays 0.0 forever by design — see ``agent/ports.py``'s
    ``TurnResult.cost_usd`` docstring: converting a token count into a dollar
    figure is exactly the estimate-to-billing-claim conversion this codebase
    has a standing rule against). An estimate MUST NEVER be presented as, or
    summed into, recorded spend — `docket status` stays exactly the driver's
    own recorded figure (see cli/_cost.py and the no-unfalsifiable-cost-claims
    discipline in CLAUDE.md/cost-tracking.spec).
    """
    pricing = _mp.price_for(model)
    if pricing is None:
        return None
    in_rate, out_rate, cache_read_rate, cache_write_rate = pricing
    usd = (
        max(0, totals.input_tokens - totals.cache_read - totals.cache_write) / 1_000_000 * in_rate
        + totals.output_tokens / 1_000_000 * out_rate
        + totals.cache_read / 1_000_000 * cache_read_rate
        + totals.cache_write / 1_000_000 * cache_write_rate
    )
    return round(usd, 6)


def gating_cost(agent_id: str) -> tuple[float, bool]:
    """One agent's budget-gating figure: recorded cost if nonzero, else the
    ``estimate_cost_usd`` token-based fallback (mirrors ``pod_gating_cost`` per member).
    Returns ``(amount, estimated)`` -- an estimate MUST NEVER be presented as recorded spend."""
    totals = aggregate_cost(agent_id)
    if totals.cost_usd > 0.0:
        return totals.cost_usd, False
    if totals.input_tokens == 0 and totals.output_tokens == 0:
        return 0.0, False
    model = str(_fleet.meta_get(agent_id, "model", "") or "")
    est = estimate_cost_usd(model, totals)
    if est is None:
        return 0.0, False
    return est, True


def cost_history(agent_id: str) -> list[UsageDay]:
    """Return per-day token/cost records for *agent_id*.

    Delegates to the RuntimeDriver port's ``usage()`` (see ``aggregate_cost``'s
    docstring) instead of parsing session JSONL directly, resolving
    ``agent.driver.default_driver()``. Note ``DocketDriver``'s
    ``usage().by_day`` is always empty (see its docstring: a session's stored
    usage is one running total, not timestamped per turn), so this always
    returns ``[]`` against the production driver -- an honest gap: a daily
    cost breakdown is real, useful information this driver does not yet have
    a way to produce.
    """
    from docket.agent import driver as _dr

    return _dr.default_driver().usage(agent_id).by_day
