"""Durable per-session JSONL trace store.

All agent actions docket can observe are appended to::

    $TRACES_DIR/<project>/<session_id>.jsonl

One file per session → atomic vs concurrent sessions. Disable all trace writes
with ``DOCKET_NO_TRACE=1``.

Exempt from the store.py single-writer rule: appends are line-independent,
not a read-modify-write of a whole document, so this module writes JSONL
directly rather than through ``edges/store.py``. The ingestion bridge
(``trace_ingest``) projects turns into this store, but reads them only
through the RuntimeDriver port (``edges.adapters.docket_runtime.DocketDriver``);
this module itself has no knowledge of any driver's on-disk session format,
only of its own.
"""

from __future__ import annotations

import contextlib
import datetime as _dt
import json
import os
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import docket.config as _cfg

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
        "session_compaction",
        "request_fit",
        "guardrail_check",
        "guardrail_block",
        "approval_requested",
        "approval_granted",
        "approval_denied",
        "cost_charged",
        "budget_warning",
        "budget_exceeded",
        "drift_alert",
        "verification_failed",
        "tester_verdict_failed",
        "reviewer_verdict_unparseable",
        "rework_started",
        "review_rejected",
        "stale_claim",
        "hop_retry",  # one retryable agent-turn retry attempt, observable history
        "paused_refused",  # a claim refused because the pod's Lead is budget-paused
        "approval_required",  # a require_approval gate fired pre-hop (task -> waiting_approval)
        "approval_resumed",  # a granted approval flipped a waiting task back to pending
        "approval_task_denied",  # a denied approval failed a waiting task terminally
        "run_cancellation_observed",  # execution first observed a persisted run request
        "run_cancelled",  # dispatch fully stopped and terminalized the requested run
        # Generic verdict-gate outcomes for any role/archetype beyond the two
        # built-in ones (which keep emitting their own legacy names above —
        # rework_started/review_rejected/reviewer_verdict_unparseable for
        # reviewer, tester_verdict_failed for tester — see
        # core/dispatch.py's _verdict_event_names).
        "verdict_rework_started",
        "verdict_rejected",
        "verdict_unparseable",
        "error",
        "session_end",
    ]
)

# Secret-shape patterns stripped from payloads before writing.
# Stored secret values are also redacted after the regex pass (see _stored_secret_values).
_REDACT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"(?:sk|pk|api|key|tok|secret|bearer|auth|Basic|Bearer)\s*[=:\s]+[A-Za-z0-9/_\-+.]{20,}",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:ANTHROPIC|OPENAI|GOOGLE|OPENROUTER|AI_GATEWAY|VERCEL|COHERE)"
        r"[_A-Z]*[=:\s]+[A-Za-z0-9/_\-+.]{20,}",
        re.IGNORECASE,
    ),
    re.compile(r"[A-Z][A-Z0-9_]{5,}_(?:API_KEY|SECRET|TOKEN|KEY)\s*[=:]\s*\S+", re.IGNORECASE),
    re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", re.IGNORECASE),
)


def _now_iso() -> str:
    return _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _stored_secret_values() -> list[str]:
    """Stored secret values longer than 8 chars (redact.sh's >8 filter).

    Best-effort: reads docket's own secrets store (``core/secrets.py``) and
    returns [] on any error, so redaction never fails a trace write.
    """
    try:
        from docket.core import secrets as _secrets

        return [v for v in (s.strip() for s in _secrets.secret_values()) if len(v) > 8]
    except Exception:
        return []


def redact(text: str) -> str:
    """Strip secret-shaped substrings from *text*.

    Applies the always-on regex patterns, then redacts the exact VALUES
    of any stored secrets (replaced after the regex pass).
    """
    if not text:
        return text
    for pat in _REDACT_PATTERNS:
        text = pat.sub("[REDACTED]", text)
    for value in _stored_secret_values():
        text = text.replace(value, "[REDACTED]")
    return text


def _epoch_from_iso(ts: str) -> float | None:
    """Parse the leading 'YYYY-MM-DDTHH:MM:SS' of *ts* as a UTC epoch."""
    try:
        dt = _dt.datetime.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S")
    except (ValueError, IndexError):
        return None
    return dt.replace(tzinfo=_dt.UTC).timestamp()


