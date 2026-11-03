from __future__ import annotations

from docket.agent.ports import UsageDay, UsageTotals
from docket.hops.application import driver as _dr
from docket.teams import fleet as _fleet
from docket.teams import pod as _pod


def last_activity(agent_id: str) -> str:
    """The date (YYYY-MM-DD) of *agent_id*'s most recently updated session, or '—'."""
    stamps = [s.last_active for s in _dr.default_driver().list_sessions(agent_id) if s.last_active]
    return max(stamps)[:10] if stamps else "—"


def aggregate_usage(agent_id: str) -> UsageTotals:
    """Return aggregated token totals for *agent_id*.

    Session-JSONL parsing lives behind the RuntimeDriver port: this returns the driver's
    ``UsageTotals`` as reported. See agent/ports.py.

    Resolves ``agent.driver.default_driver()``
    (``DocketDriver``) -- load-bearing for ``hops/gates/pre_hop.py``'s own
    pod-budget gate (``pod_counted_tokens`` calls this for every hop's member),
    which must see the same driver hops actually execute through or the
    budget cap silently stops tripping.
    """
    return _dr.default_driver().usage(agent_id).totals


def usage_history(agent_id: str) -> list[UsageDay]:
    """Return per-day token records for *agent_id*.

    Delegates to the RuntimeDriver port's ``usage()`` (see ``aggregate_usage``'s
    docstring) instead of parsing session JSONL directly, resolving
    ``agent.driver.default_driver()``. Note ``DocketDriver``'s
    ``usage().by_day`` is always empty (see its docstring: a session's stored
    usage is one running total, not timestamped per turn), so this always
    returns ``[]`` against the production driver -- an honest gap: a daily
    breakdown is real, useful information this driver does not yet have
    a way to produce.
    """
    return _dr.default_driver().usage(agent_id).by_day


def pod_counted_tokens(project: str) -> int:
    """The pod's counted tokens: each member's input minus cache reads, plus output, summed over
    the pod's members and all their sessions. The measure a task's ``maxTokens`` uses, and what the
    pod's ``budgetTokens`` is compared with."""
    all_ids = [a.id for a in _fleet.list_agents()]
    total = 0
    for mid, _role, _idx in _pod.members_of(all_ids, project):
        totals = aggregate_usage(mid)
        total += max(0, totals.input_tokens - totals.cache_read) + totals.output_tokens
    return total
