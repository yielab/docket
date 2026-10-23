"""Corrections ledger: deny reasons, REQUEST-CHANGES texts, declined answers."""

from __future__ import annotations

import datetime as _dt
import json as _json
import logging as _logging
import os
from typing import Any

from docket.core import trace as _trace
from docket.kernel import clock as _clock
from docket.kernel.errors import InvalidInput
from docket.kernel.home import current_home

__all__ = ["read", "record", "utc_cursor", "utc_z"]

_log = _logging.getLogger(__name__)


def record(
    project: str,
    kind: str,
    *,
    task_id: str,
    role: str,
    text: str,
    source: str,
    _now: str | None = None,
) -> None:
    """Append one correction record. Text is redacted and tail-bounded to 4000 chars."""

    ts = _now or _clock.iso()

    # Redact sensitive text
    redacted_text = _trace.redact(text)

    # Tail-bound to 4000 chars
    if len(redacted_text) > 4000:
        redacted_text = redacted_text[-4000:]

    record_dict: dict[str, Any] = {
        "ts": ts,
        "project": project,
        "kind": kind,
        "taskId": task_id,
        "role": role,
        "text": redacted_text,
        "source": source,
    }

    # Append to JSONL file (direct, no atomic wrapper)
    try:
        path = current_home().corrections_dir / f"{project}.jsonl"
        is_new = not path.exists()
        path.parent.mkdir(parents=True, exist_ok=True)

        with path.open("a", encoding="utf-8") as f:
            f.write(_json.dumps(record_dict) + "\n")

        if is_new:
            os.chmod(path, 0o600)
    except OSError as e:
        # Never fail the caller on write errors; log instead
        _log.warning(f"Failed to write correction record: {e}")


def utc_cursor(ts: str) -> str:
    """*ts* as the ledger writes it (UTC `isoformat()`); ValueError unless it carries an offset."""
    stamp = _dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        raise InvalidInput(f"naive timestamp: {ts}")
    return stamp.astimezone(_dt.UTC).isoformat()


def utc_z(ts: str) -> str:
    """*ts* as UTC with a `Z` suffix; *ts* unchanged when it does not parse (\"\" stays \"\")."""
    try:
        return utc_cursor(ts).replace("+00:00", "Z")
    except ValueError:
        return ts


def read(project: str, since: str = "") -> list[dict[str, Any]]:
    """Correction records in append order, keeping `ts > since`; both sides must be in the
    ledger's UTC `isoformat()` form (see `utc_cursor`), or the string compare is wrong."""
    path = current_home().corrections_dir / f"{project}.jsonl"
    if not path.exists():
        return []

    records: list[dict[str, Any]] = []
    try:
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = _json.loads(line)
                except _json.JSONDecodeError:
                    continue
                if not since or str(rec.get("ts", "")) > since:
                    records.append(rec)
    except OSError:
        pass

    return records
