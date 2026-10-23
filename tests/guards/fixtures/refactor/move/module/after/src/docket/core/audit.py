"""Audit entries."""

from __future__ import annotations

from docket.observe import trace as _trace
from docket.observe.trace import record


def log(entry: str) -> None:
    record(entry)
    _trace.EVENTS.append(entry)
