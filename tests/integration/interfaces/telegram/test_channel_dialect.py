"""The outbound telegram channel dialect and the coalescing of unauthorized batches."""

from __future__ import annotations

import ast
import dataclasses
from pathlib import Path
from typing import Any, ClassVar

import pytest
from tests.support.tasks import task
from tests.support.telegram_harness import (
    _bind,
    _read_audit,
)

from docket.governance import policy as _policy
from docket.governance import secrets as _secrets
from docket.interfaces.telegram import bot as _tg
from docket.interfaces.telegram.client import TelegramUpdate
from docket.kernel.home import current_home, use_home
from docket.kernel.operator_contract import make_event
from docket.operator.adapters import telegram as _tg_channel
from docket.operator.channel import ChannelSpec

SUBJECT = "docket.interfaces.telegram.bot"


def _notify_event(pod: str = "demo", task_id: str = "task-1") -> Any:
    return make_event(
        "task.input_required",
        pod,
        f"task:{pod}:{task_id}",
        {"pod": pod, "taskId": task_id},
        time="2026-09-28T00:00:00Z",
        version=f"waiting_input:{task_id}",
    )


def _channel_spec(actors: list[str]) -> ChannelSpec:
    return ChannelSpec(kind="channel", name="telegram", dialect="telegram", actors=actors)