def _append(tracefile: Path, records: list[dict[str, Any]]) -> None:
    """Append records to *tracefile*, chmod 0600 if newly created."""
    if not records:
        return
    is_new = not tracefile.exists()
    tracefile.parent.mkdir(parents=True, exist_ok=True)
    with tracefile.open("a", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    if is_new:
        os.chmod(tracefile, 0o600)


def trace_event(
    project: str,
    session_id: str,
    agent_role: str,
    event_type: str,
    payload: str,
    cost_usd: float | str | None = None,
    duration_ms: int | str | None = None,
) -> TraceStatus:
    """Validate, redact and append one trace event.

    Returns ``"written"`` on a real append, ``"rejected"`` for an unknown
    ``event_type``, or ``"suppressed"`` when DOCKET_NO_TRACE=1 no-ops the
    write — three distinct outcomes a caller can tell apart, so a suppressed
    write can never be mistaken for a real one. payload is parsed as JSON
    when possible, else wrapped as ``{"text": payload}``.
    """
    if _cfg.no_trace():
        return "suppressed"
    if event_type not in EVENT_TYPES:
        return "rejected"

    redacted = redact(payload)
    try:
        payload_obj: Any = json.loads(redacted)
    except json.JSONDecodeError:
        payload_obj = {"text": redacted}

    record: dict[str, Any] = {
        "ts": _now_iso(),
        "project": project,
        "session_id": session_id,
        "agent_role": agent_role,
        "event_type": event_type,
        "payload": payload_obj,
    }
    if cost_usd not in (None, ""):
        with contextlib.suppress(TypeError, ValueError):
            record["cost_usd"] = float(cost_usd)  # type: ignore[arg-type]
    if duration_ms not in (None, ""):
        with contextlib.suppress(TypeError, ValueError):
            record["duration_ms"] = int(duration_ms)  # type: ignore[arg-type]

    # Several step-scoped histories can intentionally emit into one task trace
    # (parallel pipeline children). Keep each in-process JSONL append whole.
    with _TRACE_APPEND_LOCK:
        _append(_cfg.TRACES_DIR / project / f"{session_id}.jsonl", [record])
    return "written"


def trace_ingest(project: str) -> None:
    """Idempotently project the active driver's session logs into the trace store.

    Projects each turn into tool_call/tool_result events, offset-tracked
    (.ingest-index.json) to avoid double-emit. Synthesises a session_end for
    timed-out open sessions. No-ops when DOCKET_NO_TRACE=1 or the driver has no
    sessions for *project*.

    All knowledge of the on-disk session-log format lives behind the
    RuntimeDriver port, not here -- this function only ever sees the
    driver's neutral ``SessionSummary``/``SessionSlice`` shapes and applies
    docket's own trace-event policy (redaction elsewhere, timeout handling,
    event vocabulary) on top. See core/runtime_driver.py.

    Resolves ``edges.adapters.docket_runtime.default_driver()``
    (``DocketDriver``, reading ``core/session.py``'s own storage) -- the same
    driver ``core/dispatch.py``'s hop execution writes turns through, so
    ingestion and hop execution always agree on where a session's turns live.
    """
    if _cfg.no_trace():
        return

    from docket.edges.adapters import docket_runtime as _dr

    driver = _dr.default_driver()
    sessions = driver.list_sessions(project)
    if not sessions:
        return

    project_dir = _cfg.TRACES_DIR / project
    try:
        project_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(project_dir, 0o700)
    except OSError:
        return
    index_file = project_dir / ".ingest-index.json"
    timeout_s = _cfg.SESSION_TIMEOUT

    try:
        index: dict[str, int] = json.loads(index_file.read_text(encoding="utf-8"))
    except Exception:
        index = {}

    now = _dt.datetime.now(_dt.UTC).timestamp()
    changed = False

    for summary in sessions:
        session_id = summary.session_id
        offset = int(index.get(session_id, 0))
        tracefile = project_dir / f"{session_id}.jsonl"

        sl = driver.read_new_turns(project, session_id, offset)
        if not sl.had_new_content:
            continue

        records: list[dict[str, Any]] = []
        if offset == 0:
            records.append(
                {
                    "ts": sl.session_start_ts or _now_iso(),
                    "project": project,
                    "session_id": session_id,
                    "agent_role": "unknown",
                    "event_type": "session_start",
                    "payload": {"source": "ingested"},
                }
            )

        for turn in sl.turns:
            if turn.kind not in ("tool_call", "tool_result"):
                continue
            records.append(
                {
                    "ts": turn.ts,
                    "project": project,
                    "session_id": session_id,
                    "agent_role": "unknown",
                    "event_type": turn.kind,
                    "payload": {
                        "source": "ingested",
                        "daemon_type": turn.daemon_type,
                        "id": turn.record_id,
                    },
                }
            )

        _append(tracefile, records)

        index[session_id] = sl.next_offset
        changed = True

        # Synthetic session_end for timed-out open traces.
        if sl.last_ts:
            last_epoch = _epoch_from_iso(sl.last_ts)
            if (
                last_epoch is not None
                and (now - last_epoch) > timeout_s
                and not _has_session_end(tracefile)
            ):
                _append(tracefile, [_end_record(project, session_id)])

    if changed:
        _write_index(index_file, index)


def _has_session_end(tracefile: Path) -> bool:
    if not tracefile.exists():
        return False
    try:
        for line in tracefile.read_text(encoding="utf-8").splitlines():
            try:
                if json.loads(line).get("event_type") == "session_end":
                    return True
            except json.JSONDecodeError:
                continue
    except OSError:
        return False
    return False


def _end_record(project: str, session_id: str) -> dict[str, Any]:
    return {
        "ts": _now_iso(),
        "project": project,
        "session_id": session_id,
        "agent_role": "unknown",
        "event_type": "session_end",
        "payload": {"status": "aborted", "source": "timeout-sweep"},
    }


def _write_index(index_file: Path, index: dict[str, int]) -> None:
    tmp = index_file.with_suffix(index_file.suffix + ".tmp")
    tmp.write_text(json.dumps(index, indent=2), encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, index_file)


def sweep_all() -> None:
    """Coerce stale open traces to 'aborted' (called by docket serve).

    Appends a synthetic session_end to any trace whose last event is older than
    SESSION_TIMEOUT and has no session_end yet.
    """
    traces_root = _cfg.TRACES_DIR
    if not traces_root.is_dir():
        return
    now = _dt.datetime.now(_dt.UTC).timestamp()

    for tf in traces_root.glob("*/*.jsonl"):
        has_end = False
        last_ts_str: str | None = None
        try:
            for line in tf.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    r: dict[str, Any] = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if r.get("event_type") == "session_end":
                    has_end = True
                last_ts_str = str(r.get("ts") or last_ts_str or "") or last_ts_str
        except OSError:
            continue

        if has_end or last_ts_str is None:
            continue
        last_epoch = _epoch_from_iso(last_ts_str)
        if last_epoch is None or (now - last_epoch) <= _cfg.SESSION_TIMEOUT:
            continue

        try:
            project = tf.relative_to(traces_root).parts[0]
        except ValueError:
            project = "unknown"
        session_id = tf.name[: -len(".jsonl")]
        _append(tf, [_end_record(project, session_id)])


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
    """Result of one ``expire_old_traces`` run -- always returned, never printed.

    ``core/`` never prints; ``cli/_trace.py`` renders this.
    """

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


def _prune_index(project_dir: Path, removed_session_ids: set[str]) -> None:
    """Drop *removed_session_ids* from a project's ``.ingest-index.json``, if present.

    Keeps the ingest offset index consistent with what expiry deleted -- an
    index entry pointing at a deleted trace file is a bug, not a no-op: a
    future ``trace_ingest`` would read a stale offset for a session_id that
    can never be re-created (session_ids are not reused).
    """
    index_file = project_dir / ".ingest-index.json"
    if not index_file.is_file():
        return
    try:
        index: dict[str, int] = json.loads(index_file.read_text(encoding="utf-8"))
    except Exception:
        return
    changed = False
    for sid in removed_session_ids:
        if index.pop(sid, None) is not None:
            changed = True
    if changed:
        _write_index(index_file, index)


def expire_old_traces(
    retention_s: int | None = None,
    dry_run: bool = False,
    project: str | None = None,
) -> TraceExpiryReport:
    """Delete TERMINATED trace files whose last event is older than the retention window.

    Reuses the same liveness reasoning as ``sweep_all``/``_has_session_end``:
    a trace file is eligible for deletion only when it already has a
    ``session_end`` event -- real, or the synthetic ``"aborted"`` one
    ``sweep_all`` appends once a session has been idle past
    ``SESSION_TIMEOUT``. A trace with **no** ``session_end`` is presumed to
    belong to a session that may still be appending to it right now, and is
    always kept regardless of age -- deleting a file a live turn is writing
    to is the one failure mode this function must never produce. Callers
    that want stale-but-open traces to become eligible should run
    ``sweep_all()`` first (``docket serve``'s periodic sweep already does,
    independently of this function).

    *retention_s* defaults to ``config.TRACE_RETENTION_S``. *dry_run* reports
    what would be deleted without deleting anything or touching any index.
    *project* restricts the sweep to one project's trace directory.

    Never touches ``audit.log`` -- audit is out of scope by design (see
    ``core/audit.py``); this function only ever globs ``TRACES_DIR``.
    """
    window = _cfg.TRACE_RETENTION_S if retention_s is None else retention_s
    traces_root = _cfg.TRACES_DIR
    report = TraceExpiryReport(dry_run=dry_run, retention_s=window)
    if not traces_root.is_dir():
        return report

    now = _dt.datetime.now(_dt.UTC).timestamp()
    pattern = f"{project}/*.jsonl" if project else "*/*.jsonl"
    removed_by_dir: dict[Path, set[str]] = {}

    for tf in sorted(traces_root.glob(pattern)):
        report.scanned += 1
        has_end = False
        last_ts_str: str | None = None
        try:
            for line in tf.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    r: dict[str, Any] = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if r.get("event_type") == "session_end":
                    has_end = True
                ts = r.get("ts")
                if ts:
                    last_ts_str = str(ts)
        except OSError:
            continue

        if not has_end:
            report.kept_open += 1
            continue
        last_epoch = _epoch_from_iso(last_ts_str) if last_ts_str else None
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
            removed_by_dir.setdefault(tf.parent, set()).add(session_id)
            report.bytes_reclaimed += size

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

    for pdir, sids in removed_by_dir.items():
        _prune_index(pdir, sids)

    return report


def find_trace(session_id: str) -> Path | None:
    """Return the trace file for *session_id* across all projects, or None."""
    for f in sorted(_cfg.TRACES_DIR.glob(f"*/{session_id}.jsonl")):
        if f.is_file():
            return f
    return None


def read_trace(tracefile: Path) -> list[dict[str, Any]]:
    """Parse every JSON line of *tracefile* in file order; skip malformed lines."""
    out: list[dict[str, Any]] = []
    try:
        text = tracefile.read_text(encoding="utf-8")
    except OSError:
        return out
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def project_trace_dir(project: str) -> Path:
    return _cfg.TRACES_DIR / project


def latest_trace_file(project: str) -> Path | None:
    """Most-recently-modified *.jsonl for *project*, or None."""
    files = list((_cfg.TRACES_DIR / project).glob("*.jsonl"))
    if not files:
        return None
    return max(files, key=lambda p: p.stat().st_mtime)


def export_lines(project: str, since: str = "") -> list[str]:
    """Return raw JSONL lines for *project*, optionally filtered to ts >= *since*.

    Lines are concatenated across session files in sorted filename order;
    a line with an unparseable ts is kept when a since filter is set.
    """
    pdir = _cfg.TRACES_DIR / project
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
                try:
                    ts = str(json.loads(line).get("ts", ""))
                    if ts < since:
                        continue
                except json.JSONDecodeError:
                    pass
            out.append(line)
    return out
