"""docket.edges.adapters.system — docker/git wrappers.

Fakes `subprocess.run` with monkeypatch so no real docker/git is ever invoked. Covers docker
availability, git branch lookup, and git changed-files probe.
"""

from __future__ import annotations

import subprocess
from typing import Any

import pytest

from docket.edges.adapters import system

SUBJECT = "docket.edges.adapters"


class _FakeCompleted:
    """Minimal stand-in for subprocess.CompletedProcess."""

    def __init__(self, returncode: int = 0, stdout: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = ""


# ── docker ──────────────────────────────────────────────────────────────────────


def test_docker_available_true(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(system, "_which", lambda b: b == "docker")
    assert system.docker_available() is True


def test_docker_available_false(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(system, "_which", lambda b: False)
    assert system.docker_available() is False


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


# ── git_changed_files ────────────────────────────────────────────────────────


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
