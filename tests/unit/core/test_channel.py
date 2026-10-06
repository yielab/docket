"""The channel catalog (`core/channel.py`).

Covers ``load_channel_document`` (the `kind: channel` document loader,
specs/functional/operator-loop.spec.md "Notifications"), the built-in + global catalog merge
with inheritance, dialect/capability/actor validation, and the `content` widening rule. Mirrors
``tests/unit/core/test_exporter.py``'s shape for the sibling catalog.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import docket.config as _cfg
from docket.core import channel as _channel
from docket.edges import store as _store

SUBJECT = "docket.core.channel"

# CHANNELS_FILE is isolated to a tmp DOCKET_HOME by the autouse _isolate_docket_home fixture
# in tests/conftest.py -- no real ~/.docket is ever touched here.


class TestBuiltinCatalog:
    def test_every_built_in_document_loads(self) -> None:
        directory = _cfg.CHANNEL_TEMPLATES_DIR
        files = sorted(directory.glob("*.yaml"))
        assert len(files) == 7, f"expected 7 built-in channel documents, found {len(files)}"
        for path in files:
            spec = _channel.load_channel_document(path)
            assert spec.name

    def test_fresh_catalog_is_seven_builtins_only_console_enabled(self) -> None:
        catalog = _channel.load_catalog()
        assert set(catalog.entries) == {
            "console",
            "desktop",
            "webhook",
            "command",
            "ntfy",
            "email",
            "telegram",
        }
        for name, spec in catalog.entries.items():
            assert catalog.source_of(name) == "built-in"
            assert spec.enabled is (name == "console")

    def test_every_builtin_declares_a_non_empty_description(self) -> None:
        catalog = _channel.load_catalog()
        for name, spec in catalog.entries.items():
            assert spec.description.strip(), name


class TestDelivering:
    def test_a_fresh_catalog_delivers_nowhere(self) -> None:
        """console is on and console sends nothing, so nothing reaches an absent operator."""
        delivering = _channel.load_catalog().delivering()
        assert delivering == []
        text = _channel.unreached_warning(delivering)
        assert text is not None
        assert "docket channels enable desktop" in text
        assert "docket channels enable ntfy --set topic=" in text
        assert "docket inbox" in text

    def test_an_enabled_notify_channel_delivers_and_silences_the_warning(self) -> None:
        _channel.enable_channel("desktop")
        delivering = _channel.load_catalog().delivering()
        assert delivering == ["desktop"]
        assert _channel.unreached_warning(delivering) is None

    def test_a_disabled_channel_and_console_never_count(self) -> None:
        _channel.enable_channel("ntfy", {"config": {"topic": "t"}})
        _channel.disable_channel("ntfy")
        assert _channel.load_catalog().delivering() == []
        assert "console" in _channel.SILENT_DIALECTS


class TestLoadChannelDocument:
    def test_loads_a_minimal_document(self, tmp_path: Path) -> None:
        doc = tmp_path / "desktop.yaml"
        doc.write_text("kind: channel\nname: desktop\ndialect: desktop\ncapabilities: [notify]\n")

        spec = _channel.load_channel_document(doc)

        assert spec.name == "desktop"
        assert spec.dialect == "desktop"
        assert spec.content == "minimal"
        assert spec.enabled is False
        assert spec.actors == []

    def test_wrong_kind_is_refused(self, tmp_path: Path) -> None:
        doc = tmp_path / "bad.yaml"
        doc.write_text("kind: exporter\nname: x\n")

        with pytest.raises(_channel.ChannelError, match="kind"):
            _channel.load_channel_document(doc)

    def test_missing_name_is_refused(self, tmp_path: Path) -> None:
        doc = tmp_path / "bad.yaml"
        doc.write_text("kind: channel\ndialect: console\n")

        with pytest.raises(_channel.ChannelError, match="name"):
            _channel.load_channel_document(doc)


class TestCapabilityCeiling:
    """The card's explicit negative case: a notify-only dialect cannot declare `decide`."""

    def test_email_with_decide_is_refused_naming_the_dialects_maximum(self, tmp_path: Path) -> None:
        doc = tmp_path / "bad.yaml"
        doc.write_text(
            "kind: channel\nname: mail\ndialect: email\ncapabilities: [notify, decide]\n"
        )

        with pytest.raises(_channel.ChannelError) as excinfo:
            _channel.load_channel_document(doc)
        message = str(excinfo.value)
        assert "capabilities[1]" in message
        assert "notify" in message

    def test_unknown_capability_literal_is_refused(self, tmp_path: Path) -> None:
        doc = tmp_path / "bad.yaml"
        doc.write_text("kind: channel\nname: x\ndialect: console\ncapabilities: [fly]\n")

        with pytest.raises(_channel.ChannelError):
            _channel.load_channel_document(doc)


