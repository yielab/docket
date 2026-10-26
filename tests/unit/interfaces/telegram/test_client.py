"""The Telegram Bot API adapter's refusals, and the poller's survival of a raising update.

``interfaces/telegram/client.py`` is the only module that knows the Bot API's wire format; the
wire-level tests are in tests/integration/interfaces/telegram/test_client__wire.py. **No test
contacts the real Telegram API or needs a token.**
"""

from __future__ import annotations

from pathlib import Path

import pytest

from docket.interfaces.telegram import client as _tg
from docket.kernel.home import Home, use_home

SUBJECT = "docket.interfaces.telegram.client"

_FAKE_TOKEN = "123456:AAFAKE-TEST-TOKEN-not-real-do-not-flag"


class TestGetUpdatesHappyPath:
    def test_no_token_is_refused_before_any_request(self) -> None:
        result = _tg.get_updates("", offset=0)
        assert not result.ok
        assert "no bot token" in result.error


class TestSendMessage:
    def test_empty_chat_id_is_refused_before_any_request(self) -> None:
        assert _tg.send_message(_FAKE_TOKEN, "", "hello") is False

    def test_empty_token_is_refused_before_any_request(self) -> None:
        assert _tg.send_message("", "-100123", "hello") is False


class TestPoisonUpdateDoesNotWedgeThePoller:
    """One update whose handling raises must be skipped and audited; the offset still advances
    past the whole batch, so the next poll does not replay it forever."""

    def test_offset_advances_past_a_raising_update(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:

        from docket.governance import audit as _audit
        from docket.interfaces.telegram import bot as _core_tg
        from docket.interfaces.telegram.client import GetUpdatesResult, TelegramUpdate

        with use_home(Home(tmp_path / "home")):
            monkeypatch.setattr(_core_tg, "load_token", lambda: "123:token")
            updates = (
                TelegramUpdate(update_id=50, chat_id="1", user_id="1", text="/status"),
                TelegramUpdate(update_id=51, chat_id="1", user_id="1", text="/status"),
            )
            seen: list[int] = []

            def _handle(
                msg: _core_tg.InboundMessage, **_kwargs: object
            ) -> _core_tg.TelegramActionResult:
                seen.append(msg.update_id)
                if msg.update_id == 50:
                    raise RuntimeError("poison")
                return _core_tg.TelegramActionResult(
                    ok=True, reply="ok", authorized=True, action="status"
                )

            monkeypatch.setattr(_core_tg, "handle_message", _handle)
            sent: list[str] = []
            summary = _core_tg.poll_once(
                get_updates=lambda *a, **k: GetUpdatesResult(ok=True, updates=updates),
                send_message=lambda token, chat_id, text: sent.append(text) or True,
            )
            assert summary.ok
            assert seen == [50, 51]
            assert _core_tg._load_offset() == 52
            assert sent == ["ok"]
            actions = [e.get("action") for e in _audit.read_audit()]
            assert "telegram.update_failed" in actions
