"""Work commands."""

from __future__ import annotations

from pathlib import Path

from docket.core import dispatch as _dispatch
from docket.core.dispatch import claim_next, finish

TARGET = "docket.core.dispatch.claim_next"
KEPT = "docket.core.dispatch.finish"


def work(path: Path) -> str:
    claim_next(path)
    _dispatch.run_hop(path)
    return _dispatch.finish(path) + finish(path)
