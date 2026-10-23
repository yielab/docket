"""A view over the trace, importing its siblings by relative name."""

from __future__ import annotations

from docket.observe.trace import EVENTS

from .audit import log


def note() -> int:
    log("view")
    return len(EVENTS)
