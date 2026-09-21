"""Command: serve — local HTTP endpoints for dashboards / monitoring.

Endpoint list, JSON/Prometheus schemas, and the auth model per endpoint: see
specs/data/serve-read-api.spec.md. Binds to 127.0.0.1 by default; ``run_serve``'s ``bind`` can
widen that, but nothing here recommends or automates it -- treat any non-loopback bind as an
explicit, on-you decision (no network ACL here, only the bearer token). A random Bearer token
(``DOCKET_SERVE_TOKEN`` pins a fixed one) gates every /approvals, /runs, /tasks, /traces, /pods
and /dispatch request, checked with ``secrets.compare_digest`` (never ``==``); printed at startup
or written to a 0600 file via ``--token-file``/``token_file=`` when stdout is unsafe (e.g. a
systemd journal).
Every dispatch is recorded in ``core.runs`` before it starts and folded to a terminal state when it
finishes, so "done"/"failed"/"never ran" stay distinguishable; no call site swallows it silently."""

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
from docket.core import fleet, utils
from docket.core import provisioning as _prov
from docket.core import trace as _trace

DEFAULT_PORT = 7331
DEFAULT_INTERVAL = 30

# Bumped on any breaking change to /status.json or /metrics contract, or to the
# authenticated write/read-registry endpoints (/dispatch, /runs).
# Pinned by tests/unit/test_serve__read_api.py (TestApiContract).
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
        "bindings": fleet.agent_bindings(agent_id),
        "lastActivity": _last_activity_or_never(agent_id),
        "costUsd": cost,
        "budgetUsd": budget,
    }


def build_status() -> dict[str, Any]:
    """Build the /status.json payload. Schema, versioned by ``SERVE_API_VERSION``:
    specs/data/serve-read-api.spec.md (GET /status.json).
    """
    gateway = "active" if utils.gateway_active() else "inactive"
    channels = fleet.channel_names()
    registered = {a.id for a in fleet.list_agents()}

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
    """Per-project cost payload: {agents:[{id,model,costUsd,turns,...}], totalUsd}.
    Project agents only -- specialists are excluded.
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
    """Guardrail + loop counters, aggregated fresh on every scrape -- never a precomputed/cached
    value to keep in sync. Field-by-field Prometheus mapping: specs/data/serve-read-api.spec.md
    (GET /metrics).

    ``tool_calls``/``policy_hits``/``approvals`` key on small, code-controlled vocabularies (gate
    decision, hook+action pair, channel+outcome), so merging multiple sources into one dict never
    grows unbounded. ``turn_duration_seconds_sum``/``_count`` is a bare Prometheus summary pair --
    deliberately no invented percentiles; an operator gets the mean from sum/count, the same
    per-project concept ``cli/_metrics.py`` computes, just fleet-wide and unwindowed."""

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
    """Fold every project's trace JSONL into *m*. Mirrors
    ``core.trace.sweep_all``'s ``*/*.jsonl`` glob -- every project, not one.
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
    """Render Prometheus-format metrics (no trailing newline; callers append it)."""
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
    #    of docket_policy_hits_total, and the turn-duration pair below) had no
    #    such gap while traces were only ever appended to. They now expire:
    #    core/trace.py's expire_old_traces() deletes terminated traces
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
    """Render the /health body: ``{"status":"ok","gateway":N}\\n`` (N is 1 or 0)."""
    gw = 1 if utils.gateway_active() else 0
    return f'{{"status":"ok","gateway":{gw}}}\n'


def render_status() -> str:
    """Render the /status.json body (indent=2, matching cmd_snapshot)."""
    return json.dumps(build_status(), indent=2)


def _check_schedules(now_ts: float) -> None:
    """Trigger dispatch for pods whose schedule spec is due (also recognizes a standard 5-field
    cron expression, not just ``@every``/``HH:MM`` -- see ``core/schedule.py``). The last-run
    timestamp is read from, and written back into, ``cfg.SCHEDULE_FILE`` itself rather than an
    in-memory dict, so a restart does not re-fire every schedule on its first sweep. Each due
    project's run record is created before its daemon-thread dispatch starts, so the sweep loop
    is never blocked and no outcome is silently discarded."""
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
    """Run the periodic sweeps once, each best-effort and independently guarded so one failure
    never aborts the others or the server.

    Coerces stale-open traces to aborted, deletes terminated traces past TRACE_RETENTION_S, and
    expires pending approvals past APPROVAL_TIMEOUT. Retention is measured from when a session
    ENDED, not last active: an abandoned trace is terminated first and only then starts its
    retention clock, so it survives a full window after the sweep notices it -- the alternative
    would delete evidence of an abandoned session at the exact moment an operator would go
    looking for it. ``audit.log`` is never swept: telemetry is lossy by design, an audit log must
    not be.

    When *dispatch* is set (opt-in, real budget-gated agent turns, never part of the read-only
    monitor), also drains every dispatchable pod's queue (one run record per pod, source
    ``"sweep"``) and checks due schedules."""
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
    """Long-poll Telegram (one batch per call) until *stop* is set.

    Paced by Telegram's own blocking `getUpdates` wait when a bot token is configured and the
    previous call succeeded, so no extra sleep is needed on the happy path. Backs off on an
    unconfigured bot (re-checked periodically, in case a token is added while `docket serve` is
    up) or a transport failure, so neither case busy-loops. A resolved-timeout misconfiguration
    warning prints once, not every poll -- the underlying env var cannot change without a
    restart."""
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
    """Best-effort ts extraction for cursor bookkeeping -- mirrors
    `export_lines`' own parsing exactly so "which second" never diverges from
    the filter it compensates for. Returns "" when unkeyable."""
    try:
        parsed = json.loads(line)
    except json.JSONDecodeError:
        return ""
    if not isinstance(parsed, dict):
        return ""
    return str(parsed.get("ts", ""))


