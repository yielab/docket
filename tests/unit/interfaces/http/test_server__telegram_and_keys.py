"""`docket start --telegram` wiring: the poll loop's pacing/backoff discipline.

Pinned here, which the channel/adapter test modules don't reach: `serve.py`'s poll loop
paces itself (no busy-loop on an unconfigured bot or transport error) and never lets an
unexpected exception escape silently -- catch, print, back off, keep going, never a bare
`contextlib.suppress(Exception)`.
"""

from __future__ import annotations

import threading

import pytest

import docket.serve as serve
from docket.interfaces.http import server
from docket.interfaces.telegram import poll

SUBJECT = "docket.interfaces.http.server"

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
    monkeypatch.setattr(poll, "_TELEGRAM_UNCONFIGURED_BACKOFF_S", 0, raising=True)
    monkeypatch.setattr(poll, "_TELEGRAM_ERROR_BACKOFF_S", 0, raising=True)


# ── run_serve(telegram=...) actually starts (or doesn't start) the loop ─────


class TestRunServeTelegramFlag:
    def test_telegram_true_starts_the_poll_thread(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(server, "_run_sweeps", lambda *_a: None)
        monkeypatch.setattr(serve._threads, "ContextHTTPServer", _FakeServer)
        monkeypatch.setenv("DOCKET_SERVE_TOKEN", "test-token")

        started = threading.Event()
        monkeypatch.setattr(poll, "_telegram_poll_loop", lambda stop: started.set(), raising=True)

        server.run_serve(port=0, interval=30, telegram=True)
        assert started.wait(timeout=2), "telegram=True must start the poll loop thread"

    def test_telegram_false_never_starts_the_poll_thread(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(server, "_run_sweeps", lambda *_a: None)
        monkeypatch.setattr(serve._threads, "ContextHTTPServer", _FakeServer)
        monkeypatch.setenv("DOCKET_SERVE_TOKEN", "test-token")

        started = threading.Event()
        monkeypatch.setattr(poll, "_telegram_poll_loop", lambda stop: started.set(), raising=True)

        server.run_serve(port=0, interval=30, telegram=False)
        assert not started.wait(timeout=0.5)

    def test_telegram_true_prints_a_banner_flag(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setattr(server, "_run_sweeps", lambda *_a: None)
        monkeypatch.setattr(serve._threads, "ContextHTTPServer", _FakeServer)
        monkeypatch.setattr(poll, "_telegram_poll_loop", lambda stop: None, raising=True)
        monkeypatch.setenv("DOCKET_SERVE_TOKEN", "test-token")

        server.run_serve(port=0, interval=30, telegram=True)
        out = capsys.readouterr().out
        assert "telegram=on" in out
