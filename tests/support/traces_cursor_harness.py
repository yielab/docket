"""Helpers shared by the split halves of one test file."""

from __future__ import annotations

import contextlib
import datetime as _dt
from collections.abc import Iterator
from pathlib import Path

import pytest

from docket.interfaces.http.routes import traces
from docket.interfaces.http.server import _DocketHandler
from docket.kernel.clock import use_clock
from docket.kernel.home import Home, use_home


class _ClockedHandler(_DocketHandler):
    """The test's clock is installed after the server is built, so the request runs under it
    from inside the handler, where the server's own context has already been entered."""

    clock: _FakeClock | None = None

    def handle(self) -> None:
        with use_clock(self.clock) if self.clock is not None else contextlib.nullcontext():
            super().handle()


@pytest.fixture()
def traces_home(tmp_path: Path) -> Iterator[Path]:
    home = tmp_path / ".docket"
    home.mkdir(exist_ok=True)
    with use_home(Home(home)):
        yield home


class _FakeClock:
    """Deterministic stand-in for ``docket.kernel.clock``."""

    # Snapped to a whole second so tick() amounts land on an exact boundary,
    # with no fractional-second guesswork for callers.
    def __init__(self) -> None:
        self._current = _dt.datetime.now(_dt.UTC).replace(microsecond=0)

    def now(self) -> _dt.datetime:
        return self._current

    def monotonic(self) -> float:
        return self._current.timestamp()

    def tick(self, seconds: int | None = None) -> None:
        """Advance the clock -- default closes out the hold-back window."""
        # One second past `serve._TRACE_HOLD_BACK_S`: exactly enough that a
        # write-then-tick()-then-poll always sees the write delivered.
        if seconds is None:
            seconds = traces._TRACE_HOLD_BACK_S + 1
        self._current += _dt.timedelta(seconds=seconds)


@pytest.fixture()
def fake_clock(monkeypatch: pytest.MonkeyPatch) -> Iterator[_FakeClock]:
    clock = _FakeClock()
    monkeypatch.setattr(_ClockedHandler, "clock", clock)
    with use_clock(clock):
        yield clock
