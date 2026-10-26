"""docket.platform.git, docket.platform.process and docket.sandbox.docker -- docker/git wrappers.

Fakes `subprocess.run` with monkeypatch so no real docker/git is ever invoked. Covers docker
availability, git branch lookup, and git changed-files probe.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest
from tests.support.fakes import FakeProcess
from tests.support.git import GitHost

from docket.platform import git
from docket.sandbox import docker

SUBJECT = "docket.platform.git"


class _FakeCompleted:
    """Minimal stand-in for subprocess.CompletedProcess."""

    def __init__(self, returncode: int = 0, stdout: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = ""


# ── docker ──────────────────────────────────────────────────────────────────────


def test_docker_available_true(fake_process: FakeProcess) -> None:
    fake_process.binaries = {"docker"}
    assert docker.docker_available() is True


def test_docker_available_false(fake_process: FakeProcess) -> None:
    assert docker.docker_available() is False


# ── git ─────────────────────────────────────────────────────────────────────────


def test_git_current_branch(git_host: GitHost) -> None:
    git_host.available = True
    git_host.run = lambda *a, **k: _FakeCompleted(returncode=0, stdout="main\n")
    assert git.git_current_branch("/tmp/repo") == "main"


def test_git_current_branch_not_a_repo(git_host: GitHost) -> None:
    git_host.available = True
    git_host.run = lambda *a, **k: _FakeCompleted(returncode=128)
    assert git.git_current_branch("/tmp/notrepo") == ""


def test_git_current_branch_no_git(git_host: GitHost) -> None:
    git_host.available = False
    assert git.git_current_branch("/tmp/repo") == ""


# ── git_changed_files ────────────────────────────────────────────────────────


def test_git_changed_files_parses_porcelain_output(git_host: GitHost) -> None:
    git_host.available = True
    porcelain = " M src/docket/core/dispatch.py\n?? new_file.py\nA  staged.py\n"
    git_host.run = lambda *a, **k: _FakeCompleted(returncode=0, stdout=porcelain)
    assert git.git_changed_files("/tmp/repo") == [
        "new_file.py",
        "src/docket/core/dispatch.py",
        "staged.py",
    ]


def test_git_changed_files_handles_rename_lines(git_host: GitHost) -> None:
    git_host.available = True
    git_host.run = lambda *a, **k: _FakeCompleted(
        returncode=0, stdout="R  old_name.py -> new_name.py\n"
    )
    assert git.git_changed_files("/tmp/repo") == ["new_name.py"]


def test_git_changed_files_empty_clean_tree(git_host: GitHost) -> None:
    git_host.available = True
    git_host.run = lambda *a, **k: _FakeCompleted(returncode=0, stdout="")
    assert git.git_changed_files("/tmp/repo") == []


def test_git_changed_files_not_a_repo(git_host: GitHost) -> None:
    git_host.available = True
    git_host.run = lambda *a, **k: _FakeCompleted(returncode=128)
    assert git.git_changed_files("/tmp/notrepo") == []


def test_git_changed_files_no_git(git_host: GitHost) -> None:
    git_host.available = False

    def boom(*_a: Any, **_k: Any) -> _FakeCompleted:
        raise AssertionError("must not shell out without git")

    git_host.run = boom
    assert git.git_changed_files("/tmp/repo") == []


def test_git_changed_files_handles_missing_binary(git_host: GitHost) -> None:
    git_host.available = True

    def raise_fnf(*_a: Any, **_k: Any) -> _FakeCompleted:
        raise FileNotFoundError

    git_host.run = raise_fnf
    assert git.git_changed_files("/tmp/repo") == []


def test_git_changed_files_handles_timeout(git_host: GitHost) -> None:
    git_host.available = True

    def raise_timeout(*_a: Any, **_k: Any) -> _FakeCompleted:
        raise subprocess.TimeoutExpired(cmd="git", timeout=5)

    git_host.run = raise_timeout
    assert git.git_changed_files("/tmp/repo") == []


# ── git ls-files ────────────────────────────────────────────────────────────────


def test_git_ls_files_splits_on_nul_and_sorts(
    monkeypatch: pytest.MonkeyPatch, git_host: GitHost
) -> None:
    git_host.available = True
    seen: list[list[str]] = []

    def fake_run(cwd: str, args: list[str], timeout: float, *a: Any, **k: Any) -> _FakeCompleted:
        seen.append(args)
        return _FakeCompleted(0, "src/b.py\0a dir/x.py\0\0")

    monkeypatch.setattr(git, "_git_run", fake_run)

    assert git.git_ls_files("/repo") == ["a dir/x.py", "src/b.py"]
    assert seen == [["ls-files", "-z"]]


def test_git_ls_files_is_none_outside_a_repository(
    monkeypatch: pytest.MonkeyPatch, git_host: GitHost
) -> None:
    git_host.available = True
    monkeypatch.setattr(git, "_git_run", lambda *a, **k: _FakeCompleted(128, ""))
    assert git.git_ls_files("/not-a-repo") is None


def test_git_ls_files_is_none_without_git(git_host: GitHost) -> None:
    git_host.available = False
    assert git.git_ls_files("/repo") is None


def test_git_changed_files_all_untracked_lists_files_in_a_new_directory(tmp_path: Path) -> None:
    """With all_untracked a file inside a new directory is listed by its own path."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "tsconfig.json").write_text("{}\n")
    assert git.git_changed_files(str(tmp_path)) == ["config/"]
    assert git.git_changed_files(str(tmp_path), all_untracked=True) == ["config/tsconfig.json"]
