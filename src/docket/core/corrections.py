"""Corrections ledger: deny reasons, REQUEST-CHANGES texts, declined answers."""

from __future__ import annotations

import json as _json
import logging as _logging
import os
from typing import Any

import docket.config as _cfg
from docket.core import trace as _trace

__all__ = ["read", "record"]

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
    from docket.core import dispatch as _dispatch

    ts = _now or _dispatch._now()

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
        path = _cfg.CORRECTIONS_DIR / f"{project}.jsonl"
        is_new = not path.exists()
        path.parent.mkdir(parents=True, exist_ok=True)

        with path.open("a", encoding="utf-8") as f:
            f.write(_json.dumps(record_dict) + "\n")

        if is_new:
            os.chmod(path, 0o600)
    except OSError as e:
        # Never fail the caller on write errors; log instead
        _log.warning(f"Failed to write correction record: {e}")


def read(project: str) -> list[dict[str, Any]]:
    """Read all correction records in append order, or empty list if missing."""
    path = _cfg.CORRECTIONS_DIR / f"{project}.jsonl"
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
                    records.append(_json.loads(line))
                except _json.JSONDecodeError:
                    continue
    except OSError:
        pass

    return records
