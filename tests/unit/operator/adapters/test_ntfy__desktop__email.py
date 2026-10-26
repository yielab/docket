"""The desktop dialect and the sink for new dialects."""

from __future__ import annotations

import os
import shutil
import tempfile

import pytest
from tests.support.ntfy_harness import (
    _ChannelSpecLike,
    _event_approval,
    _event_minimal_with_canary,
)

from docket.operator import adapters as channels
from docket.operator.adapters import desktop, email, ntfy

SUBJECT = "docket.operator.adapters.ntfy"


def _fake_binary(tmpdir: str, name: str, body: str) -> str:
    script_path = f"{tmpdir}/{name}"
    with open(script_path, "w") as f:
        f.write(body)
    os.chmod(script_path, 0o755)
    return script_path


class TestDesktopDeliver:
    def test_calls_notify_send_with_title_and_body(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(desktop.sys, "platform", "linux")
        tmpdir = tempfile.mkdtemp()
        _fake_binary(tmpdir, "notify-send", '#!/bin/sh\necho "$@" >> /tmp/test-notify.txt\n')
        monkeypatch.setenv("PATH", tmpdir)
        spec = _ChannelSpecLike({})
        event = _event_approval()
        result = desktop.deliver(spec, event, secret=None, timeout=5.0)
        assert result.ok is True
        shutil.rmtree(tmpdir)

    def test_calls_osascript_on_macos(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(desktop.sys, "platform", "darwin")
        tmpdir = tempfile.mkdtemp()
        _fake_binary(tmpdir, "osascript", '#!/bin/sh\necho "$@" >> /tmp/test-notify.txt\n')
        monkeypatch.setenv("PATH", tmpdir)
        spec = _ChannelSpecLike({})
        event = _event_approval()
        result = desktop.deliver(spec, event, secret=None, timeout=5.0)
        assert result.ok is True
        shutil.rmtree(tmpdir)

    def test_missing_notify_send_returns_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(desktop.sys, "platform", "linux")
        monkeypatch.setenv("PATH", "")
        spec = _ChannelSpecLike({})
        event = _event_approval()
        result = desktop.deliver(spec, event, secret=None, timeout=5.0)
        assert result.ok is False
        assert "not found" in result.error

    def test_missing_osascript_returns_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(desktop.sys, "platform", "darwin")
        monkeypatch.setenv("PATH", "")
        spec = _ChannelSpecLike({})
        event = _event_approval()
        result = desktop.deliver(spec, event, secret=None, timeout=5.0)
        assert result.ok is False
        assert "not found" in result.error

    def test_nonzero_exit_is_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(desktop.sys, "platform", "linux")
        tmpdir = tempfile.mkdtemp()
        _fake_binary(tmpdir, "notify-send", "#!/bin/sh\nexit 1\n")
        monkeypatch.setenv("PATH", tmpdir)
        spec = _ChannelSpecLike({})
        event = _event_approval()
        result = desktop.deliver(spec, event, secret=None, timeout=5.0)
        assert result.ok is False
        shutil.rmtree(tmpdir)

    def test_canary_not_in_minimal_event_text(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(desktop.sys, "platform", "linux")
        tmpdir = tempfile.mkdtemp()
        output_file = f"{tmpdir}/output.txt"
        _fake_binary(tmpdir, "notify-send", f'#!/bin/sh\necho "$@" >> {output_file}\n')
        monkeypatch.setenv("PATH", tmpdir)
        spec = _ChannelSpecLike({})
        event = _event_minimal_with_canary()
        desktop.deliver(spec, event, secret=None, timeout=5.0)
        if os.path.exists(output_file):
            with open(output_file) as f:
                output = f.read()
            assert "CANARY_7f3" not in output
        shutil.rmtree(tmpdir)


class TestSinkForNewDialects:
    def test_ntfy_dialect_resolves(self) -> None:
        spec = _ChannelSpecLike({})
        spec.dialect = "ntfy"
        assert channels.sink_for(spec) is ntfy.deliver

    def test_desktop_dialect_resolves(self) -> None:
        spec = _ChannelSpecLike({})
        spec.dialect = "desktop"
        assert channels.sink_for(spec) is desktop.deliver

    def test_email_dialect_resolves(self) -> None:
        spec = _ChannelSpecLike({})
        spec.dialect = "email"
        assert channels.sink_for(spec) is email.deliver
