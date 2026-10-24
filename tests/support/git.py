"""Shared git helpers and fixtures for the docket suite."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from docket.platform import process as _process_adapter


def git(repo: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    )
    return done.stdout.strip()


def pgrep_count(marker: str) -> int:
    result = subprocess.run(["pgrep", "-fc", marker], capture_output=True, text=True)
    return int((result.stdout or "0").strip() or "0")


def git_identity_env(cwd: Path, *args: str) -> str:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
    }
    out = subprocess.run(
        ["git", *args], cwd=cwd, env=env, capture_output=True, text=True, check=True
    )
    return out.stdout.strip()


def git_identity_flags(root: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-C", str(root), "-c", "user.email=t@example.test", "-c", "user.name=t", *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return done.stdout.strip()


def git_quiet(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def repo_dir(tmp_path: Path, files: dict[str, str]) -> Path:
    root = tmp_path / "dotdocket"
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text)
    return root


class GitHost:
    """The operating system under ``platform.git``: whether ``git`` is on PATH, and what running
    it answers. ``available`` and ``run`` are what a test sets; ``run`` defaults to the real
    ``subprocess.run`` so a test that only sets availability still runs real commands."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        real_run, real_which = subprocess.run, _process_adapter.which
        self.available = True
        self.run: Callable[..., Any] = real_run
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: self.run(*a, **k))
        monkeypatch.setattr(
            _process_adapter,
            "which",
            lambda binary: self.available if binary == "git" else real_which(binary),
        )


def hide_git(monkeypatch: pytest.MonkeyPatch, empty_dir: Path) -> None:
    """Make ``git`` unresolvable on PATH, as on a host that never installed it."""
    empty_dir.mkdir(exist_ok=True)
    monkeypatch.setenv("PATH", str(empty_dir))
