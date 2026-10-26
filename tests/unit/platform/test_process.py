"""The real process adapter: what the desktop-notification probe needs and the environment
switches it reads live."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from docket.platform import process as _process

SUBJECT = "docket.platform.process"


def _path_with(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *binaries: str) -> None:
    """A PATH holding only an executable stub for each of *binaries*."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in binaries:
        stub = bin_dir / name
        stub.write_text("#!/bin/sh\n")
        stub.chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_dir))


class TestDesktopNotificationsAvailable:
    def test_linux_needs_a_session_and_notify_send(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(sys, "platform", "linux")
        _path_with(tmp_path, monkeypatch, "notify-send")
        monkeypatch.delenv("DISPLAY", raising=False)
        monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
        assert _process.desktop_notifications_available() is False
        monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
        assert _process.desktop_notifications_available() is True
        monkeypatch.setenv("PATH", str(tmp_path / "nowhere"))
        assert _process.desktop_notifications_available() is False

    def test_macos_needs_only_osascript(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(sys, "platform", "darwin")
        monkeypatch.delenv("DISPLAY", raising=False)
        _path_with(tmp_path, monkeypatch, "osascript")
        assert _process.desktop_notifications_available() is True


# ── live environment switches ─────────────────────────────────────────────────


def test_the_environment_switches_are_read_live(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("DOCKET_NO_TRACE", "DOCKET_NO_EXPORT", "DOCKET_SECRETS_BACKEND"):
        monkeypatch.delenv(name, raising=False)
    assert (_process.no_trace(), _process.no_export(), _process.secrets_backend_requested()) == (
        False,
        False,
        "file",
    )
    monkeypatch.setenv("DOCKET_NO_TRACE", "1")
    monkeypatch.setenv("DOCKET_NO_EXPORT", "1")
    monkeypatch.setenv("DOCKET_SECRETS_BACKEND", "keyring")
    assert (_process.no_trace(), _process.no_export(), _process.secrets_backend_requested()) == (
        True,
        True,
        "keyring",
    )


def test_env_value_is_stripped_and_empty_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DOCKET_TEST_CRED", raising=False)
    assert _process.env_value("DOCKET_TEST_CRED") == ""
    monkeypatch.setenv("DOCKET_TEST_CRED", "  abc  ")
    assert _process.env_value("DOCKET_TEST_CRED") == "abc"


def test_credential_env_values_match_by_name_or_suffix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EXACT_NAME", " one ")
    monkeypatch.setenv("SOMETHING_API_KEY", "two")
    monkeypatch.setenv("EMPTY_API_KEY", "  ")
    monkeypatch.setenv("UNRELATED_VALUE", "three")
    values = _process.credential_env_values(("EXACT_NAME",), ("_API_KEY",))
    assert "one" in values and "two" in values
    assert "three" not in values and "" not in values
