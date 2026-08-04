"""Command: serve — local HTTP endpoints for dashboards / monitoring.

Exposes:
  /status.json         full snapshot (agents, bindings, costs)
  /metrics             Prometheus-format metrics (no external dependency)
  /health              liveness JSON
  /approvals           list pending approvals (auth required)
  /approvals/<token>   grant or deny a pending approval (auth required)
  /runs                 list dispatch run records, newest first (auth required)
  /runs/<id>            one dispatch run record (auth required)
  /dispatch/<project>   trigger a pod dispatch; returns a queryable run id (auth required)
  /tasks/<project>      the pod's task queue, as core.dispatch.read_tasks returns it
                        (auth required)
  /traces/<project>     cursor'd raw trace JSONL for one project — ?since=<cursor>
                        resumes a poll loop exactly where the last page left off
                        (auth required; see _traces_page's docstring for the cursor
                        format and why a bare last-seen ts is not enough)

Security model: the server binds to 127.0.0.1 (loopback-only) by default —
`run_serve`'s ``bind`` parameter can widen that, but nothing in docket
recommends or automates doing so; treat any non-loopback bind as an explicit,
on-you decision (there is no additional network ACL here, only the bearer
token below). A randomly-generated Bearer token is required on every
/approvals, /runs, /tasks, /traces and /dispatch request (DOCKET_SERVE_TOKEN
env var pins a fixed token); it is printed at startup by default, or written
to a 0600 file via ``--token-file``/``token_file=`` when stdout isn't a safe
place for it (e.g. a systemd unit's journal). The approval endpoints reject
all requests without a valid token — compared with `secrets.compare_digest`,
not `==`, before touching approval state.

Every dispatch this server triggers — webhook, due schedule, or the
periodic sweep — is recorded in the ``core.runs`` registry *before* it starts
and folded to a terminal state when it finishes, so an operator can always
distinguish "done", "failed", and "never ran" via ``docket runs show`` /
``GET /runs/<id>``. No dispatch call site in this module silently discards an
exception (no bare ``contextlib.suppress(Exception)`` around dispatch) — see
``core/runs.py``'s ``execute()``.

``POST /approvals/<token>`` genuinely resumes or kills a pod-dispatch task the
require_approval gate stopped, not just the approval record's own state — see
``core/dispatch.py``'s ``resolve_waiting_approval`` (a no-op for any other approval).

``POST /dispatch/<project>``'s JSON body — a plain ``{name: value}`` object,
``{}`` if the body is omitted — is resolved against the pod's effective pipeline's
declared ``variables`` (``core.pipeline.resolve_variables``) before the run record
is even created; a missing *required* variable is rejected with 400 and never
reaches the run registry. The resolved namespace is persisted on the run record
itself (``variables``), so ``docket runs show <id>``/``GET /runs/<id>`` can answer
"what params did this dispatch actually see". Due-schedule dispatch (``_check_schedules``)
also recognizes a standard 5-field cron expression, not just ``@every``/``HH:MM``
— see ``core/schedule.py``.
"""

from __future__ import annotations

import contextlib
import datetime as _dt
import json
import os
import re
import secrets
import threading
import urllib.parse as _urlparse
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import docket.config as cfg
from docket.core import audit as _audit
from docket.core import fleet as oc
from docket.core import trace as _trace
from docket.core import utils

DEFAULT_PORT = 7331
DEFAULT_INTERVAL = 30

# Bumped on any breaking change to /status.json or /metrics contract, or to the
# authenticated write/read-registry endpoints (/dispatch, /runs).
# Pinned by tests/python/test_serve_read_api.py (TestApiContract).
SERVE_API_VERSION = "2"

_SPECIALISTS = tuple(cfg.ORG_DISPLAY_ORDER)


def _utc_timestamp() -> str:
    """Return current UTC time as 'YYYY-MM-DDTHH:MM:SSZ' (matches `date -u`)."""
    return _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _last_activity_or_never(agent_id: str) -> str:
    """Like utils.last_activity but returns 'never' (cmd_snapshot's sentinel)."""
    val = utils.last_activity(agent_id)
    return "never" if val == "—" else val


def _agent_record(agent_id: str, *, kind: str, registered: set[str]) -> dict[str, Any]:
    from docket.edges import store

    meta_path = cfg.meta_path(agent_id)
    meta: dict[str, Any] = store.read_json(meta_path) if meta_path.exists() else {}
    cost = round(utils.aggregate_cost(agent_id).cost_usd, 6)
    default_scope = "project" if kind == "project" else "org"
    budget_raw = meta.get("budgetUsd")
    budget: float | None = (
        float(budget_raw) if budget_raw and str(budget_raw) not in ("", "0") else None
    )
    return {
        "id": agent_id,
        "name": str(meta.get("name", agent_id)),
        "kind": kind,
        "scope": str(meta.get("scope", default_scope)),
        "model": str(meta.get("model", "")),
        "registered": agent_id in registered,
        "bindings": oc.agent_bindings(agent_id),
        "lastActivity": _last_activity_or_never(agent_id),
        "costUsd": cost,
        "budgetUsd": budget,
    }


