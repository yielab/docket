"""Dispatch one task."""

from __future__ import annotations

from pathlib import Path

from docket.core import trace as _trace
from docket.tasks.claim import claim_next


def finish(path: Path) -> str:
    state = claim_next(path)
    _trace.record("finish")
    return state.task_id if state else ""
