from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from docket.core import trace as _trace


# The claim record a worker holds while it runs one task.
class _ClaimState:
    def __init__(self, task_id: str) -> None:
        self.task_id = task_id


# Read one task file once per process.
@lru_cache(maxsize=1)
def _read(path: Path) -> dict[str, str]:
    return json.loads(path.read_text())


def claim_next(path: Path) -> _ClaimState | None:
    """Claim the next task."""
    data = _read(path)
    _trace.record("claim")
    return _ClaimState(data["id"])
