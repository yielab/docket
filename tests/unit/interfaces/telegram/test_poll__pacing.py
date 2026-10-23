"""`docket start --telegram` wiring: the poll loop's pacing/backoff discipline.

Pinned here, which the channel/adapter test modules don't reach: `interfaces/http/server.py`'s poll loop
paces itself (no busy-loop on an unconfigured bot or transport error) and never lets an
unexpected exception escape silently -- catch, print, back off, keep going, never a bare
`contextlib.suppress(Exception)`.
"""

from __future__ import annotations

import threading
import time

import pytest
from tests.support import llm as _support_llm

from docket.interfaces.telegram import bot as _telegram
from docket.interfaces.telegram import poll
from docket.kernel.threads import new_thread

_fast_backoffs = _support_llm.fast_backoffs

SUBJECT = "docket.interfaces.telegram.poll"


def _run_loop_until(stop: threading.Event, n_calls: int, timeout: float = 5.0) -> None:
    t = new_thread(target=poll._telegram_poll_loop, args=(stop,), daemon=True)
    t.start()
    t.join(timeout=timeout)
    assert not t.is_alive(), f"telegram poll loop did not stop after {n_calls} calls"


class TestPollLoopPacing:
    def test_unconfigured_bot_backs_off_and_stops_cleanly(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        stop = threading.Event()
        calls = 0

        def fake_poll_once() -> _telegram.PollSummary:
            nonlocal calls
            calls += 1
            if calls >= 3:
                stop.set()
            return _telegram.PollSummary(ok=True, configured=False)

        monkeypatch.setattr(_telegram, "poll_once", fake_poll_once, raising=True)
        _run_loop_until(stop, 3)
        assert calls >= 3

    def test_transport_error_backs_off_and_stops_cleanly(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        stop = threading.Event()
        calls = 0

        def fake_poll_once() -> _telegram.PollSummary:
            nonlocal calls
            calls += 1
            if calls >= 3:
                stop.set()
            return _telegram.PollSummary(ok=False, configured=True, error="cannot reach Telegram")

        monkeypatch.setattr(_telegram, "poll_once", fake_poll_once, raising=True)
        _run_loop_until(stop, 3)
        assert calls >= 3

    def test_an_unexpected_exception_is_caught_not_left_to_crash_the_loop(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """No bare `contextlib.suppress(Exception)` around dispatch, but
        also no unhandled exception silently killing the background
        thread -- it must be visible (printed) and the loop must continue."""
        stop = threading.Event()
        calls = 0

        def fake_poll_once() -> _telegram.PollSummary:
            nonlocal calls
            calls += 1
            if calls >= 2:
                stop.set()
                return _telegram.PollSummary(ok=True, configured=False)
            raise RuntimeError("boom - simulated unexpected failure")

        monkeypatch.setattr(_telegram, "poll_once", fake_poll_once, raising=True)
        _run_loop_until(stop, 2)
        assert calls >= 2
        out = capsys.readouterr().out
        assert "poll failed" in out
        assert "boom" in out

    def test_successful_poll_with_messages_loops_again_without_extra_wait(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """On the happy path the loop must not insert its own sleep --
        getUpdates' own long-poll wait already paces it -- proven by many
        iterations completing well inside a tight wall-clock budget."""
        stop = threading.Event()
        calls = 0
        start = time.monotonic()

        def fake_poll_once() -> _telegram.PollSummary:
            nonlocal calls
            calls += 1
            if calls >= 50:
                stop.set()
            return _telegram.PollSummary(ok=True, configured=True, processed=1)

        monkeypatch.setattr(_telegram, "poll_once", fake_poll_once, raising=True)
        _run_loop_until(stop, 50, timeout=5.0)
        elapsed = time.monotonic() - start
        assert calls >= 50
        assert elapsed < 2.0  # would take 50 * backoff seconds if it wrongly slept
