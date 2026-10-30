"""Durable per-session JSONL trace store.

All agent actions docket can observe are appended to::

    $TRACES_DIR/<project>/<session_id>.jsonl

One file per session → atomic vs concurrent sessions. Disable all trace writes
with ``DOCKET_NO_TRACE=1``.

Exempt from the store.py single-writer rule: appends are line-independent,
not a read-modify-write of a whole document, so this module writes JSONL
directly rather than through ``platform/store.py``.
"""

from __future__ import annotations

import contextlib
import json
import os
import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from docket.governance.secrets import redact
from docket.kernel import clock as _clock
from docket.kernel.home import current_home
from docket.kernel.ports import process as _process
from docket.platform import mkdir_private

# A sink receives the exact record trace_event is about to append (after
# redaction, before the write) -- see subscribe() below.
TraceSink = Callable[[dict[str, Any]], None]

_SUBSCRIBERS: list[TraceSink] = []
_SUBSCRIBERS_LOCK = threading.Lock()

# trace_event()'s return contract: "written" (recorded), "rejected" (invalid
# event_type), or "suppressed" (DOCKET_NO_TRACE=1 no-ops the write) — three
# distinct outcomes, so a suppressed write can never be mistaken for a real
# one. Callers that only care about success can still do
# `trace_event(...) == "written"`.
TraceStatus = Literal["written", "rejected", "suppressed"]

_TRACE_APPEND_LOCK = threading.Lock()

EVENT_TYPES: frozenset[str] = frozenset(
    [
        "session_start",
        "tool_call",
        "tool_result",
        "context_composed",
        "prompt_composed",
        "session_compaction",
        "request_fit",
        "guardrail_check",
        "guardrail_block",
        "approval_granted",
        "approval_denied",
        "cost_charged",
        "budget_warning",
        "budget_exceeded",
        "verification_failed",
        "tester_verdict_failed",
        "reviewer_verdict_unparseable",
        "rework_started",
        "review_rejected",
        "stale_claim",
        "dispatch_refused",  # a claimed task failed deterministically before or between hops
        "hop_retry",  # one retryable agent-turn retry attempt, observable history
        "paused_refused",  # a claim refused because the pod's Lead is budget-paused
        "approval_required",  # a require_approval gate fired pre-hop (task -> waiting_approval)
        "approval_resumed",  # a granted approval flipped a waiting task back to pending
        "approval_task_denied",  # a denied approval failed a waiting task terminally
        "approval_unused",  # a hop ended ok without issuing the call a person approved for it
        "run_cancellation_observed",  # execution first observed a persisted run request
        "run_cancelled",  # dispatch fully stopped and terminalized the requested run
        # Generic verdict-gate outcomes for any role/archetype beyond the two
        # built-in ones (which keep emitting their own names above —
        # rework_started/review_rejected/reviewer_verdict_unparseable for
        # reviewer, tester_verdict_failed for tester — see
        # tasks/application/record.py's _verdict_event_names).
        "verdict_rework_started",
        "verdict_rejected",
        "verdict_unparseable",
        "verdict_reasked",  # a verdict-gated reply had no marker; one more request was sent
        "step_skipped",  # a `when` predicate was false; the step advanced with no hop
        "command_step",  # a `run` (command) step executed, with its exit code
        "route_taken",  # a step's own `on:` map resolved a gate outcome (pipeline-format.spec.md)
        # One pause, one payload (kernel/escalation_events.py): asked at the opening, delivered to
        # a person by a channel, then settled as resolved, expired or decided.
        "escalation_asked",
        "escalation_delivered",
        "escalation_resolved",
        "escalation_expired",
        "escalation_decided",
        "llm_call",  # one backend chat-completions exchange: model, tokens, latency
        "hop_started",  # a pod-dispatch hop began: step, member, model, provider, cycle
        "hop_finished",  # ...and ended: ok, verdict, gate, usage, durationMs
        "memory_update",  # a pod-memory entry was recorded, decided, reverted or reset
        "prepare",  # a claimed task's worktree was prepared: command, source, cacheHit, exit
        "process_started",  # a tool handler's real OS process group started
        "process_exited",  # ...and its matching exit, with exitCode or signal
        "error",
        "session_end",
    ]
)


def _redact_value(value: Any) -> Any:
    """Redact every string in a parsed JSON value, leaving its structure intact."""
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        return {k: _redact_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact_value(v) for v in value]
    return value


