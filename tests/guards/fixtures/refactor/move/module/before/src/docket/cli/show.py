"""Show the trace."""

from __future__ import annotations

import docket.core.trace

TARGET = "docket.core.trace.record"
SOURCE = "src/docket/core/trace.py"


def show() -> list[str]:
    return docket.core.trace.EVENTS
