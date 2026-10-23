"""The git port: the real adapter and ``FakeGit`` answer the same way.

Run as ``[real, fake]``. A repository is made by the world under test (a real ``git init`` and
commit, or ``FakeGit.add_repo``); everything asserted here is what a caller may rely on.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest
from tests.support.fakes import FakeGit
from tests.support.git import git_2

from docket.kernel.ports import Git
from docket.platform import git as real_git

SUBJECT = "docket.kernel.ports"


@dataclass
class World:
    git: Git
    make_repo: Callable[[Path], tuple[str, str]]  # path -> (branch, head sha)
    modify_tracked: Callable[[Path], None]
    lose_git: Callable[[], None]  # make the binary unavailable


def _real_world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> World:
    def make_repo(path: Path) -> tuple[str, str]:
        path.mkdir()
        git_2(path, "init", "-q", "-b", "main")
        (path / "tracked.txt").write_text("one\n")
        git_2(path, "add", "tracked.txt")
        git_2(path, "-c", "commit.gpgsign=false", "commit", "-q", "-m", "first")
        return "main", git_2(path, "rev-parse", "HEAD")

    def lose_git() -> None:
        empty = tmp_path / "no-bin"
        empty.mkdir(exist_ok=True)
        monkeypatch.setenv("PATH", str(empty))

    def modify(path: Path) -> None:
        (path / "tracked.txt").write_text("two\n")

    return World(real_git, make_repo, modify, lose_git)


def _fake_world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> World:
    fake = FakeGit()

    def make_repo(path: Path) -> tuple[str, str]:
        path.mkdir()
        fake.add_repo(path, branch="main", head="b" * 40, tracked=["tracked.txt"])
        return "main", "b" * 40

    def modify(path: Path) -> None:
        fake.repos[str(path)].changed = ["tracked.txt"]

    def lose_git() -> None:
        fake.available = False

    return World(fake, make_repo, modify, lose_git)


@pytest.fixture(params=["real", "fake"])
def world(request: pytest.FixtureRequest, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> World:
    if request.param == "real" and not real_git.git_available():
        pytest.skip("no git binary on this host")
    return (_real_world if request.param == "real" else _fake_world)(tmp_path, monkeypatch)


def test_a_directory_that_is_not_a_repository_answers_with_neutral_values(
    world: World, tmp_path: Path
) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    cwd, git = str(plain), world.git
    assert git.git_is_repo(cwd) is False
    assert git.git_current_branch(cwd) == ""
    assert git.git_head_sha(cwd) is None
    assert git.git_rev_parse(cwd, "HEAD") is None
    assert git.git_changed_files(cwd) == []
    assert git.git_tracked_files(cwd) == []
    assert git.git_ls_files(cwd) is None


def test_a_repository_reports_its_branch_head_and_tracked_files(
    world: World, tmp_path: Path
) -> None:
    repo = tmp_path / "repo"
    branch, sha = world.make_repo(repo)
    cwd, git = str(repo), world.git
    assert git.git_is_repo(cwd) is True
    assert git.git_current_branch(cwd) == branch
    assert git.git_head_sha(cwd) == sha
    assert git.git_rev_parse(cwd, "HEAD") == sha
    assert git.git_tracked_files(cwd) == ["tracked.txt"]
    assert git.git_ls_files(cwd) == ["tracked.txt"]
    assert git.git_changed_files(cwd) == []


def test_a_modified_tracked_file_is_a_changed_file(world: World, tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    world.make_repo(repo)
    world.modify_tracked(repo)
    assert world.git.git_changed_files(str(repo)) == ["tracked.txt"]


def test_a_host_without_git_answers_with_neutral_values_even_for_a_repository(
    world: World, tmp_path: Path
) -> None:
    repo = tmp_path / "repo"
    world.make_repo(repo)
    world.lose_git()
    cwd, git = str(repo), world.git
    assert git.git_available() is False
    assert git.git_is_repo(cwd) is False
    assert git.git_current_branch(cwd) == ""
    assert git.git_head_sha(cwd) is None
    assert git.git_changed_files(cwd) == []


def test_a_worktree_docket_recorded_is_remembered_by_its_path(world: World, tmp_path: Path) -> None:
    path = tmp_path / "wt"
    path.mkdir()
    assert world.git.trusted_dirs(str(path)) is None
    world.git.trust_worktree(str(path), "/g", "/c")
    assert world.git.trusted_dirs(str(path)) == ("/g", "/c")
