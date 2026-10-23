from __future__ import annotations

from pathlib import Path

from docket.tasks.claim import claim_next

QUEUE_LIMIT = 8


def run_hop(path: Path) -> str:
    state = claim_next(path)
    return state.task_id if state else ""
