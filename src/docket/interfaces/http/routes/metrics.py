from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from docket.governance import approval as _approval
from docket.governance import audit as _audit
from docket.interfaces.http.exchange import HttpExchange
from docket.kernel import clock as _clock
from docket.kernel.home import current_home
from docket.observability import trace as _trace
from docket.operator import inbox as _inbox
from docket.platform import read_json
from docket.tasks.application import escalation as _escalation
from docket.teams import utils


def _cost_json() -> dict[str, Any]:
    """Per-project cost payload: {agents:[{id,model,costUsd,turns}], totalUsd}."""

    agents: list[dict[str, Any]] = []
    total = 0.0
    for pid in utils.project_ids():
        raw = read_json(current_home().meta_path(pid))
        model = str(raw.get("model", current_home().default_model))
        totals = utils.aggregate_cost(pid)
        cost = totals.cost_usd
        total += cost
        agents.append(
            {
                "id": pid,
                "model": model,
                "costUsd": round(cost, 6),
                "turns": totals.turns,
            }
        )
    return {"agents": agents, "totalUsd": round(total, 6)}


def _esc(s: Any) -> str:
    """Strip backslashes and double-quotes from a label value."""
    return str(s).replace("\\", "").replace('"', "")


# ── guardrail + loop metrics ─────────────────────────────────────────────────
#
# Denial rate, approvals granted/denied/timed-out by channel, policy-hit
# counts by policy id, tool-call rate and turn latency — the numbers an
# operator opens after an incident. `docket start` is not a long-lived
# process holding counters in memory (a restart would silently zero them),
# so every number here is recomputed fresh, on every scrape, from the same
# durable records `docket task trace`/`docket log` already show an operator —
# no second counter store, nothing that can drift from what's on disk, and
# nothing that is lost on restart.
#
# Telemetry stays separate from the audit log itself: this module only
# *reads* trace JSONL and the audit log to compute counters, it never writes
# through them and never routes a metric back into either.

# governance/gate.py's `audit_tool_decision` embeds the raw pre_tool_call
# policy hit as a fixed `policy_id='...' policy_action='...'` pair right
# after the agent/role/project prefix, specifically so this can be parsed
# without scraping the free-text reason that follows it.
_POLICY_AUDIT_RE = re.compile(r"policy_id='([^']*)' policy_action='([^']*)'")
# approval.grant/approval.deny's detail is `token=... project=... channel=...`
# (governance/approval.py) -- channel is always one of a small, code-controlled set
# (cli/http/mcp/telegram/timeout), never free text a caller supplies.
_CHANNEL_AUDIT_RE = re.compile(r"channel=(\S+)")

# The four `agent/tools/registry.py` audit actions that can carry a pre_tool_call
# policy hit (`tool.deny`/`tool.ask` may also be a bare command-classifier
# decision with no policy involved at all -- see `_collect_audit_loop_metrics`).
_TOOL_GATE_ACTIONS: frozenset[str] = frozenset(
    {"tool.deny", "tool.ask", "tool.warn", "tool.redact"}
)
# governance/approval.py's two terminal audit actions -> the outcome label. A
# fail-closed timeout resolves via `approval.deny` with `channel=timeout`
# (never `approval.grant`), so "timed out" surfaces here as
# `channel="timeout",outcome="denied"` -- exactly what the audit log records,
# rather than a fabricated third outcome value with nothing behind it.
_APPROVAL_AUDIT_ACTIONS: dict[str, str] = {"approval.grant": "granted", "approval.deny": "denied"}


@dataclass
class LoopMetrics:
    """Guardrail + loop counters, aggregated fresh on every scrape -- never a precomputed/cached
    value to keep in sync. Field-by-field Prometheus mapping: specs/data/serve-read-api.spec.md
    (GET /metrics).

    ``tool_calls``/``policy_hits``/``approvals`` key on small, code-controlled vocabularies (gate
    decision, hook+action pair, channel+outcome), so merging multiple sources into one dict never
    grows unbounded. ``turn_duration_seconds_sum``/``_count`` is a bare Prometheus summary pair --
    deliberately no invented percentiles; an operator gets the mean from sum/count, the same
    per-project concept ``interfaces/cli/commands/status.py`` computes, just fleet-wide and unwindowed."""

    tool_calls: dict[str, int] = field(default_factory=dict)
    policy_hits: dict[tuple[str, str, str], int] = field(default_factory=dict)
    approvals: dict[tuple[str, str], int] = field(default_factory=dict)
    turn_duration_seconds_sum: float = 0.0
    turn_duration_seconds_count: int = 0


