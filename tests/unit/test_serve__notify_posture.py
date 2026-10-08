"""`docket start --dispatch` says once, at startup, when no channel delivers beyond the console
(operator-loop.spec.md Notifications 17): an unattended sweep parks tasks nobody would hear about.
"""

from __future__ import annotations

import pytest

from docket import serve
from docket.core import channel as _channel

SUBJECT = "docket.serve"


class _FakeServer:
    def __init__(self, *_a: object, **_k: object) -> None:
        pass

    def serve_forever(self) -> None:
        raise KeyboardInterrupt

    def server_close(self) -> None:
        pass


def _run(monkeypatch: pytest.MonkeyPatch, *, dispatch: bool) -> None:
    monkeypatch.setattr(serve, "_run_sweeps", lambda *_a: None)
    monkeypatch.setattr(serve, "ThreadingHTTPServer", _FakeServer)
    monkeypatch.setenv("DOCKET_SERVE_TOKEN", "test-token")
    serve.run_serve(port=0, interval=30, dispatch=dispatch)


def test_dispatch_with_only_console_warns_at_startup(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _run(monkeypatch, dispatch=True)
    out = capsys.readouterr().out
    assert "docket setup notify enable desktop" in out
    assert "docket inbox" in out


def test_dispatch_with_a_delivering_channel_is_quiet(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _channel.enable_channel("desktop")
    _run(monkeypatch, dispatch=True)
    out = capsys.readouterr().out
    assert "dispatch=on" in out
    assert "docket setup notify enable" not in out


def test_read_only_serve_never_warns(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _run(monkeypatch, dispatch=False)
    assert "docket setup notify enable" not in capsys.readouterr().out