def _append(tracefile: Path, records: list[dict[str, Any]]) -> None:
    """Append records to *tracefile*, chmod 0600 if newly created."""
    if not records:
        return
    is_new = not tracefile.exists()
    mkdir_private(tracefile.parent)
    with tracefile.open("a", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    if is_new:
        os.chmod(tracefile, 0o600)


def _parse_record(line: str) -> dict[str, Any] | None:
    """The JSON object on *line*, or None when it is blank, malformed or not an object."""
    line = line.strip()
    if not line:
        return None
    try:
        parsed = json.loads(line)
    except (json.JSONDecodeError, RecursionError):
        return None
    return parsed if isinstance(parsed, dict) else None


# Same list, same lock, same semantics as subscribe() below (now expressed over this, byte for
# byte the same behaviour): a raising sink is suppressed (mirrors _emit_trace's best-effort rule
# in governance/approval.py) and never changes trace_event's return value; the returned callable
# removes exactly the one instance added even if subscribed twice. Built for a long-lived
# subscriber (observability/telemetry.py's export pipeline) that has no single `with` block to own.
def add_subscriber(sink: TraceSink) -> Callable[[], None]:
    """Non-context-manager form of ``subscribe``: register *sink* and return a callable that
    unregisters it."""
    with _SUBSCRIBERS_LOCK:
        _SUBSCRIBERS.append(sink)

    def _unsubscribe() -> None:
        with _SUBSCRIBERS_LOCK:
            _SUBSCRIBERS.remove(sink)

    return _unsubscribe


@contextlib.contextmanager
def subscribe(sink: TraceSink) -> Iterator[None]:
    """Receive every record ``trace_event`` appends, for as long as this is open."""
    unsubscribe = add_subscriber(sink)
    try:
        yield
    finally:
        unsubscribe()


def _notify_subscribers(record: dict[str, Any]) -> None:
    with _SUBSCRIBERS_LOCK:
        sinks = list(_SUBSCRIBERS)
    for sink in sinks:
        with contextlib.suppress(Exception):
            sink(record)


def trace_event(
    project: str,
    session_id: str,
    agent_role: str,
    event_type: str,
    payload: str,
    cost_usd: float | str | None = None,
    duration_ms: int | str | None = None,
    *,
    task_id: str = "",
) -> TraceStatus:
    """Validate, redact and append one trace event. Returns ``"written"`` on
    a real append, ``"rejected"`` for an unknown ``event_type``, or
    ``"suppressed"`` under DOCKET_NO_TRACE=1 -- three outcomes a caller can
    tell apart, so a suppressed write is never mistaken for a real one.
    payload is parsed as JSON when possible, else wrapped as ``{"text": ...}``."""
    if _process.no_trace():
        return "suppressed"
    if event_type not in EVENT_TYPES:
        return "rejected"

    try:
        payload_obj: Any = _redact_value(json.loads(payload))
    except json.JSONDecodeError:
        payload_obj = {"text": redact(payload)}

    record: dict[str, Any] = {
        "ts": _clock.stamp(),
        "project": project,
        "session_id": session_id,
        "agent_role": agent_role,
        "event_type": event_type,
    }
    if task_id:
        record["task_id"] = task_id
    record["payload"] = payload_obj
    if cost_usd not in (None, ""):
        with contextlib.suppress(TypeError, ValueError):
            record["cost_usd"] = float(cost_usd)  # type: ignore[arg-type]
    if duration_ms not in (None, ""):
        with contextlib.suppress(TypeError, ValueError):
            record["duration_ms"] = int(duration_ms)  # type: ignore[arg-type]

    if _SUBSCRIBERS:
        _notify_subscribers(record)

    # Several step-scoped histories can intentionally emit into one task trace
    # (parallel pipeline children). Keep each in-process JSONL append whole.
    with _TRACE_APPEND_LOCK:
        _append(current_home().traces_dir / project / f"{session_id}.jsonl", [record])
    return "written"


def _end_record(project: str, session_id: str) -> dict[str, Any]:
    return {
        "ts": _clock.stamp(),
        "project": project,
        "session_id": session_id,
        "agent_role": "unknown",
        "event_type": "session_end",
        "payload": {"status": "aborted", "source": "timeout-sweep"},
    }


def sweep_all() -> None:
    """Append a synthetic 'aborted' session_end, after notifying subscribers, to every trace
    older than SESSION_TIMEOUT that has none (called by docket start).
    No-ops under DOCKET_NO_TRACE=1."""
    if _process.no_trace():
        return
    traces_root = current_home().traces_dir
    if not traces_root.is_dir():
        return
    now = _clock.epoch()

    for tf in traces_root.glob("*/*.jsonl"):
        has_end = False
        last_ts_str: str | None = None
        try:
            for line in tf.read_text(encoding="utf-8").splitlines():
                r = _parse_record(line)
                if r is None:
                    continue
                if r.get("event_type") == "session_end":
                    has_end = True
                last_ts_str = str(r.get("ts") or last_ts_str or "") or last_ts_str
        except OSError:
            continue

        if has_end or last_ts_str is None:
            continue
        last_epoch = _clock.parse_epoch(last_ts_str)
        if last_epoch is None or (now - last_epoch) <= current_home().session_timeout:
            continue

        try:
            project = tf.relative_to(traces_root).parts[0]
        except ValueError:
            project = "unknown"
        session_id = tf.name[: -len(".jsonl")]
        end_record = _end_record(project, session_id)
        _notify_subscribers(end_record)
        with _TRACE_APPEND_LOCK:
            _append(tf, [end_record])


@dataclass
class ExpiredTrace:
    """One trace file the retention sweep deleted (or would delete, dry-run)."""

    project: str
    session_id: str
    path: Path
    last_event_ts: str
    age_days: float
    bytes: int


@dataclass
class TraceExpiryReport:
    """Result of one ``expire_old_traces`` run -- always returned, never
    printed; application code never prints, ``interfaces/cli/commands/task.py`` renders this."""

    dry_run: bool
    retention_s: int
    scanned: int = 0
    expired: list[ExpiredTrace] = field(default_factory=list)
    kept_open: int = 0
    kept_recent: int = 0
    bytes_reclaimed: int = 0

    @property
    def expired_count(self) -> int:
        return len(self.expired)


def _remove_artifacts(paths: set[str]) -> int:
    """Delete the stored tool results a deleted trace named, only files directly inside a pod's
    ``cache/artifacts`` directory; the bytes freed."""
    pods = current_home().pods_dir.resolve()
    freed = 0
    for raw in paths:
        path = Path(raw)
        try:
            resolved = path.resolve()
            inside = resolved.parent.name == "artifacts" and pods in resolved.parents
            if not inside or not path.is_file() or path.is_symlink():
                continue
            size = path.stat().st_size
            path.unlink()
            freed += size
        except OSError:
            continue
    return freed


def expire_old_traces(
    retention_s: int | None = None,
    dry_run: bool = False,
    project: str | None = None,
) -> TraceExpiryReport:
    """Delete TERMINATED trace files whose last event is older than the
    retention window. Eligible only when a trace already has a
    ``session_end`` (real, or the synthetic ``"aborted"`` one ``sweep_all``
    appends past ``SESSION_TIMEOUT``); a trace with no ``session_end`` is
    always kept regardless of age -- deleting a file a live turn is writing
    to is the one failure mode this function must never produce. Run
    ``sweep_all()`` first to make stale-but-open traces eligible (``docket
    serve``'s periodic sweep already does).

    *retention_s* defaults to ``Home.trace_retention_s``; *dry_run*
    reports without deleting or touching any index; *project* restricts the
    sweep to one project. Never touches ``audit.log`` -- out of scope by
    design (see ``governance/audit.py``); only ever globs ``TRACES_DIR``.
    """
    window = current_home().trace_retention_s if retention_s is None else retention_s
    traces_root = current_home().traces_dir
    report = TraceExpiryReport(dry_run=dry_run, retention_s=window)
    if not traces_root.is_dir():
        return report

    now = _clock.epoch()
    pattern = f"{project}/*.jsonl" if project else "*/*.jsonl"

    for tf in sorted(traces_root.glob(pattern)):
        report.scanned += 1
        artifacts: set[str] = set()
        has_end = False
        last_ts_str: str | None = None
        try:
            for line in tf.read_text(encoding="utf-8").splitlines():
                r = _parse_record(line)
                if r is None:
                    continue
                if r.get("event_type") == "session_end":
                    has_end = True
                payload = r.get("payload")
                if isinstance(payload, dict) and isinstance(payload.get("artifact"), str):
                    artifacts.add(payload["artifact"])
                ts = r.get("ts")
                if ts:
                    last_ts_str = str(ts)
        except OSError:
            continue

        if not has_end:
            report.kept_open += 1
            continue
        last_epoch = _clock.parse_epoch(last_ts_str) if last_ts_str else None
        if last_epoch is None:
            # Terminated but no parseable timestamp anywhere -- can't judge
            # age, so keep it rather than guess.
            report.kept_open += 1
            continue
        age_s = now - last_epoch
        if age_s <= window:
            report.kept_recent += 1
            continue
        assert last_ts_str is not None  # last_epoch above is only set from a real last_ts_str

        try:
            proj = tf.relative_to(traces_root).parts[0]
        except ValueError:
            proj = "unknown"
        session_id = tf.name[: -len(".jsonl")]
        try:
            size = tf.stat().st_size
        except OSError:
            size = 0

        if not dry_run:
            try:
                tf.unlink()
            except OSError:
                continue
            report.bytes_reclaimed += size + _remove_artifacts(artifacts)

        report.expired.append(
            ExpiredTrace(
                project=proj,
                session_id=session_id,
                path=tf,
                last_event_ts=last_ts_str,
                age_days=age_s / 86400.0,
                bytes=size,
            )
        )

    return report


def find_trace(session_id: str) -> Path | None:
    """Return the trace file for *session_id* across all projects, or None."""
    for f in sorted(current_home().traces_dir.glob(f"*/{session_id}.jsonl")):
        if f.is_file():
            return f
    return None


def first_ts(project: str, session_id: str) -> str | None:
    """The ``ts`` of the first record in *session_id*'s trace under *project*, else None."""
    try:
        with (current_home().traces_dir / project / f"{session_id}.jsonl").open(
            encoding="utf-8"
        ) as handle:
            for line in handle:
                record = _parse_record(line)
                if record is not None:
                    return str(record.get("ts") or "") or None
    except OSError:
        return None
    return None


def read_trace(tracefile: Path) -> list[dict[str, Any]]:
    """Parse every JSON object line of *tracefile* in file order; skip blank, malformed and
    non-object lines."""
    out: list[dict[str, Any]] = []
    try:
        text = tracefile.read_text(encoding="utf-8")
    except OSError:
        return out
    for line in text.splitlines():
        record = _parse_record(line)
        if record is not None:
            out.append(record)
    return out


def project_trace_dir(project: str) -> Path:
    return current_home().traces_dir / project


def export_lines(project: str, since: str = "") -> list[str]:
    """Raw JSONL lines of *project* in sorted filename order, filtered to ts >= *since* when
    given; a line with no parseable ts, or that is not a JSON object, is kept."""
    pdir = current_home().traces_dir / project
    out: list[str] = []
    for tf in sorted(pdir.glob("*.jsonl")):
        try:
            text = tf.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            if since:
                record = _parse_record(line)
                if record is not None and str(record.get("ts", "")) < since:
                    continue
            out.append(line)
    return out


#: A dispatch writes the task's own status on ``session_end``. ``None`` = not terminal.
_TERMINAL_OUTCOME: dict[str, str] = {
    "done": "success",
    "success": "success",
    "failed": "failure",
    "failure": "failure",
    "cancelled": "aborted",
    "blocked": "aborted",
    "aborted": "aborted",
}


@dataclass(frozen=True)
class TerminalOutcomes:
    """Counts of a pod's finished sessions and how long they took."""

    success: int = 0
    failure: int = 0
    aborted: int = 0
    durations_ms: tuple[int, ...] = ()

    @property
    def total(self) -> int:
        return self.success + self.failure + self.aborted

    @property
    def mean_ms(self) -> int | None:
        return round(sum(self.durations_ms) / len(self.durations_ms)) if self.durations_ms else None

    @property
    def p95_ms(self) -> int | None:
        if not self.durations_ms:
            return None
        return sorted(self.durations_ms)[int(len(self.durations_ms) * 0.95)]


def terminal_outcomes(project: str, *, window: int) -> TerminalOutcomes:
    """Count the *window* sessions of *project* whose ``session_end`` ts is latest.

    Open sessions and parked tasks (``waiting_*``) are not terminal and are skipped."""
    sessions: list[tuple[str, str, int | None]] = []
    for tf in sorted(project_trace_dir(project).glob("*.jsonl")):
        start_ts = end_ts = outcome = None
        for rec in read_trace(tf):
            etype = rec.get("event_type")
            if etype == "session_start":
                start_ts = str(rec.get("ts") or "")
            elif etype == "session_end":
                payload = rec.get("payload")
                raw = str(payload.get("status", "success")) if isinstance(payload, dict) else ""
                outcome = _TERMINAL_OUTCOME.get(raw)
                end_ts = str(rec.get("ts") or "")
        if outcome is None:
            continue
        duration: int | None = None
        started, ended = _clock.parse_epoch(start_ts), _clock.parse_epoch(end_ts)
        if started is not None and ended is not None:
            duration = int((ended - started) * 1000)
        sessions.append((end_ts or "", outcome, duration))
    sessions.sort(key=lambda s: s[0])
    recent = sessions[-window:] if window > 0 else sessions
    return TerminalOutcomes(
        success=sum(1 for _, o, _ in recent if o == "success"),
        failure=sum(1 for _, o, _ in recent if o == "failure"),
        aborted=sum(1 for _, o, _ in recent if o == "aborted"),
        durations_ms=tuple(d for _, _, d in recent if d is not None),
    )