def _collect_trace_loop_metrics(m: LoopMetrics) -> None:
    """Fold every project's trace JSONL into *m*. Mirrors
    ``observability.trace.sweep_all``'s ``*/*.jsonl`` glob -- every project, not one.
    """
    traces_dir = current_home().traces_dir
    if not traces_dir.is_dir():
        return
    for tf in sorted(traces_dir.glob("*/*.jsonl")):
        start_ts: Any = None
        end_ts: Any = None
        for rec in _trace.read_trace(tf):
            etype = rec.get("event_type")
            raw_payload = rec.get("payload")
            payload: dict[str, Any] = raw_payload if isinstance(raw_payload, dict) else {}
            if etype == "tool_result":
                decision = str(payload.get("decision", ""))
                if decision:
                    m.tool_calls[decision] = m.tool_calls.get(decision, 0) + 1
            elif etype == "guardrail_check":
                policy_id = str(payload.get("policy", ""))
                hook = str(payload.get("hook", ""))
                action = str(payload.get("action", ""))
                if policy_id and hook and action:
                    key = (policy_id, hook, action)
                    m.policy_hits[key] = m.policy_hits.get(key, 0) + 1
            elif etype == "session_start":
                start_ts = rec.get("ts")
            elif etype == "session_end":
                end_ts = rec.get("ts")
        if start_ts and end_ts:
            s, e = _clock.parse_epoch(start_ts), _clock.parse_epoch(end_ts)
            if s is not None and e is not None and e >= s:
                m.turn_duration_seconds_sum += e - s
                m.turn_duration_seconds_count += 1


def _collect_audit_loop_metrics(m: LoopMetrics) -> None:
    """Fold the audit log's tool-gate and approval entries into *m*."""
    for entry in _audit.read_audit():
        action = str(entry.get("action", ""))
        detail = str(entry.get("detail", ""))
        if action in _TOOL_GATE_ACTIONS:
            hit = _POLICY_AUDIT_RE.search(detail)
            if not hit:
                continue
            policy_id: str = hit.group(1)
            policy_action: str = hit.group(2)
            # Empty policy_id, or policy_action "allow" (matched but didn't
            # decide anything), means this call's decision came from the
            # command classifier alone -- not a policy hit.
            if not policy_id or policy_action in ("", "allow"):
                continue
            policy_key = (policy_id, "pre_tool_call", policy_action)
            m.policy_hits[policy_key] = m.policy_hits.get(policy_key, 0) + 1
        elif action in _APPROVAL_AUDIT_ACTIONS:
            outcome = _APPROVAL_AUDIT_ACTIONS[action]
            chan_hit = _CHANNEL_AUDIT_RE.search(detail)
            channel: str = chan_hit.group(1) if chan_hit else "unknown"
            approval_key = (channel, outcome)
            m.approvals[approval_key] = m.approvals.get(approval_key, 0) + 1


def _loop_metrics() -> LoopMetrics:
    m = LoopMetrics()
    _collect_trace_loop_metrics(m)
    _collect_audit_loop_metrics(m)
    return m


def _escalation_metrics_lines() -> list[str]:
    """Render escalation metrics (task claims, questions, latency) as Prometheus lines."""

    esc = _escalation.count_escalation_metrics()

    lines: list[str] = [
        "# HELP docket_tasks_started_total Number of dispatch task claims (session_start"
        " trace events); lifetime-of-storage count, resets on trace expiry",
        "# TYPE docket_tasks_started_total counter",
        "docket_tasks_started_total " + str(esc.tasks_started_total),
        "# HELP docket_questions_total Questions asked to operators, by kind and outcome;"
        " lifetime-of-storage count, resets on task deletion",
        "# TYPE docket_questions_total counter",
    ]
    for (kind, outcome), count in sorted(esc.questions_total.items()):
        lines.append(
            'docket_questions_total{kind="'
            + _esc(kind)
            + '",outcome="'
            + _esc(outcome)
            + '"} '
            + str(count)
        )

    lines += [
        "# HELP docket_decision_latency_seconds Seconds from question createdAt to"
        " answeredAt, answered questions only; lifetime-of-storage count",
        "# TYPE docket_decision_latency_seconds summary",
        "docket_decision_latency_seconds_sum " + str(esc.decision_latency_seconds_sum),
        "docket_decision_latency_seconds_count " + str(esc.decision_latency_seconds_count),
    ]
    return lines


