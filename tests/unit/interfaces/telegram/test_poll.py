"""serve — stdlib HTTP server for docket's read API.

These exercise the pure builders (build_status / render_metrics / render_health)
against a seeded fake DOCKET_HOME, plus a live round-trip through the threaded
HTTP server on port 0. The pure-function assertions are the contract guard:
they pin the /status.json JSON keys and the Prometheus metric line names so any
drift is caught.
"""

from __future__ import annotations

import threading
from typing import Any

import pytest

from docket.interfaces.telegram import poll

SUBJECT = "docket.interfaces.telegram.poll"


class TestTelegramHint:
    def test_unconfigured_bot_names_the_command_that_connects_it(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from docket.interfaces.telegram import bot as _telegram

        stop = threading.Event()

        def _unconfigured() -> Any:
            stop.set()
            return _telegram.PollSummary(ok=False, configured=False)

        monkeypatch.setattr(_telegram, "poll_once", _unconfigured)
        poll.telegram_poll_loop(stop)
        assert "docket setup notify enable telegram" in capsys.readouterr().out
