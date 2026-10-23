"""Dispatch one task."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from docket.core import trace as _trace

QUEUE_LIMIT = 8


# Read one task file once per process.
@lru_cache(maxsize=1)
def _read(path: Path) -> dict[str, str]:
    return json.loads(path.read_text())


# The claim record a worker holds while it runs one task.
class _ClaimState:
    def __init__(self, task_id: str) -> None:
        self.task_id = task_id


def claim_next(path: Path) -> _ClaimState | None:
    """Claim the next task."""
    data = _read(path)
    _trace.record("claim")
    return _ClaimState(data["id"])


def run_hop(path: Path) -> str:
    state = claim_next(path)
    return state.task_id if state else ""


def finish(path: Path) -> str:
    state = claim_next(path)
    _trace.record("finish")
    return state.task_id if state else ""
