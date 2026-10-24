"""Shared utility functions for read-only command implementations."""

from __future__ import annotations

from docket.agent.ports import UsageTotals
from docket.teams import model_selection as _mp


def si_format(n: int) -> str:
    """Format a token count with SI suffix (e.g. 1_234_567 → '1.2M')."""
    f = float(n)
    for unit in ("", "K", "M", "G", "T"):
        if abs(f) < 1000.0:
            return str(int(f)) if unit == "" else f"{f:.1f}{unit}"
        f /= 1000.0
    return f"{f:.1f}P"


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
    own recorded figure (see interfaces/cli/commands/status.py and the no-unfalsifiable-cost-claims
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
