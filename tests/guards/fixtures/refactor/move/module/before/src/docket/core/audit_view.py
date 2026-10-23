"""A view over the trace, importing its siblings by relative name."""

from __future__ import annotations

from .audit import log
from .trace import EVENTS


def note() -> int:
    log("view")
    return len(EVENTS)
