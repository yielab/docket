"""M5 tests: docket.edges.adapters.system — systemctl/docker/git wrappers.

These tests fake `subprocess.run` (and the service-manager override) with
monkeypatch so no real systemctl/docker/git is ever invoked. They cover:
  * gateway active / inactive
  * restart success / failure
  * DOCKET_NO_RESTART=1 dry-run
  * the no-systemd fallback path
  * docker availability + ps
  * git branch lookup
"""

from __future__ import annotations

import subprocess
from typing import Any

import pytest

from docket.edges.adapters import system


class _FakeCompleted:
    """Minimal stand-in for subprocess.CompletedProcess."""

    def __init__(self, returncode: int = 0, stdout: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = ""


def _force_systemd(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOCKET_SERVICE_MANAGER", "systemd")


def _force_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOCKET_SERVICE_MANAGER", "none")


# ── service_manager / service_hint ──────────────────────────────────────────────


def test_service_manager_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOCKET_SERVICE_MANAGER", "launchd")
    assert system.service_manager() == "launchd"


def test_service_manager_detects_systemd(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DOCKET_SERVICE_MANAGER", raising=False)
    monkeypatch.setattr(system, "_which", lambda b: b == "systemctl")
    assert system.service_manager() == "systemd"


def test_service_manager_detects_launchd(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DOCKET_SERVICE_MANAGER", raising=False)
    monkeypatch.setattr(system, "_which", lambda b: b == "launchctl")
    assert system.service_manager() == "launchd"


def test_service_manager_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DOCKET_SERVICE_MANAGER", raising=False)
    monkeypatch.setattr(system, "_which", lambda b: False)
    assert system.service_manager() == "none"


def test_service_hint_systemd(monkeypatch: pytest.MonkeyPatch) -> None:
    _force_systemd(monkeypatch)
    assert system.service_hint("restart") == "systemctl --user restart openclaw-gateway.service"


def test_service_hint_none(monkeypatch: pytest.MonkeyPatch) -> None:
    _force_none(monkeypatch)
    assert system.service_hint("start") == "openclaw gateway start"


# ── systemctl_is_active / gateway_active ────────────────────────────────────────


def test_gateway_active_true(monkeypatch: pytest.MonkeyPatch) -> None:
    _force_systemd(monkeypatch)

    def fake_run(cmd: list[str], **_: Any) -> _FakeCompleted:
        assert cmd == ["systemctl", "--user", "is-active", system.GATEWAY_UNIT]
        return _FakeCompleted(returncode=0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert system.gateway_active() is True


def test_gateway_active_false_when_inactive(monkeypatch: pytest.MonkeyPatch) -> None:
    _force_systemd(monkeypatch)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _FakeCompleted(returncode=3))
    assert system.gateway_active() is False


def test_systemctl_is_active_false_off_systemd(monkeypatch: pytest.MonkeyPatch) -> None:
    _force_none(monkeypatch)

    def boom(*_a: Any, **_k: Any) -> _FakeCompleted:
        raise AssertionError("subprocess.run must not be called off systemd")

    monkeypatch.setattr(subprocess, "run", boom)
    assert system.systemctl_is_active() is False


def test_systemctl_is_active_handles_missing_binary(monkeypatch: pytest.MonkeyPatch) -> None:
    _force_systemd(monkeypatch)

    def raise_fnf(*_a: Any, **_k: Any) -> _FakeCompleted:
        raise FileNotFoundError

    monkeypatch.setattr(subprocess, "run", raise_fnf)
    assert system.systemctl_is_active() is False


def test_systemctl_is_active_handles_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    _force_systemd(monkeypatch)

    def raise_timeout(*_a: Any, **_k: Any) -> _FakeCompleted:
        raise subprocess.TimeoutExpired(cmd="systemctl", timeout=5)

    monkeypatch.setattr(subprocess, "run", raise_timeout)
    assert system.systemctl_is_active() is False


# ── systemctl_restart / systemctl_start ─────────────────────────────────────────


def test_systemctl_restart_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _force_systemd(monkeypatch)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _FakeCompleted(returncode=0))
    assert system.systemctl_restart() is True


def test_systemctl_restart_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    _force_systemd(monkeypatch)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _FakeCompleted(returncode=1))
    assert system.systemctl_restart() is False


def test_systemctl_restart_off_systemd(monkeypatch: pytest.MonkeyPatch) -> None:
    _force_none(monkeypatch)

    def boom(*_a: Any, **_k: Any) -> _FakeCompleted:
        raise AssertionError("must not shell out off systemd")

    monkeypatch.setattr(subprocess, "run", boom)
    assert system.systemctl_restart() is False


def test_systemctl_start_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _force_systemd(monkeypatch)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _FakeCompleted(returncode=0))
    assert system.systemctl_start() is True


# ── restart_gateway ─────────────────────────────────────────────────────────────


def test_restart_gateway_dry_run(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("DOCKET_NO_RESTART", "1")

    def boom(*_a: Any, **_k: Any) -> _FakeCompleted:
        raise AssertionError("dry-run must not shell out")

    monkeypatch.setattr(subprocess, "run", boom)
    result = system.restart_gateway()
    assert result == system.RestartResult(status="dry_run", ok=True)
    # edges/ never prints (ROADMAP §2) — the cli layer renders the result.
    assert capsys.readouterr().out == ""


def test_restart_gateway_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DOCKET_NO_RESTART", raising=False)
    _force_systemd(monkeypatch)
    monkeypatch.setattr(system, "gateway_active", lambda: True)
    monkeypatch.setattr(system, "systemctl_restart", lambda unit=system.GATEWAY_UNIT: True)
    monkeypatch.setattr(system.time, "sleep", lambda _s: None)
    assert system.restart_gateway() == system.RestartResult(status="restarted", ok=True)


def test_restart_gateway_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DOCKET_NO_RESTART", raising=False)
    _force_systemd(monkeypatch)
    monkeypatch.setattr(system, "gateway_active", lambda: True)
    monkeypatch.setattr(system, "systemctl_restart", lambda unit=system.GATEWAY_UNIT: False)
    result = system.restart_gateway()
    assert result.ok is False
    assert result.status == "failed"
    assert result.hint  # service_hint('status') text, rendered by cli/


def test_restart_gateway_not_running_returns_true(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DOCKET_NO_RESTART", raising=False)
    _force_systemd(monkeypatch)
    monkeypatch.setattr(system, "gateway_active", lambda: False)

    def boom(*_a: Any, **_k: Any) -> bool:
        raise AssertionError("must not restart a stopped service")

    monkeypatch.setattr(system, "systemctl_restart", boom)
    result = system.restart_gateway()
    assert result.ok is True
    assert result.status == "not_running"
    assert result.hint  # service_hint('start') text, rendered by cli/


def test_restart_gateway_no_systemd_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """Off systemd, gateway_active is False so restart is a graceful no-op."""
    monkeypatch.delenv("DOCKET_NO_RESTART", raising=False)
    _force_none(monkeypatch)

    def boom(*_a: Any, **_k: Any) -> _FakeCompleted:
        raise AssertionError("no systemctl off systemd")

    monkeypatch.setattr(subprocess, "run", boom)
    # gateway_active() -> systemctl_is_active() -> False off systemd, no shell-out.
    result = system.restart_gateway()
    assert result.ok is True
    assert result.status == "not_running"


# ── docker ──────────────────────────────────────────────────────────────────────


def test_docker_available_true(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(system, "_which", lambda b: b == "docker")
    assert system.docker_available() is True


def test_docker_available_false(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(system, "_which", lambda b: False)
    assert system.docker_available() is False


def test_docker_ps_returns_names(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(system, "docker_available", lambda: True)
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: _FakeCompleted(returncode=0, stdout="alpha\nbeta\n\n"),
    )
    assert system.docker_ps() == ["alpha", "beta"]


def test_docker_ps_empty_when_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(system, "docker_available", lambda: False)
    assert system.docker_ps() == []


def test_docker_ps_handles_daemon_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(system, "docker_available", lambda: True)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _FakeCompleted(returncode=1))
    assert system.docker_ps() == []


def test_docker_ps_handles_missing_binary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(system, "docker_available", lambda: True)

    def raise_fnf(*_a: Any, **_k: Any) -> _FakeCompleted:
        raise FileNotFoundError

    monkeypatch.setattr(subprocess, "run", raise_fnf)
    assert system.docker_ps() == []


# ── git ─────────────────────────────────────────────────────────────────────────


def test_git_current_branch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(system, "git_available", lambda: True)
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: _FakeCompleted(returncode=0, stdout="main\n"),
    )
    assert system.git_current_branch("/tmp/repo") == "main"


def test_git_current_branch_not_a_repo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(system, "git_available", lambda: True)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _FakeCompleted(returncode=128))
    assert system.git_current_branch("/tmp/notrepo") == ""


def test_git_current_branch_no_git(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(system, "git_available", lambda: False)
    assert system.git_current_branch("/tmp/repo") == ""
