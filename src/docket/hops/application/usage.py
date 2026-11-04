from __future__ import annotations

from datetime import datetime

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
    ``agent.driver.default_driver()``.
    """
    return _dr.default_driver().usage(agent_id).by_day


def pod_counted_tokens(project: str, since: datetime | None = None) -> int:
    """The pod's counted tokens (input minus cache reads, plus output) over its members and sessions:
    what ``maxTokens`` and ``budgetTokens`` measure. With *since*, only the day buckets on or after
    *since*'s date count (the pod's ``budgetWindow``)."""
    all_ids = [a.id for a in _fleet.list_agents()]
    first_day = None if since is None else since.date().isoformat()
    total = 0
    for mid, _role, _idx in _pod.members_of(all_ids, project):
        if first_day is None:
            totals = aggregate_usage(mid)
            total += max(0, totals.input_tokens - totals.cache_read) + totals.output_tokens
            continue
        for day in usage_history(mid):
            if day.date >= first_day:
                total += max(0, day.input_tokens - day.cache_read) + day.output_tokens
    return total
