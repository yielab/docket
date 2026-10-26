"""The Telegram bot's token, enqueue entry point, request timeout and wire discovery."""

from __future__ import annotations

import ast
import dataclasses
import json
from pathlib import Path

from tests.support.fakes import FakeProcess

from docket.governance import secrets as _secrets
from docket.interfaces.telegram import bot as _tg
from docket.interfaces.telegram.client import TelegramUpdate
from docket.kernel.home import current_home, use_home

SUBJECT = "docket.interfaces.telegram.bot"


def _fake_get_updates_capturing(
    calls: list[dict[str, object]],
) -> _tg.GetUpdatesFn:
    def _fake(
        token: str, *, offset: int = 0, timeout: int = 25, request_timeout: float = 35
    ) -> _tg.GetUpdatesResult:
        calls.append({"offset": offset, "timeout": timeout, "request_timeout": request_timeout})
        return _tg.GetUpdatesResult(True, updates=())

    return _fake


class TestTokenNeverTouchedHere:
    def test_handle_message_never_imports_a_real_network_call(self) -> None:
        """`handle_message` (unlike `poll_once`) takes no token and performs
        no I/O to Telegram at all -- structurally, there is nothing for a
        bot-token secret to leak through in this code path."""
        import inspect

        src = inspect.getsource(_tg.handle_message)
        assert "token" not in src.lower()


class TestTheBotReadsItsTokenThroughTheSecretsBackend:
    def test_a_keyring_stored_token_reaches_get_updates(self, fake_process: FakeProcess) -> None:
        fake_process.env["DOCKET_SECRETS_BACKEND"] = "keyring"
        fake_process.binaries = {"secret-tool"}
        fake_process.secret_tool_store(
            current_home().keyring_service, "TELEGRAM_BOT_TOKEN", "999:from-keyring"
        )
        _secrets.save_secrets({"TELEGRAM_BOT_TOKEN": ""})  # the keyring backend's index entry

        seen: list[str] = []

        def _get_updates(token: str, **_kw: object) -> _tg.GetUpdatesResult:
            seen.append(token)
            return _tg.GetUpdatesResult(True, updates=())

        summary = _tg.poll_once(get_updates=_get_updates, send_message=lambda *a, **k: True)

        assert summary.configured
        assert seen == ["999:from-keyring"]
        assert _tg.wire_discovery_configured()


class TestOneEnqueueEntryPoint:
    def test_telegram_and_the_mcp_tools_call_enqueue_task_once(self) -> None:
        from docket.interfaces.cli.commands import mcp as _mcp

        for module in (_tg, _mcp):
            tree = ast.parse(Path(module.__file__ or "").read_text(encoding="utf-8"))
            called = {
                node.func.attr
                for node in ast.walk(tree)
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            }
            assert "enqueue_task_once" in called, module.__name__


class TestRequestTimeoutIsThreadedFromConfig:
    def test_configured_request_timeout_reaches_the_adapter(self) -> None:
        """A well-formed pair (request > poll) must reach `get_updates` unmodified, proving
        `TELEGRAM_REQUEST_TIMEOUT_S` is not a dead constant: breaking the wiring would surface
        the adapter's hardcoded default (35.0) instead of the configured 99.0."""
        with use_home(
            dataclasses.replace(
                current_home(), telegram_poll_timeout_s=25, telegram_request_timeout_s=99.0
            )
        ):
            _secrets.save_secrets({"TELEGRAM_BOT_TOKEN": "123:abc"})

            calls: list[dict[str, object]] = []
            summary = _tg.poll_once(
                get_updates=_fake_get_updates_capturing(calls),
                send_message=lambda *a, **k: True,
            )

            assert summary.ok
            assert summary.warning == ""
            assert len(calls) == 1
            assert calls[0]["request_timeout"] == 99.0
            assert calls[0]["timeout"] == 25

    def test_a_different_configured_value_also_reaches_the_adapter(self) -> None:
        """A second, distinct value to rule out a coincidental match with
        the adapter's own hardcoded default."""
        with use_home(
            dataclasses.replace(
                current_home(), telegram_poll_timeout_s=10, telegram_request_timeout_s=40.0
            )
        ):
            _secrets.save_secrets({"TELEGRAM_BOT_TOKEN": "123:abc"})

            calls: list[dict[str, object]] = []
            summary = _tg.poll_once(
                get_updates=_fake_get_updates_capturing(calls),
                send_message=lambda *a, **k: True,
            )

            assert summary.ok
            assert summary.warning == ""
            assert calls[0]["request_timeout"] == 40.0