def _decode_trace_cursor(raw: str) -> tuple[str, int]:
    """Decode a `since` value into (ts, lines already delivered at ts).

    Accepts both a minted `"<ts>:<n>"` cursor and a bare ISO timestamp a caller supplies by hand
    (n=0). Requires the ts half to end in `Z` to tell them apart: a timestamp CONTAINS colons, so
    a bare `"...T12:34:56"`'s own trailing seconds would otherwise misparse as the digit count,
    silently rewinding the cursor and re-delivering that minute. See
    specs/data/serve-read-api.spec.md (cursor semantics)."""
    if not raw:
        return "", 0
    ts, sep, tail = raw.rpartition(":")
    if sep and tail.isdigit() and ts.endswith("Z"):
        return ts, int(tail)
    return raw, 0


def _traces_page(project: str, since: str) -> tuple[list[str], str]:
    """One cursor'd page of *project*'s raw trace JSONL, delivered exactly once (sorted by ts
    across session files, verbatim, unfiltered). Returns (lines, next_cursor); cursor contract:
    specs/data/serve-read-api.spec.md (GET /traces/<project>).

    A trailing line this module cannot key on (`_trace_line_ts` returns "") is a pre-existing
    `export_lines` limitation, not fixed here: it is always returned (nothing already-fetched is
    silently dropped), but the next cursor anchors on the last line this function CAN key on,
    never on "" -- which would collapse the filter and replay the whole project's trace."""
    cursor_ts, already = _decode_trace_cursor(since)
    # `export_lines` concatenates session files in sorted FILENAME order, and a
    # session id is a uuid -- so with more than one session (any project with
    # history) the raw stream is not chronological. Everything below anchors the
    # cursor on the newest event in the page and counts the run sharing that
    # second, which is only correct on an ordered page; without this sort a
    # multi-session project replays the events that happened to follow the
    # anchor in glob order. Stable, so same-second lines keep their file order,
    # and unkeyable ("") lines sort to the front where the skip loop expects them.
    lines = sorted(_trace.export_lines(project, cursor_ts), key=_trace_line_ts)

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
    """Serves the docket endpoints; builds responses on demand. ``serve_token``
    (a `run_serve` subclass attribute) empty means "disallow all auth" --
    never an accidental unauthenticated pass-through."""

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

    def _reject_bad_project_id(self, project: str) -> bool:
        """Send a `400` and return `True` if *project* fails `validate_project_id` --
        every project-path-segment handler but `_handle_post_pods` (whose `400` comes
        from `provision_pod`'s own boundary check) calls this right after auth."""
        try:
            _prov.validate_project_id(project)
        except _prov.ProjectIdError as exc:
            self._send_json_error(str(exc), 400)
            return True
        return False

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
            if self._reject_bad_project_id(project):
                return
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
            if self._reject_bad_project_id(project):
                return
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
            self._handle_post_approvals(path)
        elif path.startswith("/tasks/"):
            self._handle_post_tasks(path)
        elif path.startswith("/dispatch/"):
            self._handle_post_dispatch(path)
        elif path == "/pods":
            self._handle_post_pods()
        else:
            self._send_json_error("not found", 404)

    def _handle_post_approvals(self, path: str) -> None:
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

    def _handle_post_tasks(self, path: str) -> None:
        if not self._check_auth():
            self._send_json_error("Unauthorized", 401)
            return
        project = path[len("/tasks/") :]
        if not project:
            self._send_json_error("Missing project", 400)
            return
        if self._reject_bad_project_id(project):
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

    def _handle_post_dispatch(self, path: str) -> None:
        if not self._check_auth():
            self._send_json_error("Unauthorized", 401)
            return
        project = path[len("/dispatch/") :]
        if not project:
            self._send_json_error("Missing project", 400)
            return
        if self._reject_bad_project_id(project):
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

    def _handle_post_pods(self) -> None:
        """``POST /pods`` — provision a fresh pod from a blueprint. Body,
        response shape, and the not-a-thin-wrapper/no-drift rationale:
        specs/data/serve-read-api.spec.md (POST /pods)."""
        if not self._check_auth():
            self._send_json_error("Unauthorized", 401)
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length) if length > 0 else b"{}"
            body: Any = json.loads(raw)
        except (ValueError, json.JSONDecodeError):
            self._send_json_error("Invalid JSON body", 400)
            return
        if not isinstance(body, dict):
            self._send_json_error("Request body must be a JSON object", 400)
            return

        project = body.get("project")
        if not isinstance(project, str) or not project:
            self._send_json_error("project is required", 400)
            return

        from docket.core import blueprints as _bp

        blueprint_name = body.get("blueprint", _bp.DEFAULT_BLUEPRINT)
        if not isinstance(blueprint_name, str) or not blueprint_name:
            self._send_json_error("blueprint must be a non-empty string", 400)
            return

        path_value = body.get("path", "")
        if not isinstance(path_value, str):
            self._send_json_error("path must be a string", 400)
            return

        # `pod` mirrors `docket add --pod full` — the CLI's only roster
        # override, itself restricted to the `software` blueprint (a
        # non-`software` blueprint provisions its own fixed roster; the CLI
        # warns and ignores rather than erroring, and there is no HTTP
        # surface to print that warning to, so this route just ignores it
        # the same way).
        pod_field = body.get("pod")
        roles: tuple[str, ...] | None = None
        if pod_field is not None:
            if not isinstance(pod_field, str) or pod_field.lower() != "full":
                self._send_json_error('pod must be "full" if given', 400)
                return
            if blueprint_name == "software":
                from docket.core.pod import FULL_POD_ROLES

                roles = FULL_POD_ROLES

        budget_raw = body.get("budget")
        budget_usd: float | None = None
        if budget_raw is not None:
            if isinstance(budget_raw, bool) or not isinstance(budget_raw, (int, float, str)):
                self._send_json_error("budget must be a number", 400)
                return
            try:
                budget_val = float(budget_raw)
            except (TypeError, ValueError):
                self._send_json_error("budget must be numeric", 400)
                return
            budget_usd = budget_val if budget_val > 0 else None

        verify_cmd = body.get("verifyCmd", "")
        if not isinstance(verify_cmd, str):
            self._send_json_error("verifyCmd must be a string", 400)
            return

        from docket.core import pod_provisioning as _pp
        from docket.core import provisioning as _prov

        try:
            result = _pp.provision_pod(
                project,
                blueprint_name,
                location=path_value,
                roles=roles,
                budget_usd=budget_usd,
                verify_cmd=verify_cmd,
                source="http",
            )
        except _bp.BlueprintError as exc:
            self._send_json_error(str(exc), 400)
            return
        except _pp.VerifyCmdError as exc:
            self._send_json_error(str(exc), 400)
            return
        except _prov.ProjectIdError as exc:
            self._send_json_error(str(exc), 400)
            return
        except _pp.PodAlreadyExistsError:
            self._send_json_error(f"'{project}' already exists", 409)
            return
        except _pp.PodProvisionError as exc:
            # Rollback has already run (see provision_pod's docstring) --
            # nothing from this attempt survives on disk or in the fleet
            # registry. Not a 4xx: the request itself was well-formed, the
            # failure is an operational one (e.g. disk/filesystem trouble).
            self._send_json_error(str(exc), 500)
            return

        resp_body = json.dumps(
            {
                "ok": True,
                "project": result.project,
                "blueprint": result.blueprint,
                "members": [
                    {"id": m.member_id, "role": m.role, "model": m.model} for m in result.members
                ],
            }
        ).encode()
        self._send(resp_body, "application/json", status=201)

    def do_HEAD(self) -> None:
        self.do_GET()


def _write_token_file(path: Path, token: str) -> None:
    """Write *token* to *path* with 0600 perms. Uses ``os.open`` with an
    explicit mode so the file is never briefly world-/group-readable between
    creation and a follow-up ``chmod``."""
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

    Binds to *bind* (default 127.0.0.1) on *port* (default 7331); runs sweeps once at startup and
    then every *interval* seconds in a daemon thread, until interrupted. ``telegram``, opt-in
    like ``dispatch``, starts docket's own Telegram long-poll loop in a daemon thread, degrading
    to an idle, periodically-retried wait rather than failing to start if no bot token is
    configured. ``token_file`` writes the bearer token to that path (0600) instead of stdout, for
    a context less private than a terminal (e.g. a systemd journal)."""
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