def build_status() -> dict[str, Any]:
    """Build the /status.json payload.

    Shape (v1)::

        {apiVersion, timestamp, gateway, channels, agents:[...], totalCostUsd}

    ``gateway`` is ``"active"`` or ``"inactive"``; each agent carries
    {id,name,kind,scope,model,registered,bindings,lastActivity,costUsd,budgetUsd}.
    Contract is versioned by ``SERVE_API_VERSION`` and pinned in
    ``specs/data/serve-read-api.spec.md``.
    """
    gateway = "active" if utils.gateway_active() else "inactive"
    channels = oc.channel_names()
    registered = {a.id for a in oc.list_agents()}

    agents: list[dict[str, Any]] = []
    total_cost = 0.0

    for pid in utils.project_ids():
        rec = _agent_record(pid, kind="project", registered=registered)
        total_cost += float(rec["costUsd"])
        agents.append(rec)

    for spec in _SPECIALISTS:
        spec_dir = cfg.WORKSPACES_DIR / spec
        if not spec_dir.is_dir():
            continue
        rec = _agent_record(spec, kind="specialist", registered=registered)
        total_cost += float(rec["costUsd"])
        agents.append(rec)

    return {
        "apiVersion": SERVE_API_VERSION,
        "timestamp": _utc_timestamp(),
        "gateway": gateway,
        "channels": channels,
        "agents": agents,
        "totalCostUsd": round(total_cost, 6),
    }


def _cost_json() -> dict[str, Any]:
    """Per-project cost payload.

    Returns {agents:[{id,model,costUsd,turns,...}], totalUsd}. Metrics only
    cover project agents (specialists are excluded).
    """
    from docket.edges import store

    agents: list[dict[str, Any]] = []
    total = 0.0
    for pid in utils.project_ids():
        raw = store.read_json(cfg.meta_path(pid))
        model = str(raw.get("model", cfg.DEFAULT_MODEL))
        budget_raw = raw.get("budgetUsd")
        totals = utils.aggregate_cost(pid)
        cost = totals.cost_usd
        total += cost
        budget_val = float(budget_raw) if budget_raw and str(budget_raw) not in ("", "0") else None
        agents.append(
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
    return {"agents": agents, "totalUsd": round(total, 6)}


def _esc(s: Any) -> str:
    """Strip backslashes and double-quotes from a label value."""
    return str(s).replace("\\", "").replace('"', "")


# ── guardrail + loop metrics ─────────────────────────────────────────────────
#
# Denial rate, approvals granted/denied/timed-out by channel, policy-hit
# counts by policy id, tool-call rate and turn latency — the numbers an
# operator opens after an incident. `docket serve` is not a long-lived
# process holding counters in memory (a restart would silently zero them),
# so every number here is recomputed fresh, on every scrape, from the same
# durable records `docket trace`/`docket audit` already show an operator —
# no second counter store, nothing that can drift from what's on disk, and
# nothing that is lost on restart.
#
# Telemetry stays separate from the audit log itself: this module only
# *reads* trace JSONL and the audit log to compute counters, it never writes
# through them and never routes a metric back into either.

# core/tools.py's `_audit_tool_decision` embeds the raw pre_tool_call
# policy hit as a fixed `policy_id='...' policy_action='...'` pair right
# after the agent/role/project prefix, specifically so this can be parsed
# without scraping the free-text reason that follows it.
_POLICY_AUDIT_RE = re.compile(r"policy_id='([^']*)' policy_action='([^']*)'")
# approval.grant/approval.deny's detail is `token=... project=... channel=...`
# (core/approval.py) -- channel is always one of a small, code-controlled set
# (cli/http/mcp/telegram/timeout), never free text a caller supplies.
_CHANNEL_AUDIT_RE = re.compile(r"channel=(\S+)")

# The four `core/tools.py` audit actions that can carry a pre_tool_call
# policy hit (`tool.deny`/`tool.ask` may also be a bare command-classifier
# decision with no policy involved at all -- see `_collect_audit_loop_metrics`).
_TOOL_GATE_ACTIONS: frozenset[str] = frozenset(
    {"tool.deny", "tool.ask", "tool.warn", "tool.redact"}
)
# core/approval.py's two terminal audit actions -> the outcome label. A
# fail-closed timeout resolves via `approval.deny` with `channel=timeout`
# (never `approval.grant`), so "timed out" surfaces here as
# `channel="timeout",outcome="denied"` -- exactly what the audit log records,
# rather than a fabricated third outcome value with nothing behind it.
_APPROVAL_AUDIT_ACTIONS: dict[str, str] = {"approval.grant": "granted", "approval.deny": "denied"}


@dataclass
class LoopMetrics:
    """Guardrail + loop counters, aggregated fresh on every scrape.

    ``tool_calls``: decision ("allow"/"ask"/"deny") -> count, from every
    ``tool_result`` trace event core/agent_loop.py emits for each
    ``dispatch_tool`` call. Doubles as both tool-call rate (sum of all
    buckets) and denial rate (the "deny" bucket over that sum) -- the
    standard Prometheus shape (a `rate()`/ratio over counters), not a
    precomputed percentage this module would otherwise have to keep in sync.

    ``policy_hits``: (policy_id, hook, action) -> count, merged from two
    sources -- the structured ``guardrail_check`` trace event
    (pre_input/pre_output; core/dispatch.py) and the enriched
    ``policy_id=``/``policy_action=`` fields core/tools.py's tool-gate audit
    entries carry (pre_tool_call). ``hook``/``action`` are both
    small, code-controlled vocabularies (3 hooks, 4 policy actions);
    ``policy_id`` is bounded by the operator's own installed policy files.

    ``approvals``: (channel, outcome) -> count, from every
    ``approval.grant``/``approval.deny`` audit entry -- channel is one of
    cli/http/mcp/telegram/timeout (core/approval.py's own closed set of
    callers), outcome is "granted"/"denied".

    ``turn_duration_seconds_sum``/``_count``: a Prometheus-conventional
    summary pair (no invented percentiles -- this module reports only
    sum/count, never a fabricated quantile), built from every
    ``session_start``/``session_end`` bracket found in any
    trace file, fleet-wide -- the same terminal-session concept
    `docket metrics`/`cli/_metrics.py` already computes per-project, just
    unwindowed and summed across every project rather than one.
    """

    tool_calls: dict[str, int] = field(default_factory=dict)
    policy_hits: dict[tuple[str, str, str], int] = field(default_factory=dict)
    approvals: dict[tuple[str, str], int] = field(default_factory=dict)
    turn_duration_seconds_sum: float = 0.0
    turn_duration_seconds_count: int = 0


def _epoch_seconds(ts: Any) -> float | None:
    """Parse a leading 'YYYY-MM-DDTHH:MM:SS' trace timestamp as a UTC epoch."""
    if not isinstance(ts, str) or len(ts) < 19:
        return None
    try:
        return (
            _dt.datetime.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=_dt.UTC).timestamp()
        )
    except ValueError:
        return None