class TestTelegramChannelDialect:
    """The outbound half of the `telegram` dialect (`operator/adapters/telegram.py::
    deliver`) -- the second legitimate `send_message` call site `TestOutboundOnlyThroughTheChannel`
    pins. Never touches a socket: `send_message` is monkeypatched on the dialect module."""

    def test_sends_to_every_actor_with_the_resolved_secret(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sent: list[tuple[str, str]] = []
        monkeypatch.setattr(
            _tg_channel,
            "send_message",
            lambda token, chat_id, text, **k: sent.append((token, chat_id)) or True,
        )

        result = _tg_channel.deliver(
            _channel_spec(["-100", "-200"]), _notify_event(), secret="123:abc", timeout=5.0
        )

        assert result.ok
        assert sorted(sent) == [("123:abc", "-100"), ("123:abc", "-200")]

    def test_missing_secret_is_a_typed_failure_not_an_exception(self) -> None:
        result = _tg_channel.deliver(
            _channel_spec(["-100"]), _notify_event(), secret=None, timeout=5.0
        )
        assert not result.ok
        assert "secret" in result.error

    def test_no_actors_is_a_typed_failure(self) -> None:
        result = _tg_channel.deliver(
            _channel_spec([]), _notify_event(), secret="123:abc", timeout=5.0
        )
        assert not result.ok
        assert "actors" in result.error

    def test_a_failed_send_is_reported_without_raising(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(_tg_channel, "send_message", lambda *a, **k: False)

        result = _tg_channel.deliver(
            _channel_spec(["-100"]), _notify_event(), secret="123:abc", timeout=5.0
        )

        assert not result.ok
        assert "-100" in result.error

    def test_sink_for_resolves_the_telegram_dialect_to_this_module(self) -> None:
        from docket.operator.adapters import sink_for

        assert sink_for(_channel_spec(["-100"])) is _tg_channel.deliver

    def test_only_actors_are_reached_never_every_fleet_binding(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A pod may have several `fleet.json` bindings; the channel push must reach only the
        chat ids the operator explicitly put in `actors`."""
        _bind("demo-lead", "-100300")
        _bind("security", "-100200")
        sent: list[str] = []
        monkeypatch.setattr(
            _tg_channel,
            "send_message",
            lambda token, chat_id, text, **k: sent.append(chat_id) or True,
        )

        _tg_channel.deliver(
            _channel_spec(["-100300"]), _notify_event(), secret="123:abc", timeout=5.0
        )

        assert sent == ["-100300"]


class TestOutboundOnlyThroughTheChannel:
    """Outbound Telegram messages now exist through exactly two paths, and no other
    (specs/functional/telegram-integration.spec.md, Command grammar 7): the
    reply inside `interfaces.telegram.bot.poll_once` (unchanged -- a response to a message that already
    passed `_authorize`), and `operator/adapters/telegram.py::deliver`, the `telegram`
    channel dialect's `notify` push, which only ever reaches a chat id the operator explicitly
    listed in that channel's own `actors` -- never every `fleet.json` binding, and never from
    `interfaces/telegram/bot.py` itself. Pinned structurally (an AST walk over `src/`) rather than
    behaviourally, because the failure guarded against is someone *adding* a third caller -- a
    behavioural test can only assert about call sites that already exist. If a third caller is
    ever added, this test must change in the same commit."""

    _SRC = Path(_tg.__file__).resolve().parents[2]  # src/docket/

    #: The two legitimate call sites: the reply inside `interfaces.telegram.bot.poll_once`, and the
    #: `telegram` channel dialect's outbound, `actors`-scoped push.
    #: The email dialect also defines a `send_message` -- `smtplib.SMTP.send_message`, an
    #: unrelated stdlib method name collision, not a path to the Telegram channel.
    _ALLOWED: ClassVar[set[str]] = {
        "interfaces/telegram/bot.py",
        "operator/adapters/telegram.py",
        "operator/adapters/email.py",
    }

    def _send_call_sites(self) -> list[str]:
        found: list[str] = []
        for path in sorted(self._SRC.rglob("*.py")):
            rel = path.relative_to(self._SRC).as_posix()
            if rel in self._ALLOWED or rel == "interfaces/telegram/client.py":
                continue  # the wire-format adapter defines it; the two allowed callers use it
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                fn = node.func
                name = (
                    fn.attr
                    if isinstance(fn, ast.Attribute)
                    else fn.id
                    if isinstance(fn, ast.Name)
                    else ""
                )
                if name == "send_message":
                    found.append(f"{rel}:{node.lineno}")
        return found

    def test_nothing_outside_the_reply_and_channel_paths_sends_a_telegram_message(self) -> None:
        offenders = self._send_call_sites()
        assert not offenders, (
            "docket must only message a Telegram chat via poll_once's reply or the "
            f"actors-scoped channel dialect; found send_message call(s) at: {offenders}"
        )

    def test_the_approval_store_does_not_reach_the_telegram_channel(self) -> None:
        """Creating an approval must not notify -- an operator polls with /status."""
        source = (self._SRC / "governance" / "approval.py").read_text(encoding="utf-8")
        assert "telegram" not in source.replace("APPROVAL_CHANNELS", "").replace(
            '"telegram"', ""
        ).replace("``telegram``", ""), (
            "governance/approval.py referencing the telegram module would mean approval "
            "creation can push a message; the channel is inbound-only"
        )

    def test_delegate_replies_with_a_task_id_not_the_agents_answer(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """spec: Command grammar 8 -- the channel queues work, it does not carry results."""
        monkeypatch.setattr(_tg, "_lead_project", lambda _aid: "demo")
        monkeypatch.setattr(_tg._policy, "policy_eval_detail", lambda *a, **k: _policy.PolicyHit())
        monkeypatch.setattr(
            _tg._queue, "enqueue_task_once", lambda *a, **k: (task(id="task-abc123"), True)
        )

        result = _tg._handle_delegate("demo-lead", "do the thing")

        assert result.ok
        assert "task-abc123" in result.reply
        assert "do the thing" not in result.reply


class TestUnauthorizedBatchIsCoalesced:
    """One batch from an unbound chat writes one audit entry per chat id."""

    @staticmethod
    def _updates(chat_id: str, count: int) -> _tg.GetUpdatesFn:
        from docket.interfaces.telegram.client import GetUpdatesResult

        updates = tuple(
            TelegramUpdate(update_id=i, chat_id=chat_id, user_id="9", text="/status")
            for i in range(1, count + 1)
        )

        def _fake(token: str, **_: object) -> GetUpdatesResult:
            return GetUpdatesResult(True, updates=updates)

        return _fake

    def test_ten_messages_from_one_unbound_chat_write_one_entry(self) -> None:
        """Ten refusals in one batch audit as one telegram.unauthorized line with count=10."""
        with use_home(dataclasses.replace(current_home(), telegram_poll_timeout_s=0)):
            _secrets.save_secrets({"TELEGRAM_BOT_TOKEN": "123:abc"})
            replies: list[str] = []
            summary = _tg.poll_once(
                get_updates=self._updates("-999999", 10),
                send_message=lambda _t, _c, text: replies.append(text) or True,
            )
            assert summary.processed == 10
            assert len(replies) == 10
            entries = [e for e in _read_audit() if e.get("action") == "telegram.unauthorized"]
            assert len(entries) == 1
            assert "count=10" in str(entries[0]["detail"])
            assert "-999999" in str(entries[0]["detail"])

    def test_two_unbound_chats_in_one_batch_write_one_entry_each(self) -> None:
        """Coalescing is per chat id, so two chats in one batch keep two entries."""
        from docket.interfaces.telegram.client import GetUpdatesResult

        with use_home(dataclasses.replace(current_home(), telegram_poll_timeout_s=0)):
            _secrets.save_secrets({"TELEGRAM_BOT_TOKEN": "123:abc"})
            updates = (
                TelegramUpdate(update_id=1, chat_id="-111", user_id="9", text="/status"),
                TelegramUpdate(update_id=2, chat_id="-222", user_id="9", text="/status"),
                TelegramUpdate(update_id=3, chat_id="-111", user_id="9", text="/status"),
            )
            _tg.poll_once(
                get_updates=lambda _t, **_: GetUpdatesResult(True, updates=updates),
                send_message=lambda *a: True,
            )
            entries = [e for e in _read_audit() if e.get("action") == "telegram.unauthorized"]
            assert len(entries) == 2
            assert sorted(str(e["detail"]).count("count=") for e in entries) == [1, 1]
            assert any("count=2" in str(e["detail"]) for e in entries)