class TestOnVocabulary:
    def test_unknown_on_entry_is_refused_naming_it(self, tmp_path: Path) -> None:
        doc = tmp_path / "bad.yaml"
        doc.write_text(
            "kind: channel\nname: x\ndialect: console\ncapabilities: [notify]\non: [bogus]\n"
        )

        with pytest.raises(_channel.ChannelError) as excinfo:
            _channel.load_channel_document(doc)
        assert "on[0]" in str(excinfo.value)

    def test_needs_you_shorthand_and_a_real_event_kind_both_load(self, tmp_path: Path) -> None:
        doc = tmp_path / "ok.yaml"
        doc.write_text(
            "kind: channel\nname: x\ndialect: ntfy\ncapabilities: [notify]\n"
            "on: [needs_you, task.failed]\n"
        )

        spec = _channel.load_channel_document(doc)
        assert spec.on == ["needs_you", "task.failed"]


class TestActorsRequiredWhenEnabled:
    """A dormant document may declare `decide`/`converse` with empty `actors` -- exactly the
    shape the built-in `telegram` template ships. Only an *enabled* document is rejected."""

    def test_dormant_telegram_with_no_actors_loads(self) -> None:
        spec = _channel.ChannelSpec(
            kind="channel",
            name="telegram",
            dialect="telegram",
            capabilities=["notify", "converse", "decide"],
            enabled=False,
        )
        assert spec.actors == []

    def test_enabled_telegram_with_decide_and_no_actors_is_refused(self) -> None:
        with pytest.raises(Exception, match="actors"):
            _channel.ChannelSpec(
                kind="channel",
                name="telegram",
                dialect="telegram",
                capabilities=["decide"],
                enabled=True,
            )

    def test_enabled_console_with_decide_and_no_actors_is_fine(self) -> None:
        spec = _channel.ChannelSpec(
            kind="channel",
            name="console",
            dialect="console",
            capabilities=["notify", "converse", "decide"],
            enabled=True,
        )
        assert spec.actors == []


class TestSecretField:
    def test_credential_shaped_value_is_refused_naming_the_field(self) -> None:
        with pytest.raises(Exception, match="secret"):
            _channel.ChannelSpec(
                kind="channel",
                name="webhook",
                dialect="webhook",
                capabilities=["notify"],
                secret="sk-1234567890123456789",
            )

    def test_a_valid_name_is_accepted(self) -> None:
        spec = _channel.ChannelSpec(
            kind="channel",
            name="webhook",
            dialect="webhook",
            capabilities=["notify"],
            secret="WEBHOOK_SIGNING_SECRET",
        )
        assert spec.secret == "WEBHOOK_SIGNING_SECRET"


class TestGlobalOverrideInheritance:
    def test_partial_global_override_inherits_unset_fields(self) -> None:
        _store.write_json(
            _cfg.CHANNELS_FILE,
            {
                "channels": {
                    "ntfy": {
                        "kind": "channel",
                        "name": "ntfy",
                        "enabled": True,
                        "config": {"server": "https://ntfy.sh", "topic": "mytopic"},
                    }
                }
            },
        )

        catalog = _channel.load_catalog()
        spec = catalog.get("ntfy")

        assert spec is not None
        assert catalog.source_of("ntfy") == "global"
        assert spec.dialect == "ntfy"
        assert spec.capabilities == ["notify"]
        assert spec.config == {"server": "https://ntfy.sh", "topic": "mytopic"}