def _collect_trace_loop_metrics(m: LoopMetrics) -> None:
    """Fold every project's trace JSONL into *m* (tool calls, policy hits,
    turn durations). Mirrors ``core.trace.sweep_all``'s ``*/*.jsonl`` glob —
    every project, not one.
    """
    traces_dir = cfg.TRACES_DIR
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
            s, e = _epoch_seconds(start_ts), _epoch_seconds(end_ts)
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


def render_metrics() -> str:
    """Render Prometheus-format metrics.

    No trailing newline; callers append it.
    """
    d = _cost_json()
    gw = "1" if utils.gateway_active() else "0"

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
        lines.append(
            'docket_agent_turns_total{agent="'
            + _esc(a.get("id", ""))
            + '"} '
            + str(a.get("turns", 0))
        )
    from docket.core import approval as _approval

    pending = len(_approval.list_pending())
    lines += [
        "# HELP docket_cost_usd_total Total cost across all agents (USD)",
        "# TYPE docket_cost_usd_total gauge",
        "docket_cost_usd_total " + str(d.get("totalUsd", 0)),
        "# HELP docket_gateway_up Gateway service active (1) or not (0)",
        "# TYPE docket_gateway_up gauge",
        "docket_gateway_up " + gw,
        "# HELP docket_approvals_pending_total Pending approvals awaiting a human decision",
        "# TYPE docket_approvals_pending_total gauge",
        "docket_approvals_pending_total " + str(pending),
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
    #    CURRENT generation. core/audit.py rotates that file to a single backup
    #    (audit.log.1, itself overwritten by the next rotation) once it exceeds
    #    AUDIT_LOG_MAX_BYTES, and read_audit() reads only the current file --
    #    so a rotation silently drops whatever history was in the backup.
    # 2. Trace-derived (docket_tool_calls_total, the pre_input/pre_output half
    #    of docket_policy_hits_total, and the turn-duration pair below) used to
    #    have no such gap, because traces were only ever appended to. They now
    #    expire: core/trace.py's expire_old_traces() deletes terminated traces
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

    return "\n".join(lines)


def render_health() -> str:
    """Render the /health body.

    Format: ``{"status":"ok","gateway":N}\\n`` where N is 1 or 0.
    """
    gw = 1 if utils.gateway_active() else 0
    return f'{{"status":"ok","gateway":{gw}}}\n'


def render_status() -> str:
    """Render the /status.json body (indent=2, matching cmd_snapshot)."""
    return json.dumps(build_status(), indent=2)


def _check_schedules(now_ts: float) -> None:
    """Trigger dispatch for pods whose schedule spec is due.

    Reads the schedule config from ``cfg.SCHEDULE_FILE``; the last-run
    timestamp used to decide "due" is read from — and, once a project fires,
    written back into — that same file (``core.schedule.load_last_run`` /
    ``record_last_run``) rather than an in-memory dict, so a ``docket serve``
    restart does not re-fire every schedule on its first sweep.

    Each due project gets a run record (source ``"schedule"``) created up
    front, then is dispatched in a daemon thread via ``core.runs.execute`` so
    the sweep loop is never blocked by an agent run — and so the outcome
    (including an exception) always lands in the run registry instead of
    being silently discarded.
    """
    from docket.core import dispatch as _dispatch
    from docket.core import runs as _runs
    from docket.core import schedule as _sched

    schedules = _sched.load_schedules(cfg.SCHEDULE_FILE)
    last_run_map = _sched.load_last_run(cfg.SCHEDULE_FILE)
    for project, spec in schedules.items():
        last_run = last_run_map.get(project, 0.0)
        if not _sched.is_schedule_due(spec, last_run, now_ts):
            continue
        _sched.record_last_run(cfg.SCHEDULE_FILE, project, now_ts)

        record = _runs.create_run("schedule", project)

        def _run(proj: str = project, run_id: str = record["id"]) -> None:
            # Process-wide timeout knobs (unset = no override) run inside the
            # run record, so a scheduled dispatch is both configurable and
            # observable rather than fire-and-forget.
            _runs.execute(
                run_id,
                lambda: _dispatch.dispatch_pod(
                    proj,
                    turn_timeout=cfg.DISPATCH_TURN_TIMEOUT_S,
                    verify_timeout=cfg.DISPATCH_VERIFY_TIMEOUT_S,
                ),
            )

        t = threading.Thread(target=_run, daemon=True)
        t.start()


def _run_sweeps(dispatch: bool = False) -> None:
    """Run the periodic sweeps once, each best-effort.

    Coerces stale open traces to aborted, deletes terminated traces past
    TRACE_RETENTION_S, and expires pending approvals past APPROVAL_TIMEOUT.
    Every sweep is guarded so one failure never aborts the others or the server.

    Retention is measured from when a session ENDED, not from when it was last
    active, and the two sweeps compose to make that so: ``expire_old_traces``
    only ever deletes an already-terminated trace, and ``sweep_all``'s synthetic
    session_end carries a fresh ``_now_iso()`` timestamp. So an abandoned trace
    is first terminated, and only then starts its retention clock — an ancient
    stale-open trace survives a full window after the sweep first notices it,
    rather than being deleted on sight. That is deliberate: the alternative
    deletes evidence of an abandoned session at the exact moment an operator
    would go looking for it. ``audit.log`` is not swept at all — telemetry is
    sampled and lossy by design, an audit log must be neither.

    When *dispatch* is set, also drives every dispatchable pod's queued tasks
    through its pipeline (one run record per pod, source ``"sweep"``) and
    checks the schedule file for due projects. These run real, budget-gated
    agent turns so they are opt-in (`docket serve --dispatch`) and never part
    of the read-only monitor.
    """
    import time

    from docket.core import approval, trace

    with contextlib.suppress(Exception):
        trace.sweep_all()
    with contextlib.suppress(Exception):
        trace.expire_old_traces()
    with contextlib.suppress(Exception):
        approval.approval_sweep_expired()
    if dispatch:
        from docket.core import dispatch as _dispatch
        from docket.core import runs as _runs

        try:
            pods_to_dispatch = _dispatch.dispatchable_pods()
        except Exception as exc:
            print(f"[serve] sweep: could not list dispatchable pods: {exc}")
            pods_to_dispatch = []
        for project in pods_to_dispatch:
            record = _runs.create_run("sweep", project)

            def _dispatch_one(proj: str = project) -> list[_dispatch.TaskResult]:
                # Timeout knobs inside this pod's per-pod run record.
                return _dispatch.dispatch_pod(
                    proj,
                    turn_timeout=cfg.DISPATCH_TURN_TIMEOUT_S,
                    verify_timeout=cfg.DISPATCH_VERIFY_TIMEOUT_S,
                )

            _runs.execute(record["id"], _dispatch_one)
        try:
            _check_schedules(time.time())
        except Exception as exc:
            print(f"[serve] sweep: schedule check failed: {exc}")


def _sweep_loop(interval: int, stop: threading.Event, dispatch: bool = False) -> None:
    """Run _run_sweeps every *interval* seconds until *stop* is set."""
    while not stop.wait(interval):
        _run_sweeps(dispatch)


# The Telegram long-poll loop. `core.telegram.poll_once` never raises for an
# unconfigured bot or a network failure (it returns a typed summary) -- the
# `except Exception` below is a last-resort backstop for a genuinely
# unexpected bug in that call chain, and it prints rather than swallows
# (a bare `contextlib.suppress(Exception)` around dispatch is banned; a
# delegate action reaching `core.dispatch.enqueue_task` is exactly that
# "dispatch" this loop must not hide a failure from).
_TELEGRAM_UNCONFIGURED_BACKOFF_S = 30
_TELEGRAM_ERROR_BACKOFF_S = 5


def _telegram_poll_loop(stop: threading.Event) -> None:
    """Long-poll Telegram until *stop* is set, handling one batch per call.

    Paced by Telegram's own long-poll wait
    (`config.TELEGRAM_POLL_TIMEOUT_S`) when a bot token is configured and
    the previous call succeeded -- `getUpdates` itself blocks server-side, so
    no extra sleep is needed on the happy path. Backs off on an unconfigured
    bot (checked again every `_TELEGRAM_UNCONFIGURED_BACKOFF_S`, in case
    `docket keys add TELEGRAM_BOT_TOKEN` runs while `docket serve` is up) or
    a transport failure (`_TELEGRAM_ERROR_BACKOFF_S`) so either case never
    busy-loops.

    `summary.warning` (set when `TELEGRAM_REQUEST_TIMEOUT_S` is misconfigured
    against `TELEGRAM_POLL_TIMEOUT_S` -- see `core.telegram._resolved_request_
    timeout`) is printed once, not every poll: the underlying env var cannot
    change without a restart, so the same warning would otherwise repeat
    every `TELEGRAM_POLL_TIMEOUT_S` seconds for the life of the process.
    """
    from docket.core import telegram as _telegram

    printed_unconfigured = False
    printed_timeout_warning = False
    while not stop.is_set():
        try:
            summary = _telegram.poll_once()
        except Exception as exc:  # pragma: no cover - backstop, see docstring above
            print(f"[serve] telegram: poll failed: {type(exc).__name__}: {exc}")
            if stop.wait(_TELEGRAM_ERROR_BACKOFF_S):
                return
            continue

        if not summary.configured:
            if not printed_unconfigured:
                print(
                    "[serve] telegram: no TELEGRAM_BOT_TOKEN configured "
                    "(docket keys add TELEGRAM_BOT_TOKEN) -- channel idle"
                )
                printed_unconfigured = True
            if stop.wait(_TELEGRAM_UNCONFIGURED_BACKOFF_S):
                return
            continue

        printed_unconfigured = False
        if summary.warning and not printed_timeout_warning:
            print(f"[serve] telegram: {summary.warning}")
            printed_timeout_warning = True
        if not summary.ok:
            print(f"[serve] telegram: {summary.error}")
            if stop.wait(_TELEGRAM_ERROR_BACKOFF_S):
                return


# ── /traces/<project> cursor paging ─────────────────────────────────────────
#
# Built entirely on `core.trace.export_lines(project, since)` — owned by
# another card this wave, used here exactly as it stands. That function's
# `since` filter is `ts >= since`: inclusive, and second-granularity (`ts` is
# `%Y-%m-%dT%H:%M:%SZ`). Both properties matter for a poll loop that must
# ingest every event exactly once:
#
#   * Inclusive means the naive cursor — "next = last event's ts" — would
#     redeliver that same last event (and anything else sharing its second)
#     on the very next poll.
#   * Second granularity means several events sharing one timestamp is
#     routine, not an edge case (a single dispatch hop can emit several trace
#     events inside the same wall-clock second), so "ts > cursor" instead of
#     "ts >= cursor" would silently DROP any same-second event that arrives
#     after the poll that first saw that second, rather than deliver it late.
#
# The cursor this module mints is therefore a compound "<ts>:<n>" token: n is
# how many lines carrying that exact ts have already gone out. Re-querying at
# ts re-fetches that whole second (inclusive filter), and the first n of them
# — stable, since trace files are append-only and never reordered — are
# exactly the ones already delivered, so they're dropped before the response
# is built. See `_traces_page`.


def _trace_line_ts(line: str) -> str:
    """Best-effort ts extraction for cursor bookkeeping.

    Mirrors `export_lines`' own parsing exactly (`str(json.loads(line).get("ts",
    ""))`) so this module's notion of "which second a line belongs to" never
    diverges from the filter it is compensating for. Returns "" for anything
    `export_lines` cannot key on either: malformed JSON, or valid JSON that
    isn't an object.
    """
    try:
        parsed = json.loads(line)
    except json.JSONDecodeError:
        return ""
    if not isinstance(parsed, dict):
        return ""
    return str(parsed.get("ts", ""))


def _decode_trace_cursor(raw: str) -> tuple[str, int]:
    """Decode a `since` query value into (ts, lines already delivered at ts).

    Accepts both a cursor this module minted (`"<ts>:<n>"`) and a bare
    timestamp a caller supplies by hand (n=0) — the latter is a reasonable
    "give me everything from this point on" request, and export_lines' own
    `since` parameter already accepts a plain ts.

    Splitting the two apart needs more care than "does it end in :<digits>",
    because a timestamp CONTAINS colons. `core/trace.py`'s `_now_iso()` writes
    `%Y-%m-%dT%H:%M:%SZ`, so a minted cursor's ts half always ends in `Z` —
    that trailing `Z` is what distinguishes `"...T12:34:56Z:3"` (compound,
    n=3) from `"...T12:34:56"` (a bare ISO ts whose SECONDS would otherwise be
    misread as the count, silently rewinding the cursor to the start of the
    minute and re-delivering it). Requiring the `Z` keeps the hand-supplied
    form this docstring advertises actually working.
    """
    if not raw:
        return "", 0
    ts, sep, tail = raw.rpartition(":")
    if sep and tail.isdigit() and ts.endswith("Z"):
        return ts, int(tail)
    return raw, 0


def _traces_page(project: str, since: str) -> tuple[list[str], str]:
    """One cursor'd page of *project*'s raw trace JSONL, delivered exactly once.

    Returns (lines, next_cursor). `lines` are the verbatim JSONL strings
    `export_lines` returned (untouched — no reformatting, no filtering by
    event type/role/session); `next_cursor` is what a subsequent call's
    `since` should be to resume without re-ingesting or skipping anything —
    see the module-level comment above for why that requires more than the
    last line's raw ts.

    A trailing line this module cannot key on (`_trace_line_ts` returns "")
    is a pre-existing `export_lines` limitation, not something fixed here:
    such a line is always re-included whenever *any* since filter is active,
    regardless of position, so no cursor value can make it stop reappearing.
    This function still returns it (nothing already-fetched is silently
    dropped) but anchors the next cursor on the last line it CAN key on,
    rather than minting a cursor from "" — which would collapse the filter
    entirely and replay the whole project's trace on the next poll.
    """
    cursor_ts, already = _decode_trace_cursor(since)
    lines = _trace.export_lines(project, cursor_ts)

    if already:
        skipped = 0
        i = 0
        while i < len(lines) and skipped < already:
            ts = _trace_line_ts(lines[i])
            if ts == cursor_ts:
                skipped += 1
                i += 1
            elif ts == "":
                # Always re-included regardless of position (see docstring)
                # -- pass over without spending the skip budget on it.
                i += 1
            else:
                break
        lines = lines[i:]

    if not lines:
        return [], since

    anchor_idx = -1
    anchor_ts = ""
    for idx in range(len(lines) - 1, -1, -1):
        ts = _trace_line_ts(lines[idx])
        if ts:
            anchor_idx, anchor_ts = idx, ts
            break
    if anchor_idx == -1:
        # Nothing in this page has a usable ts -- cannot safely advance past
        # the incoming cursor without risking a full replay next time.
        return lines, since

    # How many lines, counting backward from anchor_idx, carry that exact ts
    # -- the size of the trailing same-second run the next poll must skip.
    count_at_anchor = 0
    for idx in range(anchor_idx, -1, -1):
        if _trace_line_ts(lines[idx]) != anchor_ts:
            break
        count_at_anchor += 1
    if anchor_ts == cursor_ts:
        count_at_anchor += already
    return lines, f"{anchor_ts}:{count_at_anchor}"


class _DocketHandler(BaseHTTPRequestHandler):
    """Serves the docket endpoints; builds responses on demand.

    ``serve_token`` is set per-server via a subclass created in ``run_serve``.
    An empty token disallows all auth so the base class can never accidentally
    pass an unauthenticated request through.
    """

    serve_token: str = ""

    def log_message(self, fmt: str, *args: Any) -> None:
        return

    def _send(self, body: bytes, content_type: str, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _check_auth(self) -> bool:
        if not self.serve_token:
            return False
        auth = self.headers.get("Authorization", "")
        expected = f"Bearer {self.serve_token}"
        # Timing-safe compare — a plain `==` short-circuits on
        # the first mismatched byte, leaking token-length/prefix information
        # to an attacker who can measure response latency.
        return secrets.compare_digest(auth, expected)

    def _send_json_error(self, msg: str, status: int = 400) -> None:
        body = json.dumps({"ok": False, "error": msg}).encode()
        self._send(body, "application/json", status)

    def do_GET(self) -> None:
        full_path = self.path
        path = full_path.split("?", 1)[0].rstrip("/")
        if path in ("/status.json", "/status"):
            self._send(render_status().encode("utf-8"), "application/json")
        elif path == "/metrics":
            self._send((render_metrics() + "\n").encode("utf-8"), "text/plain; version=0.0.4")
        elif path == "/health":
            self._send(render_health().encode("utf-8"), "application/json")
        elif path == "/approvals":
            if not self._check_auth():
                self._send_json_error("Unauthorized", 401)
                return
            from docket.core import approval

            body = json.dumps({"pending": approval.list_pending()}).encode("utf-8")
            self._send(body, "application/json")
        elif path == "/runs":
            if not self._check_auth():
                self._send_json_error("Unauthorized", 401)
                return
            from docket.core import runs as _runs

            query = _urlparse.parse_qs(_urlparse.urlsplit(full_path).query)
            project_values = query.get("project")
            project = project_values[0] if project_values else None
            body = json.dumps({"runs": _runs.list_runs(project)}).encode("utf-8")
            self._send(body, "application/json")
        elif path.startswith("/runs/"):
            if not self._check_auth():
                self._send_json_error("Unauthorized", 401)
                return
            run_id = path[len("/runs/") :]
            if not run_id:
                self._send_json_error("Missing run id", 400)
                return
            from docket.core import runs as _runs

            rec = _runs.get_run(run_id)
            if rec is None:
                self._send_json_error(f"Unknown run: {run_id}", 404)
                return
            self._send(json.dumps(rec).encode("utf-8"), "application/json")
        elif path == "/tasks":
            # `path` already had trailing slashes stripped above, so both
            # bare "/tasks" and "/tasks/" (an empty project segment) land
            # here as "Missing project" rather than falling through to a
            # generic 404.
            if not self._check_auth():
                self._send_json_error("Unauthorized", 401)
                return
            self._send_json_error("Missing project", 400)
        elif path.startswith("/tasks/"):
            if not self._check_auth():
                self._send_json_error("Unauthorized", 401)
                return
            project = path[len("/tasks/") :]
            from docket.core import dispatch as _dispatch

            # read_tasks itself returns [] for a project with no pod (absent
            # queue file) -- no 404 invented here, matching that contract.
            body = json.dumps({"tasks": _dispatch.read_tasks(project)}).encode("utf-8")
            self._send(body, "application/json")
        elif path == "/traces":
            # Same rationale as the bare "/tasks" branch above.
            if not self._check_auth():
                self._send_json_error("Unauthorized", 401)
                return
            self._send_json_error("Missing project", 400)
        elif path.startswith("/traces/"):
            if not self._check_auth():
                self._send_json_error("Unauthorized", 401)
                return
            project = path[len("/traces/") :]
            query = _urlparse.parse_qs(_urlparse.urlsplit(full_path).query)
            since_values = query.get("since")
            since = since_values[0] if since_values else ""
            events, next_cursor = _traces_page(project, since)
            body = json.dumps({"events": events, "next": next_cursor}).encode("utf-8")
            self._send(body, "application/json")
        else:
            self._send(b"not found\n", "text/plain", status=404)

    def do_POST(self) -> None:
        path = self.path.split("?", 1)[0].rstrip("/")
        if path.startswith("/approvals/"):
            if not self._check_auth():
                self._send_json_error("Unauthorized", 401)
                return
            approval_token = path[len("/approvals/") :]
            if not approval_token:
                self._send_json_error("Missing approval token", 400)
                return
            try:
                length = int(self.headers.get("Content-Length", 0))
                raw = self.rfile.read(length) if length > 0 else b"{}"
                req_body: dict[str, object] = json.loads(raw)
            except (ValueError, json.JSONDecodeError):
                self._send_json_error("Invalid JSON body", 400)
                return
            action = str(req_body.get("action", ""))
            if action not in ("grant", "deny"):
                self._send_json_error('action must be "grant" or "deny"', 400)
                return
            from docket.core import approval
            from docket.core import dispatch as _dispatch

            # `channel` identifies the surface this decision came through, tagged
            # onto the hash-chained audit log entry (`core/approval.py`'s
            # `approval_grant`/`approval_deny`). Default stays "http" (every caller
            # before this field existed keeps identical behaviour); an unrecognised
            # value is rejected rather than let free text reach the audit log —
            # core owns the vocabulary (`approval.APPROVAL_CHANNELS`), not this module.
            channel = req_body.get("channel", "http")
            if not isinstance(channel, str) or channel not in approval.APPROVAL_CHANNELS:
                self._send_json_error(f"Unrecognised channel: {channel!r}", 400)
                return

            decision = "granted" if action == "grant" else "denied"
            try:
                if action == "grant":
                    approval.approval_grant(approval_token, channel=channel)
                else:
                    approval.approval_deny(approval_token, channel=channel)
                # If this token gated a dispatch task, genuinely resume
                # (grant) or kill (deny) it — see core/dispatch.py's
                # resolve_waiting_approval. A no-op for any other approval.
                _dispatch.resolve_waiting_approval(approval_token, decision)
                rec = approval.approval_get(approval_token)
                resp_body = json.dumps(
                    {"ok": True, "token": approval_token, "state": rec["state"]}
                ).encode()
                self._send(resp_body, "application/json")
            except approval.ApprovalNoop as exc:
                _dispatch.resolve_waiting_approval(approval_token, decision)
                self._send_json_error(exc.message, 409)
            except approval.ApprovalError as exc:
                self._send_json_error(str(exc), 404)
        elif path.startswith("/tasks/"):
            if not self._check_auth():
                self._send_json_error("Unauthorized", 401)
                return
            project = path[len("/tasks/") :]
            if not project:
                self._send_json_error("Missing project", 400)
                return
            try:
                length = int(self.headers.get("Content-Length", 0))
                raw = self.rfile.read(length) if length > 0 else b"{}"
                task_body: Any = json.loads(raw)
            except (ValueError, json.JSONDecodeError):
                self._send_json_error("Invalid JSON body", 400)
                return
            if not isinstance(task_body, dict):
                self._send_json_error("Request body must be a JSON object", 400)
                return

            description = task_body.get("description", "")
            if not isinstance(description, str) or not description:
                self._send_json_error("description is required", 400)
                return
            priority_raw = task_body.get("priority", "normal")
            priority = str(priority_raw) if priority_raw else "normal"
            # `trusted` (optional) overrides the `pre_input` policy check's trust
            # flag for this enqueue only — see core.dispatch.enqueue_task. Absent
            # (None) leaves every existing caller's behaviour byte-for-byte
            # unchanged; this is the only place that field is threaded through.
            trusted_raw = task_body.get("trusted")
            trusted = bool(trusted_raw) if trusted_raw is not None else None

            from docket.core import dispatch as _dispatch

            try:
                task = _dispatch.enqueue_task(project, description, priority, trusted=trusted)
            except _dispatch.DispatchError as exc:
                msg = str(exc)
                # enqueue_task raises DispatchError for exactly two reasons: no
                # pod for this project (404 — nothing to enqueue against), or a
                # `block` pre_input policy verdict (4xx, naming the policy id the
                # exception message already carries — never swallowed into 500).
                status = 404 if msg.startswith("no pod for") else 400
                self._send_json_error(msg, status)
                return

            task_resp: dict[str, Any] = {
                "ok": True,
                "task": task["id"],
                "project": project,
                "status": task["status"],
            }
            # A `require_approval` pre_input verdict leaves the task itself
            # created but gated — surface its real status and token rather than
            # a 200 that implies it is queued to run (see enqueue_task, which
            # already sets both on the returned dict for this case).
            if task["status"] == "waiting_approval":
                task_resp["approvalToken"] = task.get("approvalToken", "")
            self._send(json.dumps(task_resp).encode(), "application/json")
        elif path.startswith("/dispatch/"):
            if not self._check_auth():
                self._send_json_error("Unauthorized", 401)
                return
            project = path[len("/dispatch/") :]
            if not project:
                self._send_json_error("Missing project", 400)
                return
            from docket.core import dispatch as _dispatch
            from docket.core import pipeline as _pipeline
            from docket.core import runs as _runs

            # The request body (a plain {name: value} JSON object) is the
            # webhook's params — bound into the pod's effective pipeline's
            # declared `variables` namespace (core.pipeline.resolve_variables)
            # before anything is dispatched. A missing body (no Content-Length)
            # is the same as `{}`, so an omitted body still behaves as a
            # no-params dispatch.
            try:
                length = int(self.headers.get("Content-Length", 0))
                raw = self.rfile.read(length) if length > 0 else b"{}"
                params: Any = json.loads(raw)
            except (ValueError, json.JSONDecodeError):
                self._send_json_error("Invalid JSON body", 400)
                return
            if not isinstance(params, dict):
                self._send_json_error("Request body must be a JSON object", 400)
                return
            try:
                effective = _dispatch.effective_pipeline(project, None)
                variables = _pipeline.resolve_variables(effective, params)
            except _pipeline.VariableError as exc:
                self._send_json_error(str(exc), 400)
                return

            # The run record is created — and its id handed back to
            # the caller — BEFORE any dispatch work is attempted. The actual
            # pipeline still runs async (this endpoint must not block on a real
            # agent turn), but its outcome always lands in the run registry
            # instead of vanishing behind a fire-and-forget thread.
            record = _runs.create_run("webhook", project, variables=variables)

            def _run(proj: str = project, run_id: str = record["id"]) -> None:
                _runs.execute(
                    run_id,
                    lambda: _dispatch.dispatch_pod(
                        proj,
                        turn_timeout=cfg.DISPATCH_TURN_TIMEOUT_S,
                        verify_timeout=cfg.DISPATCH_VERIFY_TIMEOUT_S,
                    ),
                )

            threading.Thread(target=_run, daemon=True).start()
            resp_body = json.dumps(
                {"ok": True, "run": record["id"], "project": project, "status": "dispatched"}
            ).encode()
            self._send(resp_body, "application/json")
        else:
            self._send_json_error("not found", 404)

    def do_HEAD(self) -> None:
        self.do_GET()


def _write_token_file(path: Path, token: str) -> None:
    """Write *token* to *path* with 0600 perms (create or replace, owner-only).

    Uses ``os.open`` with an explicit mode so the file is never briefly
    world-/group-readable between creation and a follow-up ``chmod``.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(token + "\n")
    finally:
        with contextlib.suppress(OSError):
            os.chmod(path, 0o600)


def run_serve(
    port: int | None = None,
    *,
    bind: str = "127.0.0.1",
    interval: int = DEFAULT_INTERVAL,
    dispatch: bool = False,
    telegram: bool = False,
    token_file: str | None = None,
) -> None:
    """Start the docket HTTP server (blocking) — public CLI entry point.

    Binds to *bind* (default ``127.0.0.1`` — loopback-only; not reachable off
    this host unless the caller explicitly widens it, which docket neither
    recommends nor automates) on the given port (default 7331) and serves
    /status.json, /metrics, /health. Responses are built on each request
    (cheap, index-backed). Runs sweeps once at startup and then every
    *interval* seconds in a daemon thread. Runs until interrupted.

    ``telegram``, when set (``docket serve --telegram``), also starts the
    docket-owned Telegram long-poll loop in its own daemon thread — opt-in,
    matching ``dispatch``, since it is a real externally-reachable channel
    once a bot token is configured. Degrades to an idle, periodically-retried
    wait if no ``TELEGRAM_BOT_TOKEN`` is stored (``docket keys add
    TELEGRAM_BOT_TOKEN``) rather than failing to start — see
    ``core/telegram.py``.

    ``token_file``, when given, writes the bearer token required by
    /approvals and /dispatch to that path (0600 perms) instead of printing it
    to stdout — use this when stdout may land somewhere less private than a
    terminal, e.g. a systemd unit's journal.
    """
    actual_port = DEFAULT_PORT if port is None else port

    _token = os.environ.get("DOCKET_SERVE_TOKEN") or secrets.token_urlsafe(32)

    class _BoundHandler(_DocketHandler):
        serve_token = _token

    _run_sweeps(dispatch)
    stop = threading.Event()
    sweeper = threading.Thread(target=_sweep_loop, args=(interval, stop, dispatch), daemon=True)
    sweeper.start()

    if telegram:
        tg_thread = threading.Thread(target=_telegram_poll_loop, args=(stop,), daemon=True)
        tg_thread.start()

    server = ThreadingHTTPServer((bind, actual_port), _BoundHandler)
    disp = "  dispatch=on" if dispatch else ""
    tg = "  telegram=on" if telegram else ""
    print(f"docket serve  port={actual_port}  refresh={interval}s{disp}{tg}  (Ctrl-C to stop)")
    print(
        f"Endpoints: /status.json  /metrics  /health  /approvals  /runs  /dispatch"
        f"  ->  http://localhost:{actual_port}/"
    )
    loopback = bind in ("127.0.0.1", "localhost", "::1")
    bind_note = "loopback-only" if loopback else "WARNING: not loopback — reachable off this host"
    print(f"Bind: {bind}  ({bind_note})")
    if token_file:
        token_path = Path(token_file)
        _write_token_file(token_path, _token)
        print(f"Approval API token written to {token_path} (0600)  (override: DOCKET_SERVE_TOKEN)")
    else:
        print(f"Approval API token: {_token}  (override: DOCKET_SERVE_TOKEN)")
    print("")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        server.server_close()
