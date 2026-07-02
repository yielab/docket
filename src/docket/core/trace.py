"""Durable per-session JSONL trace store.

All agent actions docket can observe are appended to::

    $TRACES_DIR/<project>/<session_id>.jsonl

One file per session → atomic vs concurrent sessions. Disable all trace writes
with ``DOCKET_NO_TRACE=1``.

Exempt from the store.py single-writer rule (D-12, ROADMAP §6): appends are
line-independent, not a read-modify-write of a whole document, so this module
writes JSONL directly rather than through ``edges/store.py``. The ingestion
bridge reads daemon session JSONL under
``$OPENCLAW_DIR/agents/<project>/sessions`` — opaque turn-data, not an openclaw
config file.
"""

from __future__ import annotations

import contextlib
import datetime as _dt
import json
import os
import re
from pathlib import Path
from typing import Any

import docket.config as _cfg

EVENT_TYPES: frozenset[str] = frozenset(
    [
        "session_start",
        "tool_call",
        "tool_result",
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
        r"(?:ANTHROPIC|OPENAI|GOOGLE|OPENROUTER|COHERE)[_A-Z]*[=:\s]+[A-Za-z0-9/_\-+.]{20,}",
        re.IGNORECASE,
    ),
    re.compile(r"[A-Z][A-Z0-9_]{5,}_(?:API_KEY|SECRET|TOKEN|KEY)\s*[=:]\s*\S+", re.IGNORECASE),
    re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", re.IGNORECASE),
)


def _now_iso() -> str:
    return _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _stored_secret_values() -> list[str]:
    """Stored secret values longer than 8 chars (redact.sh's >8 filter).

    Best-effort: reads through the OpenClaw ACL (local import avoids a cycle) and
    returns [] on any error, so redaction never fails a trace write.
    """
    try:
        from docket.edges.adapters import openclaw as _oc

        return [v for v in (s.strip() for s in _oc.secrets_values()) if len(v) > 8]
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
) -> bool:
    """Validate, redact and append one trace event. Returns False when rejected.

    No-ops (returns True) when DOCKET_NO_TRACE=1. payload is parsed as JSON when
    possible, else wrapped as ``{"text": payload}``.
    """
    if os.environ.get("DOCKET_NO_TRACE", "0") == "1":
        return True
    if event_type not in EVENT_TYPES:
        return False

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

    _append(_cfg.TRACES_DIR / project / f"{session_id}.jsonl", [record])
    return True


def trace_ingest(project: str) -> None:
    """Idempotently project daemon session logs into the trace store.

    Reads ``$OPENCLAW_DIR/agents/<project>/sessions/*.jsonl`` and projects each
    turn into tool_call/tool_result events, offset-tracked (.ingest-index.json) to
    avoid double-emit. Synthesises a session_end for timed-out open sessions.
    No-ops when DOCKET_NO_TRACE=1 or the daemon session dir is absent.
    """
    if os.environ.get("DOCKET_NO_TRACE", "0") == "1":
        return
    sessions_dir = _cfg.OPENCLAW_DIR / "agents" / project / "sessions"
    if not sessions_dir.is_dir():
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

    for src in sorted(sessions_dir.glob("*.jsonl")):
        session_id = src.name[: -len(".jsonl")]
        offset = int(index.get(session_id, 0))
        tracefile = project_dir / f"{session_id}.jsonl"

        try:
            all_lines = src.read_text(encoding="utf-8").splitlines(keepends=True)
        except OSError:
            continue

        new_lines = all_lines[offset:]
        if not new_lines:
            continue

        session_start_ts = ""
        with contextlib.suppress(Exception):
            session_start_ts = str(json.loads(all_lines[0]).get("timestamp", ""))

        records: list[dict[str, Any]] = []
        if offset == 0:
            records.append(
                {
                    "ts": session_start_ts or _now_iso(),
                    "project": project,
                    "session_id": session_id,
                    "agent_role": "unknown",
                    "event_type": "session_start",
                    "payload": {"source": "ingested"},
                }
            )

        last_ts: str | None = None
        for line in new_lines:
            line = line.strip()
            if not line:
                continue
            try:
                rec: dict[str, Any] = json.loads(line)
            except json.JSONDecodeError:
                continue

            etype = str(rec.get("type", ""))
            ts = str(rec.get("timestamp", _now_iso()))
            last_ts = ts

            if etype in ("tool_use", "tool_result", "message"):
                if etype == "tool_use":
                    event_type = "tool_call"
                elif etype == "tool_result":
                    event_type = "tool_result"
                else:
                    continue
                records.append(
                    {
                        "ts": ts,
                        "project": project,
                        "session_id": session_id,
                        "agent_role": "unknown",
                        "event_type": event_type,
                        "payload": {
                            "source": "ingested",
                            "daemon_type": etype,
                            "id": rec.get("id"),
                        },
                    }
                )

        _append(tracefile, records)

        index[session_id] = offset + len(new_lines)
        changed = True

        # Synthetic session_end for timed-out open traces.
        if last_ts:
            last_epoch = _epoch_from_iso(last_ts)
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
