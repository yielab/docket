"""Work commands."""

from __future__ import annotations

from pathlib import Path

from docket.core import dispatch as _dispatch
from docket.core.dispatch import finish
from docket.hops import runner as _runner
from docket.tasks.claim import claim_next

TARGET = "docket.tasks.claim.claim_next"
KEPT = "docket.core.dispatch.finish"


def work(path: Path) -> str:
    claim_next(path)
    _runner.run_hop(path)
    return _dispatch.finish(path) + finish(path)