class TestWireDiscovery:
    def test_exact_challenge_discovers_only_groups_without_advancing_offset(self) -> None:
        _secrets.save_secrets({"TELEGRAM_BOT_TOKEN": "123:abc"})
        current_home().telegram_offset_file.parent.mkdir(parents=True, exist_ok=True)
        current_home().telegram_offset_file.write_text('{"offset": 40}')
        calls: list[dict[str, object]] = []

        def _updates(token: str, **kwargs: object) -> _tg.GetUpdatesResult:
            calls.append({"token": token, **kwargs})
            return _tg.GetUpdatesResult(
                True,
                updates=(
                    TelegramUpdate(41, "101", "7", "/wire A1B2C3", "private", "Ada"),
                    TelegramUpdate(42, "-100123", "7", "/wire WRONG", "supergroup", "Wrong Team"),
                    TelegramUpdate(
                        43, "-100456", "7", "/wire@docket_bot A1B2C3", "group", "Right Team"
                    ),
                ),
            )

        result = _tg.discover_wire_groups("A1B2C3", get_updates=_updates)

        assert result.ok
        assert result.configured
        assert result.groups == (_tg.TelegramGroup("-100456", "Right Team"),)
        assert calls == [{"token": "123:abc", "offset": 40, "timeout": 2, "request_timeout": 12.0}]
        assert json.loads(current_home().telegram_offset_file.read_text()) == {"offset": 40}

    def test_missing_token_and_transport_failure_are_typed_fallbacks(self) -> None:
        missing = _tg.discover_wire_groups("A1B2C3")
        assert missing.ok
        assert not missing.configured

        _secrets.save_secrets({"TELEGRAM_BOT_TOKEN": "123:abc"})
        failed = _tg.discover_wire_groups(
            "A1B2C3",
            get_updates=lambda *a, **k: _tg.GetUpdatesResult(False, error="offline"),
        )
        assert not failed.ok
        assert failed.configured
        assert failed.error == "offline"


class TestRequestTimeoutInvariantIsEnforced:
    def test_request_timeout_not_exceeding_poll_timeout_is_clamped_with_a_warning(self) -> None:
        """The invariant TELEGRAM_REQUEST_TIMEOUT_S > TELEGRAM_POLL_TIMEOUT_S is enforced, not
        merely stated: a misconfigured pair must not reach the adapter as-is, or every
        legitimately-empty long-poll would look like a local timeout."""
        with use_home(
            dataclasses.replace(
                current_home(), telegram_poll_timeout_s=50, telegram_request_timeout_s=35.0
            )
        ):
            _secrets.save_secrets({"TELEGRAM_BOT_TOKEN": "123:abc"})

            calls: list[dict[str, object]] = []
            summary = _tg.poll_once(
                get_updates=_fake_get_updates_capturing(calls),
                send_message=lambda *a, **k: True,
            )

            assert summary.ok
            assert summary.warning != ""
            assert "TELEGRAM_REQUEST_TIMEOUT_S" in summary.warning
            assert "TELEGRAM_POLL_TIMEOUT_S" in summary.warning
            request_timeout = calls[0]["request_timeout"]
            assert isinstance(request_timeout, float)
            assert request_timeout > 50

    def test_equal_values_also_violate_the_invariant(self) -> None:
        """`>` not `>=`: equal values still leave zero margin for the round
        trip and must also be corrected."""
        with use_home(
            dataclasses.replace(
                current_home(), telegram_poll_timeout_s=30, telegram_request_timeout_s=30.0
            )
        ):
            _secrets.save_secrets({"TELEGRAM_BOT_TOKEN": "123:abc"})

            calls: list[dict[str, object]] = []
            summary = _tg.poll_once(
                get_updates=_fake_get_updates_capturing(calls),
                send_message=lambda *a, **k: True,
            )

            assert summary.warning != ""
            request_timeout = calls[0]["request_timeout"]
            assert isinstance(request_timeout, float)
            assert request_timeout > 30

    def test_warning_is_carried_even_on_a_failed_poll(self) -> None:
        """The misconfiguration warning must not be lost just because the poll also failed for an
        unrelated reason -- `serve.py`'s loop must learn of a bad config on the first poll."""
        with use_home(
            dataclasses.replace(
                current_home(), telegram_poll_timeout_s=50, telegram_request_timeout_s=5.0
            )
        ):
            _secrets.save_secrets({"TELEGRAM_BOT_TOKEN": "123:abc"})

            def _failing(token: str, **kwargs: object) -> _tg.GetUpdatesResult:
                return _tg.GetUpdatesResult(False, error="cannot reach Telegram: boom")

            summary = _tg.poll_once(get_updates=_failing, send_message=lambda *a, **k: True)

            assert not summary.ok
            assert summary.warning != ""
