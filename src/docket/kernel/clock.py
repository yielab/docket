"""The one place that reads the time.

Every persisted timestamp is built here, so a test pins the time with ``use_clock`` instead of
patching a private wrapper in each module. Each format below is one that is already written to
disk or to a wire; changing one changes stored data.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, date, datetime
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime:
        """The current moment, timezone-aware, in UTC."""
        ...

    def monotonic(self) -> float:
        """Seconds on a clock that never goes backwards, for measuring durations."""
        ...


class _SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)

    def monotonic(self) -> float:
        return time.monotonic()


_SYSTEM = _SystemClock()
_CURRENT: ContextVar[Clock | None] = ContextVar("docket_clock", default=None)


def _clock() -> Clock:
    return _CURRENT.get() or _SYSTEM


@contextmanager
def use_clock(clock: Clock) -> Iterator[Clock]:
    """Make ``clock`` the clock of this block. Threads need ``contextvars.copy_context``."""
    token = _CURRENT.set(clock)
    try:
        yield clock
    finally:
        _CURRENT.reset(token)


def now() -> datetime:
    return _clock().now()


def monotonic() -> float:
    return _clock().monotonic()


def epoch() -> float:
    return now().timestamp()


def iso() -> str:
    """``2026-10-22T09:30:00.123456+00:00`` -- microseconds and an explicit offset."""
    return now().isoformat()


def stamp() -> str:
    """``2026-10-22T09:30:00Z`` -- whole seconds; sorts as text and parses without a library."""
    return now().strftime("%Y-%m-%dT%H:%M:%SZ")


def stamp_ms() -> str:
    """``2026-10-22T09:30:00.123Z`` -- the audit chain needs milliseconds, truncated not rounded."""
    moment = now()
    return moment.strftime("%Y-%m-%dT%H:%M:%S") + f".{moment.microsecond // 1000:03d}Z"


def today() -> date:
    return now().date()


def today_iso() -> str:
    return today().isoformat()
