from __future__ import annotations

from docket.tasks.claim import claim_next


def run_hop(path: str) -> str:
    return claim_next(path) + "!"