class TestEnableChannel:
    def test_unknown_name_is_refused(self) -> None:
        with pytest.raises(_channel.ChannelError, match="not in the channel catalog"):
            _channel.enable_channel("does-not-exist")

    def test_ntfy_without_topic_is_refused_without_writing(self) -> None:
        with pytest.raises(_channel.ChannelError, match="topic"):
            _channel.enable_channel("ntfy")
        assert _channel.load_catalog().get("ntfy").enabled is False  # type: ignore[union-attr]

    def test_ntfy_with_topic_persists_and_is_reflected_on_reload(self) -> None:
        spec = _channel.enable_channel("ntfy", {"config": {"topic": "mytopic"}})
        assert spec.enabled is True
        assert spec.config["topic"] == "mytopic"

        reloaded = _channel.load_catalog().get("ntfy")
        assert reloaded is not None
        assert reloaded.enabled is True
        assert reloaded.config["topic"] == "mytopic"

    def test_telegram_without_actors_is_refused_without_writing(self) -> None:
        with pytest.raises(_channel.ChannelError, match="actor"):
            _channel.enable_channel("telegram")
        assert _channel.load_catalog().get("telegram").enabled is False  # type: ignore[union-attr]

    def test_telegram_with_actors_persists(self) -> None:
        spec = _channel.enable_channel("telegram", {"actors": ["12345"]})
        assert spec.enabled is True
        assert spec.actors == ["12345"]


class TestDisableChannel:
    def test_unknown_name_is_refused(self) -> None:
        with pytest.raises(_channel.ChannelError, match="not in the channel catalog"):
            _channel.disable_channel("does-not-exist")

    def test_disabling_console_keeps_its_capabilities(self) -> None:
        spec = _channel.disable_channel("console")
        assert spec.enabled is False
        assert spec.capabilities == ["notify", "converse", "decide"]


class TestDeleteChannel:
    def test_built_in_with_no_global_override_is_refused(self) -> None:
        with pytest.raises(_channel.ChannelError, match="built-in"):
            _channel.delete_channel("console")

    def test_removes_a_global_entry(self) -> None:
        spec = _channel.ChannelSpec(
            kind="channel", name="my-webhook", dialect="webhook", capabilities=["notify"]
        )
        _channel.save_channel(spec)
        assert _channel.load_catalog().get("my-webhook") is not None

        _channel.delete_channel("my-webhook")
        assert _channel.load_catalog().get("my-webhook") is None


class TestContentWidening:
    def test_order_is_minimal_actions_conversation(self) -> None:
        assert _channel.is_widening("minimal", "actions") is True
        assert _channel.is_widening("minimal", "conversation") is True
        assert _channel.is_widening("actions", "conversation") is True
        assert _channel.is_widening("actions", "minimal") is False
        assert _channel.is_widening("conversation", "actions") is False
        assert _channel.is_widening("minimal", "minimal") is False

    def test_set_content_unknown_name_is_refused(self) -> None:
        with pytest.raises(_channel.ChannelError, match="not in the channel catalog"):
            _channel.set_content("does-not-exist", "actions")

    def test_set_content_unknown_level_is_refused(self) -> None:
        with pytest.raises(_channel.ChannelError, match="content level"):
            _channel.set_content("console", "full")

    def test_set_content_persists(self) -> None:
        updated = _channel.set_content("console", "conversation")
        assert updated.content == "conversation"
        reloaded = _channel.load_catalog().get("console")
        assert reloaded is not None
        assert reloaded.content == "conversation"


class TestExportChannel:
    def test_round_trips_a_built_in(self) -> None:
        rendered = _channel.export_channel("console")
        assert "kind: channel" in rendered
        assert "name: console" in rendered

    def test_unknown_name_is_refused(self) -> None:
        with pytest.raises(_channel.ChannelError):
            _channel.export_channel("does-not-exist")
