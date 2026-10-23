"""Audit entries."""

from __future__ import annotations

from docket.core import trace as _trace
from docket.core.trace import record


def log(entry: str) -> None:
    record(entry)
    _trace.EVENTS.append(entry)
