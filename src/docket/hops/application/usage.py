from __future__ import annotations

from docket.agent.ports import UsageDay, UsageTotals
from docket.hops.application import driver as _dr
from docket.teams import fleet as _fleet
from docket.teams import pod as _pod
from docket.teams.utils import estimate_cost_usd


def last_activity(agent_id: str) -> str:
    """The date (YYYY-MM-DD) of *agent_id*'s most recently updated session, or '—'."""
    stamps = [s.last_active for s in _dr.default_driver().list_sessions(agent_id) if s.last_active]
    return max(stamps)[:10] if stamps else "—"


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
    return _dr.default_driver().usage(agent_id).totals


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
    return _dr.default_driver().usage(agent_id).by_day


def pod_recorded_cost(project: str) -> float:
    """Sum each pod member's recorded USD spend (always 0.0 today — see ``pod_gating_cost``)."""
    all_ids = [a.id for a in _fleet.list_agents()]
    total = 0.0
    for mid, _role, _idx in _pod.members_of(all_ids, project):
        total += float(aggregate_cost(mid).cost_usd)
    return round(total, 6)
