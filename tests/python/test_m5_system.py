"""M5 tests: docket.edges.adapters.system — docker/git wrappers, gateway stub.

These tests fake `subprocess.run` with monkeypatch so no real docker/git is
ever invoked. They cover:
  * gateway_active's honest always-inactive stub
  * docker availability + ps
  * git branch lookup
  * git changed-files probe (W-5b)

There is no daemon gateway to start/restart/probe any more, and no
service_manager/service_hint/systemctl_* helper left that tried to (see
edges/adapters/system.py's module docstring). gateway_active survives as a
stable, always-honest stub because `docket snapshot` and the `serve` read API
still expose a `gateway` field to external consumers
(specs/data/serve-read-api.spec.md) -- covered below. restart_gateway()/
RestartResult were deleted outright rather than kept as a stub: unlike
gateway_active, nothing external ever observed restart_gateway's return
value, so every call site was pure ceremony -- there is accordingly no test
for it here.
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


# ── gateway_active (honest no-op stub) ──────────────────────────────────────────


def test_gateway_active_always_false(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_a: Any, **_k: Any) -> _FakeCompleted:
        raise AssertionError("gateway_active must never shell out -- no daemon exists")

    monkeypatch.setattr(subprocess, "run", boom)
    assert system.gateway_active() is False


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
