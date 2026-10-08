"""``docket setup notify``: Telegram in one step, bindings, flush, and the fail-closed paths."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest
from typer.testing import CliRunner

import docket.config as _cfg
from docket.cli import _contract, _setup_notify, app
from docket.core import channel as _chan
from docket.core import fleet as _fleet
from docket.core import secrets as _secrets

SUBJECT = "docket.cli._setup_notify"

_runner = CliRunner()


@pytest.fixture
def sink(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """A fake delivery sink; every delivery lands in the returned list."""
    sent: list[Any] = []

    def _deliver(spec: Any, event: Any, **kwargs: Any) -> Any:
        sent.append((spec.name, event))
        return SimpleNamespace(ok=True, error="")

    monkeypatch.setattr(_setup_notify._channels, "sink_for", lambda spec: _deliver)
    return sent


@pytest.fixture
def two_pods() -> list[str]:
    ids = ["alpha-lead", "alpha-implementer", "beta-lead", "beta-implementer"]
    for aid in ids:
        _cfg.workspace_dir(aid).mkdir(parents=True, exist_ok=True)
        _fleet.add_agent(aid)
    return ids


def _bindings() -> dict[str, str]:
    return {b.agent_id: b.peer_id for b in _fleet.load_fleet().bindings}


class TestEnableTelegram:
    def test_one_step_writes_the_three_stores_and_sends_nothing(
        self, two_pods: list[str], sink: list[Any]
    ) -> None:
        result = _runner.invoke(
            app, ["setup", "notify", "enable", "telegram", "--chat", "42", "--token", "t0k"]
        )
        assert result.exit_code == 0, result.output
        assert _secrets.secret_value("TELEGRAM_BOT_TOKEN") == "t0k"
        spec = _chan.load_catalog().get("telegram")
        assert spec is not None and spec.enabled and spec.actors == ["42"]
        assert _bindings() == {"alpha-lead": "42", "beta-lead": "42"}
        assert sink == []

    def test_test_flag_sends_exactly_one_message(
        self, two_pods: list[str], sink: list[Any]
    ) -> None:
        result = _runner.invoke(
            app,
            ["setup", "notify", "enable", "telegram", "--chat", "42", "--token", "t", "--test"],
        )
        assert result.exit_code == 0, result.output
        assert [name for name, _ in sink] == ["telegram"]

    def test_without_a_chat_nothing_is_written(self, two_pods: list[str]) -> None:
        result = _runner.invoke(app, ["setup", "notify", "enable", "telegram", "--token", "t"])
        assert result.exit_code == 1
        assert not _cfg.CHANNELS_FILE.exists()
        assert _secrets.secret_value("TELEGRAM_BOT_TOKEN") is None
        assert _bindings() == {}

    def test_without_a_token_off_a_tty_nothing_is_written(
        self, two_pods: list[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        monkeypatch.setattr(_contract, "_is_tty", lambda: False)
        result = _runner.invoke(app, ["setup", "notify", "enable", "telegram", "--chat", "42"])
        assert result.exit_code == 1
        assert not _cfg.CHANNELS_FILE.exists()
        assert _bindings() == {}

    def test_the_function_keeps_a_stored_token_when_given_none(self, two_pods: list[str]) -> None:
        _setup_notify.store_secret("TELEGRAM_BOT_TOKEN", "kept")
        written = _setup_notify.enable_telegram(["7"], None, test=False)
        assert written.secret == "" and written.bindings == ["alpha-lead", "beta-lead"]
        assert _secrets.secret_value("TELEGRAM_BOT_TOKEN") == "kept"


class TestBind:
    def test_bind_writes_the_binding_and_unbind_removes_it(self, two_pods: list[str]) -> None:
        bound = _runner.invoke(app, ["setup", "notify", "bind", "alpha-lead", "--chat", "-100"])
        assert bound.exit_code == 0, bound.output
        assert _bindings() == {"alpha-lead": "-100"}
        gone = _runner.invoke(app, ["setup", "notify", "unbind", "alpha-lead", "--yes"])
        assert gone.exit_code == 0, gone.output
        assert _bindings() == {}

    def test_bind_an_unknown_member_exits_1(self, two_pods: list[str]) -> None:
        result = _runner.invoke(app, ["setup", "notify", "bind", "ghost", "--chat", "1"])
        assert result.exit_code == 1

    def test_bind_off_a_tty_without_a_chat_refuses(
        self, two_pods: list[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(_contract, "_is_tty", lambda: False)
        result = _runner.invoke(app, ["setup", "notify", "bind", "alpha-lead"])
        assert result.exit_code == 1
        assert _bindings() == {}

    def test_unbind_off_a_tty_without_yes_refuses(
        self, two_pods: list[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _fleet.upsert_binding("alpha-lead", "9", "telegram")
        monkeypatch.setattr(_contract, "_is_tty", lambda: False)
        result = _runner.invoke(app, ["setup", "notify", "unbind", "alpha-lead"])
        assert result.exit_code == 1
        assert _bindings() == {"alpha-lead": "9"}


class TestFlush:
    def test_dry_run_delivers_nothing(self, sink: list[Any]) -> None:
        result = _runner.invoke(app, ["setup", "notify", "flush", "--dry-run"])
        assert result.exit_code == 0, result.output
        assert sink == []

    def test_bare_notify_prints_help_and_delivers_nothing(self, sink: list[Any]) -> None:
        result = _runner.invoke(app, ["setup", "notify"])
        assert "flush" in result.output
        assert sink == []


class TestCatalog:
    def test_list_json_names_every_built_in_channel(self) -> None:
        result = _runner.invoke(app, ["setup", "notify", "list", "--json"])
        assert result.exit_code == 0
        assert "telegram" in {row["name"] for row in json.loads(result.stdout)}

    def test_enable_ntfy_applies_set_overrides(self) -> None:
        result = _runner.invoke(app, ["setup", "notify", "enable", "ntfy", "--set", "topic=myapp"])
        assert result.exit_code == 0, result.output
        spec = _chan.load_catalog().get("ntfy")
        assert spec is not None and spec.config["topic"] == "myapp"

    def test_widening_content_off_a_tty_needs_yes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_contract, "_is_tty", lambda: False)
        refused = _runner.invoke(app, ["setup", "notify", "privacy", "console", "conversation"])
        assert refused.exit_code == 1
        allowed = _runner.invoke(
            app, ["setup", "notify", "privacy", "console", "conversation", "--yes"]
        )
        assert allowed.exit_code == 0, allowed.output

    def test_removed_top_level_names_are_unknown_commands(self) -> None:
        for name in ("wire", "unwire", "notify", "conversations", "channels", "exporters"):
            assert _runner.invoke(app, [name]).exit_code == 2


def test_show_telegram_lists_bindings_and_conversations(two_pods: list[str]) -> None:
    _setup_notify._bind("alpha-lead", "55", "telegram")
    result = _runner.invoke(app, ["setup", "notify", "show", "telegram"])
    assert result.exit_code == 0, result.output
    assert "alpha-lead" in result.output and "55" in result.output
