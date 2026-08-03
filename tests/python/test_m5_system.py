"""M5 tests: docket.edges.adapters.system — docker/git wrappers, gateway stubs.

These tests fake `subprocess.run` with monkeypatch so no real docker/git is
ever invoked. They cover:
  * gateway_active/restart_gateway's honest always-inactive/no-op stubs
  * docker availability + ps
  * git branch lookup
  * git changed-files probe (W-5b)

Phase 19 P19-7b deleted the daemon's gateway systemd unit and every
service_manager/service_hint/systemctl_* helper that only ever existed to
start/restart/probe it -- there is nothing left to manage, so their tests
are deleted, not adapted (see edges/adapters/system.py's module docstring).
gateway_active/restart_gateway survive as stable, always-honest stubs so the
~20 call sites across cli/ that used to restart the gateway need no
individual rewrite; both are covered below for their new behavior.
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


# ── gateway_active / restart_gateway (honest no-op stubs) ──────────────────────


def test_gateway_active_always_false(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_a: Any, **_k: Any) -> _FakeCompleted:
        raise AssertionError("gateway_active must never shell out -- no daemon exists")

    monkeypatch.setattr(subprocess, "run", boom)
    assert system.gateway_active() is False


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


def test_restart_gateway_no_daemon(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DOCKET_NO_RESTART", raising=False)

    def boom(*_a: Any, **_k: Any) -> _FakeCompleted:
        raise AssertionError("no daemon exists -- must not shell out")

    monkeypatch.setattr(subprocess, "run", boom)
    result = system.restart_gateway()
    assert result == system.RestartResult(status="no_daemon", ok=True)


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


# ── git_changed_files (W-5b) ─────────────────────────────────────────────────


def test_git_changed_files_parses_porcelain_output(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(system, "git_available", lambda: True)
    porcelain = " M src/docket/core/dispatch.py\n?? new_file.py\nA  staged.py\n"
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: _FakeCompleted(returncode=0, stdout=porcelain),
    )
    assert system.git_changed_files("/tmp/repo") == [
        "new_file.py",
        "src/docket/core/dispatch.py",
        "staged.py",
    ]


def test_git_changed_files_handles_rename_lines(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(system, "git_available", lambda: True)
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: _FakeCompleted(returncode=0, stdout="R  old_name.py -> new_name.py\n"),
    )
    assert system.git_changed_files("/tmp/repo") == ["new_name.py"]


def test_git_changed_files_empty_clean_tree(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(system, "git_available", lambda: True)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _FakeCompleted(returncode=0, stdout=""))
    assert system.git_changed_files("/tmp/repo") == []


def test_git_changed_files_not_a_repo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(system, "git_available", lambda: True)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _FakeCompleted(returncode=128))
    assert system.git_changed_files("/tmp/notrepo") == []


def test_git_changed_files_no_git(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(system, "git_available", lambda: False)

    def boom(*_a: Any, **_k: Any) -> _FakeCompleted:
        raise AssertionError("must not shell out without git")

    monkeypatch.setattr(subprocess, "run", boom)
    assert system.git_changed_files("/tmp/repo") == []


def test_git_changed_files_handles_missing_binary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(system, "git_available", lambda: True)

    def raise_fnf(*_a: Any, **_k: Any) -> _FakeCompleted:
        raise FileNotFoundError

    monkeypatch.setattr(subprocess, "run", raise_fnf)
    assert system.git_changed_files("/tmp/repo") == []


def test_git_changed_files_handles_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(system, "git_available", lambda: True)

    def raise_timeout(*_a: Any, **_k: Any) -> _FakeCompleted:
        raise subprocess.TimeoutExpired(cmd="git", timeout=5)

    monkeypatch.setattr(subprocess, "run", raise_timeout)
    assert system.git_changed_files("/tmp/repo") == []
