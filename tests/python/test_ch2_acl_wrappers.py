"""CH-2: unit tests for the new `openclaw` ACL wrappers.

Mirrors the mocking style of test_m5_system.py — subprocess.run and shutil.which
are patched at the real module (the ACL functions do local `import subprocess as
_sp` / `import shutil as _shutil`, which are just aliases to the same module
objects, so patching the module-level attribute is visible to them too).
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from typing import Any

import pytest

from docket.edges.adapters import openclaw as _oc


@dataclass
class _FakeCompleted:
    """Minimal stand-in for subprocess.CompletedProcess."""

    returncode: int
    stdout: str = ""
    stderr: str = ""


# ── openclaw_version ─────────────────────────────────────────────────────────


def test_openclaw_version_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: _FakeCompleted(0, stdout="openclaw 2026.2.23\n")
    )
    probe = _oc.openclaw_version()
    assert probe.available is True
    assert probe.returncode == 0
    assert probe.output == "openclaw 2026.2.23"


def test_openclaw_version_nonzero_exit_still_available(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _FakeCompleted(1, stdout="huh"))
    probe = _oc.openclaw_version()
    assert probe.available is True
    assert probe.returncode == 1
    assert probe.output == "huh"


def test_openclaw_version_missing_binary(monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_fnf(*a: Any, **k: Any) -> None:
        raise FileNotFoundError("no openclaw")

    monkeypatch.setattr(subprocess, "run", raise_fnf)
    probe = _oc.openclaw_version()
    assert probe == _oc.VersionProbe(available=False, returncode=-1, output="")


def test_openclaw_version_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_timeout(*a: Any, **k: Any) -> None:
        raise subprocess.TimeoutExpired(cmd="openclaw", timeout=5)

    monkeypatch.setattr(subprocess, "run", raise_timeout)
    probe = _oc.openclaw_version()
    assert probe.available is False


# ── agents_add ────────────────────────────────────────────────────────────────


def test_agents_add_binary_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda name: None)

    def boom(*a: Any, **k: Any) -> None:
        raise AssertionError("subprocess.run must not be called when openclaw is missing")

    monkeypatch.setattr(subprocess, "run", boom)
    result = _oc.agents_add("myproj-implementer", "/ws/myproj-implementer", "anthropic/sonnet")
    assert result == _oc.AgentsAddResult(found=False, ok=False, returncode=None, timed_out=False)


def test_agents_add_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/openclaw")
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **k: Any) -> _FakeCompleted:
        calls.append(cmd)
        return _FakeCompleted(0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = _oc.agents_add("myproj-implementer", "/ws/myproj-implementer", "anthropic/sonnet")
    assert result == _oc.AgentsAddResult(found=True, ok=True, returncode=0, timed_out=False)
    assert calls[0] == [
        "openclaw",
        "agents",
        "add",
        "myproj-implementer",
        "--workspace",
        "/ws/myproj-implementer",
        "--model",
        "anthropic/sonnet",
        "--non-interactive",
    ]


def test_agents_add_nonzero_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/openclaw")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _FakeCompleted(3))
    result = _oc.agents_add("id", "/ws/id", "m")
    assert result == _oc.AgentsAddResult(found=True, ok=False, returncode=3, timed_out=False)


def test_agents_add_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/openclaw")

    def raise_timeout(*a: Any, **k: Any) -> None:
        raise subprocess.TimeoutExpired(cmd="openclaw", timeout=15)

    monkeypatch.setattr(subprocess, "run", raise_timeout)
    result = _oc.agents_add("id", "/ws/id", "m")
    assert result == _oc.AgentsAddResult(found=True, ok=False, returncode=None, timed_out=True)


# ── auth_setup_token / auth_paste_token ──────────────────────────────────────


def test_auth_setup_token_builds_argv_and_forwards_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []

    def fake_run(cmd: list[str], **k: Any) -> _FakeCompleted:
        calls.append({"cmd": cmd, **k})
        return _FakeCompleted(0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = _oc.auth_setup_token(["--flag", "x"], timeout=10)
    assert result.returncode == 0
    assert calls[0]["cmd"] == [
        "openclaw",
        "models",
        "auth",
        "setup-token",
        "--provider",
        "anthropic",
        "--flag",
        "x",
    ]
    assert calls[0]["timeout"] == 10
    # Interactive: no output capture — capture_output/text must NOT be forced on.
    assert "capture_output" not in calls[0]
    assert "text" not in calls[0]


def test_auth_paste_token_builds_argv(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(subprocess, "run", lambda cmd, **k: calls.append(cmd) or _FakeCompleted(0))
    _oc.auth_paste_token()
    assert calls[0] == ["openclaw", "models", "auth", "paste-token", "--provider", "anthropic"]


def test_auth_paste_token_propagates_exceptions(monkeypatch: pytest.MonkeyPatch) -> None:
    """cmd_auth's login/key/setup branches don't wrap this call — an unexpected
    OSError should propagate, not be swallowed by the ACL."""

    def boom(*a: Any, **k: Any) -> None:
        raise OSError("launch failed")

    monkeypatch.setattr(subprocess, "run", boom)
    with pytest.raises(OSError):
        _oc.auth_paste_token()


# ── onboard ───────────────────────────────────────────────────────────────────


def test_onboard_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _FakeCompleted(0))
    assert _oc.onboard() is True


def test_onboard_failure_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _FakeCompleted(1))
    assert _oc.onboard() is False


def test_onboard_timeout_returns_false(monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_timeout(*a: Any, **k: Any) -> None:
        raise subprocess.TimeoutExpired(cmd="openclaw", timeout=600)

    monkeypatch.setattr(subprocess, "run", raise_timeout)
    assert _oc.onboard() is False


def test_onboard_missing_binary_returns_false(monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_fnf(*a: Any, **k: Any) -> None:
        raise FileNotFoundError("no openclaw")

    monkeypatch.setattr(subprocess, "run", raise_fnf)
    assert _oc.onboard() is False
