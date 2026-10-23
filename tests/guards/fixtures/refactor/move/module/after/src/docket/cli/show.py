"""Show the trace."""

from __future__ import annotations

import docket.observe.trace

TARGET = "docket.observe.trace.record"
SOURCE = "src/docket/observe/trace.py"


def show() -> list[str]:
    return docket.observe.trace.EVENTS
