"""`docket serve --telegram` wiring: the poll loop's pacing/backoff discipline.

Pinned here, which the channel/adapter test modules don't reach: `serve.py`'s poll loop
paces itself (no busy-loop on an unconfigured bot or transport error) and never lets an
unexpected exception escape silently -- catch, print, back off, keep going, never a bare
`contextlib.suppress(Exception)`.
"""

from __future__ import annotations

import threading
import time

import pytest

import docket.serve as serve
from docket.core import telegram as _telegram

SUBJECT = "docket.serve"

# ── the poll loop's pacing/backoff discipline ───────────────────────────────


class _FakeServer:
    def __init__(self, *_a: object, **_k: object) -> None:
        pass

    def serve_forever(self) -> None:
        raise KeyboardInterrupt

    def server_close(self) -> None:
        pass


@pytest.fixture(autouse=True)
def _fast_backoffs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(serve, "_TELEGRAM_UNCONFIGURED_BACKOFF_S", 0, raising=True)
    monkeypatch.setattr(serve, "_TELEGRAM_ERROR_BACKOFF_S", 0, raising=True)


def _run_loop_until(stop: threading.Event, n_calls: int, timeout: float = 5.0) -> None:
    t = threading.Thread(target=serve._telegram_poll_loop, args=(stop,), daemon=True)
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


# ── run_serve(telegram=...) actually starts (or doesn't start) the loop ─────


class TestRunServeTelegramFlag:
    def test_telegram_true_starts_the_poll_thread(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(serve, "_run_sweeps", lambda *_a: None)
        monkeypatch.setattr(serve, "ThreadingHTTPServer", _FakeServer)
        monkeypatch.setenv("DOCKET_SERVE_TOKEN", "test-token")

        started = threading.Event()
        monkeypatch.setattr(serve, "_telegram_poll_loop", lambda stop: started.set(), raising=True)

        serve.run_serve(port=0, interval=30, telegram=True)
        assert started.wait(timeout=2), "telegram=True must start the poll loop thread"

    def test_telegram_false_never_starts_the_poll_thread(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(serve, "_run_sweeps", lambda *_a: None)
        monkeypatch.setattr(serve, "ThreadingHTTPServer", _FakeServer)
        monkeypatch.setenv("DOCKET_SERVE_TOKEN", "test-token")

        started = threading.Event()
        monkeypatch.setattr(serve, "_telegram_poll_loop", lambda stop: started.set(), raising=True)

        serve.run_serve(port=0, interval=30, telegram=False)
        assert not started.wait(timeout=0.5)

    def test_telegram_true_prints_a_banner_flag(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setattr(serve, "_run_sweeps", lambda *_a: None)
        monkeypatch.setattr(serve, "ThreadingHTTPServer", _FakeServer)
        monkeypatch.setattr(serve, "_telegram_poll_loop", lambda stop: None, raising=True)
        monkeypatch.setenv("DOCKET_SERVE_TOKEN", "test-token")

        serve.run_serve(port=0, interval=30, telegram=True)
        out = capsys.readouterr().out
        assert "telegram=on" in out
