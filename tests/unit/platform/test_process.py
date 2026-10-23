"""Real git evidence helpers (`git_head_sha`, `git_merge_base`, `git_diff_stat`).

Each degrades to `None` rather than raising -- the same convention `git_current_branch`/
`git_changed_files` already use -- on a missing binary, a non-repository directory, or an
unresolvable ref. `subprocess.run` is monkeypatched throughout, mirroring
`tests/integration/test_system_adapter.py`'s pattern; no real git process ever runs here.
"""

from __future__ import annotations

import pytest

from docket.platform import git as _git_c
from docket.platform import process as _process
from docket.sandbox import docker as _docker_c

SUBJECT = "docket.platform.process"


class TestDesktopNotificationsAvailable:
    def test_linux_needs_a_session_and_notify_send(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_process.sys, "platform", "linux")
        monkeypatch.setattr(_process, "_which", lambda binary: binary == "notify-send")
        monkeypatch.setattr(_git_c, "_which", lambda binary: binary == "notify-send")
        monkeypatch.setattr(_docker_c, "_which", lambda binary: binary == "notify-send")
        monkeypatch.delenv("DISPLAY", raising=False)
        monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
        assert _process.desktop_notifications_available() is False
        monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
        assert _process.desktop_notifications_available() is True
        monkeypatch.setattr(_process, "_which", lambda binary: False)
        monkeypatch.setattr(_git_c, "_which", lambda binary: False)
        monkeypatch.setattr(_docker_c, "_which", lambda binary: False)
        assert _process.desktop_notifications_available() is False

    def test_macos_needs_only_osascript(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_process.sys, "platform", "darwin")
        monkeypatch.delenv("DISPLAY", raising=False)
        monkeypatch.setattr(_process, "_which", lambda binary: binary == "osascript")
        monkeypatch.setattr(_git_c, "_which", lambda binary: binary == "osascript")
        monkeypatch.setattr(_docker_c, "_which", lambda binary: binary == "osascript")
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