def render_metrics() -> str:
    """Render Prometheus-format metrics (no trailing newline; callers append it)."""
    d = _cost_json()

    lines: list[str] = [
        "# HELP docket_agents_total Number of project agents",
        "# TYPE docket_agents_total gauge",
        "docket_agents_total " + str(len(d.get("agents", []))),
        "# HELP docket_agent_cost_usd Cumulative cost per agent (USD)",
        "# TYPE docket_agent_cost_usd gauge",
    ]
    for a in d.get("agents", []):
        lab = 'agent="' + _esc(a.get("id", "")) + '",model="' + _esc(a.get("model", "")) + '"'
        lines.append("docket_agent_cost_usd{" + lab + "} " + str(a.get("costUsd", 0)))
    lines += [
        "# HELP docket_agent_turns_total Total turns per agent",
        "# TYPE docket_agent_turns_total gauge",
    ]
    for a in d.get("agents", []):
        lines.append(
            'docket_agent_turns_total{agent="'
            + _esc(a.get("id", ""))
            + '"} '
            + str(a.get("turns", 0))
        )

    pending = len(_approval.list_pending())
    lines += [
        "# HELP docket_cost_usd_total Total cost across all agents (USD)",
        "# TYPE docket_cost_usd_total gauge",
        "docket_cost_usd_total " + str(d.get("totalUsd", 0)),
        "# HELP docket_approvals_pending_total Pending approvals awaiting a human decision",
        "# TYPE docket_approvals_pending_total gauge",
        "docket_approvals_pending_total " + str(pending),
    ]

    inbox_view = _inbox.build_inbox(now=_clock.stamp())
    lines += [
        "# HELP docket_inbox_items Items in the derived operator inbox, by section",
        "# TYPE docket_inbox_items gauge",
        'docket_inbox_items{section="needsYou"} ' + str(len(inbox_view.needs_you)),
        'docket_inbox_items{section="failed"} ' + str(len(inbox_view.failed)),
        'docket_inbox_items{section="doneSince"} ' + str(len(inbox_view.done_since)),
        'docket_inbox_items{section="running"} ' + str(len(inbox_view.running)),
    ]

    # Guardrail + loop metrics -- see LoopMetrics' docstring for where each
    # number is sourced from.
    #
    # Durability caveat -- BOTH sources now lose history, for different reasons,
    # and every counter here is therefore a lifetime-of-current-storage count
    # rather than a true monotonic total:
    #
    # 1. Audit-derived (all of docket_approvals_total, and the pre_tool_call
    #    slice of docket_policy_hits_total) see only $DOCKET_HOME/audit.log's
    #    CURRENT generation. governance/audit.py rotates that file to a single backup
    #    (audit.log.1, itself overwritten by the next rotation) once it exceeds
    #    AUDIT_LOG_MAX_BYTES, and read_audit() reads only the current file --
    #    so a rotation silently drops whatever history was in the backup.
    # 2. Trace-derived (docket_tool_calls_total, the pre_input/pre_output half
    #    of docket_policy_hits_total, and the turn-duration pair below) had no
    #    such gap while traces were only ever appended to. They now expire:
    #    observability/trace.py's expire_old_traces() deletes terminated traces
    #    past TRACE_RETENTION_S. Retention bounds storage growth, which was the
    #    point, but it means these counters drop when a trace file ages out.
    #
    # The consequence is the same for both, and it is why this is worth a
    # comment rather than a footnote: a `rate()` over a counter that drops to a
    # PARTIAL value (not zero) misreads it as a reset followed by an
    # under-counted window, not as missing history. Do not build an alert that
    # assumes these are monotonic.
    loop = _loop_metrics()

    lines += [
        "# HELP docket_tool_calls_total Tool calls dispatched through the gated"
        " tool registry, by gate decision",
        "# TYPE docket_tool_calls_total counter",
    ]
    for decision, count in sorted(loop.tool_calls.items()):
        lines.append('docket_tool_calls_total{decision="' + _esc(decision) + '"} ' + str(count))

    lines += [
        "# HELP docket_policy_hits_total Guardrail policy hits, by policy id, hook and action"
        " (the pre_tool_call slice is bounded by the audit log's current generation --"
        " see the rotation caveat above)",
        "# TYPE docket_policy_hits_total counter",
    ]
    for (policy_id, hook, action), count in sorted(loop.policy_hits.items()):
        lab = (
            'policy_id="'
            + _esc(policy_id)
            + '",hook="'
            + _esc(hook)
            + '",action="'
            + _esc(action)
            + '"'
        )
        lines.append("docket_policy_hits_total{" + lab + "} " + str(count))

    lines += [
        "# HELP docket_approvals_total Resolved approvals, by channel and outcome"
        ' (channel="timeout" is a fail-closed expiry, not a human channel; bounded by'
        " the audit log's current generation -- see the rotation caveat above)",
        "# TYPE docket_approvals_total counter",
    ]
    for (channel, outcome), count in sorted(loop.approvals.items()):
        lab = 'channel="' + _esc(channel) + '",outcome="' + _esc(outcome) + '"'
        lines.append("docket_approvals_total{" + lab + "} " + str(count))

    # A `summary` family (Prometheus text exposition format): one HELP/TYPE
    # pair on the bare metric name, then its `_sum`/`_count` lines -- not two
    # independent counters. No quantile lines: a summary with none is valid,
    # and is exactly the "no invented percentiles" shape (see
    # LoopMetrics.turn_duration_seconds_sum/_count's docstring) -- an
    # operator gets the mean from sum/count and nothing fabricated beyond it.
    lines += [
        "# HELP docket_turn_duration_seconds Session wall-clock"
        " (session_start -> session_end), fleet-wide",
        "# TYPE docket_turn_duration_seconds summary",
        "docket_turn_duration_seconds_sum " + str(loop.turn_duration_seconds_sum),
        "docket_turn_duration_seconds_count " + str(loop.turn_duration_seconds_count),
    ]

    lines += _escalation_metrics_lines()

    return "\n".join(lines)


def get_metrics(h: HttpExchange, _arg: str) -> None:
    h._send((render_metrics() + "\n").encode("utf-8"), "text/plain; version=0.0.4")
