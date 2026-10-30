"""Per-task git worktrees for a pod Implementer.

Acceptance criteria:
  - provision_member() makes no worktree and records no worktree meta.
  - provision_task_worktree() creates <member workspace>/tasks/<task id> on
    docket/<project>/<task id>, recording the creation commit.
  - teardown_member() removes every task worktree and reports unmerged branches.
  - git unavailable or non-repo codebase -> a reason is returned, no crash.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from tests.support.fakes import FakeGit
from tests.support.git import hide_git

from docket.kernel.home import Home, current_home, use_home
from docket.platform import git as _git
from docket.teams.member_workspace import provision_member
from docket.teams.pod import PodMember
from docket.teams.pod_provisioning import teardown_member
from docket.teams.task_worktrees import provision_task_worktree, worktree_branch

SUBJECT = "docket.interfaces.cli.commands.pod"

# ── helpers ────────────────────────────────────────────────────────────────────

_MODEL = "anthropic/claude-haiku-4-5-20251001"


def _make_member(role: str, project: str = "myapp", idx: int = 0) -> PodMember:
    member_id = f"{project}-{role}" + (f"-{idx}" if idx else "")
    return PodMember(
        member_id=member_id,
        role=role,
        project=project,
        model=_MODEL,
        session_key=f"agent:{member_id}:{project}",
        index=idx,
    )


def _init_git_repo(path: Path) -> None:
    """Create a minimal git repo with one commit at ``path``."""
    subprocess.run(["git", "init", str(path)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(path), "config", "user.email", "test@test.com"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(path), "config", "user.name", "Test"],
        check=True,
        capture_output=True,
    )
    (path / "README.md").write_text("hello\n")
    subprocess.run(["git", "-C", str(path), "add", "."], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(path), "commit", "-m", "init"],
        check=True,
        capture_output=True,
    )


FLEET_CONFIG: dict[str, Any] = {
    "agents": [],
    "bindings": [],
    "security": {},
}


@pytest.fixture()
def pod_home(tmp_path: Path) -> Iterator[Path]:
    home = tmp_path / ".docket"
    home.mkdir()
    projects = home / "state" / "workspaces" / "projects"
    projects.mkdir(parents=True)
    fleet_file = home / "state" / "fleet.json"
    fleet_file.write_text(json.dumps(FLEET_CONFIG))
    with use_home(Home(home)):
        yield home


@pytest.fixture()
def git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "myrepo"
    repo.mkdir()
    _init_git_repo(repo)
    return repo


# ── TestWorktreeBranchName ────────────────────────────────────────────────────


class TestWorktreeBranchName:
    def test_format(self) -> None:
        assert worktree_branch("myapp", "task-1") == "docket/myapp/task-1"


# ── TestProvisionTaskWorktree ─────────────────────────────────────────────────


class TestProvisionTaskWorktree:
    def test_non_repo_codebase_fallback(self, tmp_path: Path, pod_home: Path) -> None:
        plain_dir = tmp_path / "notarepo"
        plain_dir.mkdir()
        rec, reason = provision_task_worktree("myapp-implementer", "myapp", "t1", str(plain_dir))
        assert rec == {}
        assert "not a git repo" in reason

    def test_git_unavailable_fallback(
        self, git_repo: Path, pod_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        hide_git(monkeypatch, tmp_path / "no-bin")
        rec, reason = provision_task_worktree("myapp-implementer", "myapp", "t1", str(git_repo))
        assert rec == {}
        assert reason

    def test_worktree_add_failure_fallback(
        self, git_repo: Path, pod_home: Path, fake_git: FakeGit
    ) -> None:
        fake_git.add_repo(git_repo)
        fake_git.git_worktree_add = lambda *a, **k: (False, "some git error")
        rec, reason = provision_task_worktree("myapp-implementer", "myapp", "t1", str(git_repo))
        assert rec == {}
        assert "worktree add failed" in reason

    def test_worktree_created_under_member_tasks_dir(self, git_repo: Path, pod_home: Path) -> None:
        rec, reason = provision_task_worktree("myapp-implementer", "myapp", "t1", str(git_repo))
        assert reason == ""
        assert rec["dir"] == str(current_home().projects_dir / "myapp-implementer" / "tasks" / "t1")
        assert Path(rec["dir"]).is_dir()
        assert rec["branch"] == worktree_branch("myapp", "t1")
        assert _git.git_current_branch(rec["dir"]) == rec["branch"]
        assert rec["baseCommit"] == _git.git_head_sha(str(git_repo))

    def test_two_tasks_get_two_directories(self, git_repo: Path, pod_home: Path) -> None:
        one, _ = provision_task_worktree("myapp-implementer", "myapp", "t1", str(git_repo))
        two, _ = provision_task_worktree("myapp-implementer", "myapp", "t2", str(git_repo))
        assert one["dir"] != two["dir"]
        assert one["branch"] != two["branch"]


# ── TestProvisionMemberMakesNoWorktree ────────────────────────────────────────


class TestProvisionMemberMakesNoWorktree:
    def _provision(self, member: PodMember, codebase: str) -> dict[str, Any]:
        ok, msg = provision_member(
            member,
            codebase=codebase,
            stack="Python",
            description="Test project",
            project=member.project,
            project_key="default",
        )
        assert ok, msg
        return json.loads(
            (current_home().projects_dir / member.member_id / current_home().meta_file).read_text()
        )

    def test_repo_implementer_has_no_worktree(self, git_repo: Path, pod_home: Path) -> None:
        m = _make_member("implementer")
        meta = self._provision(m, str(git_repo))
        assert "worktreeDir" not in meta
        assert "worktreeBranch" not in meta
        assert not (current_home().projects_dir / m.member_id / "tasks").exists()
        listing = subprocess.run(
            ["git", "-C", str(git_repo), "worktree", "list"], capture_output=True, text=True
        ).stdout
        assert len(listing.strip().splitlines()) == 1


# ── TestTeardownMemberWorktree ─────────────────────────────────────────────────


class TestTeardownMemberWorktree:
    def _write_meta(self, ws: Path, meta: dict[str, Any]) -> None:
        ws.mkdir(parents=True, exist_ok=True)
        (ws / current_home().meta_file).write_text(json.dumps(meta))

    def _setup(self, tmp_path: Path, project: str, tasks: tuple[str, ...]) -> tuple[Path, str]:
        repo = tmp_path / f"repo-{project}"
        repo.mkdir()
        _init_git_repo(repo)
        member_id = f"{project}-implementer"
        ws = current_home().projects_dir / member_id
        self._write_meta(ws, {"codebase": str(repo), "pod": project, "role": "implementer"})
        for task in tasks:
            _rec, reason = provision_task_worktree(member_id, project, task, str(repo))
            assert not reason, reason
        return repo, member_id

    def _branches(self, repo: Path) -> str:
        return subprocess.run(
            ["git", "-C", str(repo), "branch", "--list", "docket/*"], capture_output=True, text=True
        ).stdout

    def test_teardown_removes_every_task_worktree(self, tmp_path: Path, pod_home: Path) -> None:
        repo, member_id = self._setup(tmp_path, "proj1", ("t1", "t2"))
        ok, _ = teardown_member(member_id)
        assert ok
        listing = subprocess.run(
            ["git", "-C", str(repo), "worktree", "list"], capture_output=True, text=True
        ).stdout
        assert len(listing.strip().splitlines()) == 1
        assert not (current_home().projects_dir / member_id).exists()

    def test_teardown_without_tasks_dir_no_crash(self, pod_home: Path, fake_git: FakeGit) -> None:
        ws = current_home().projects_dir / "proj2-implementer"
        self._write_meta(ws, {"codebase": "", "role": "implementer"})
        removed: list[tuple[object, ...]] = []
        fake_git.git_worktree_remove = lambda *a: removed.append(a) or (True, "")
        ok, _ = teardown_member("proj2-implementer")
        assert ok
        assert removed == []

    def test_teardown_deletes_merged_branches(self, tmp_path: Path, pod_home: Path) -> None:
        repo, member_id = self._setup(tmp_path, "proj4", ("t1",))
        ok, note = teardown_member(member_id)
        assert ok
        assert note == ""
        assert "docket/proj4/t1" not in self._branches(repo)

    def test_teardown_keeps_unmerged_branch_and_reports_manual_command(
        self, tmp_path: Path, pod_home: Path
    ) -> None:
        repo, member_id = self._setup(tmp_path, "proj5", ("t1", "t2"))
        wt = current_home().projects_dir / member_id / "tasks" / "t1"
        (wt / "extra.txt").write_text("unmerged work\n")
        subprocess.run(["git", "-C", str(wt), "add", "."], check=True, capture_output=True)
        subprocess.run(
            ["git", "-C", str(wt), "commit", "-m", "unmerged"], check=True, capture_output=True
        )
        ok, msg = teardown_member(member_id)
        assert ok
        remaining = self._branches(repo)
        assert "docket/proj5/t1" in remaining
        assert "docket/proj5/t2" not in remaining
        assert "git branch -D docket/proj5/t1" in msg


# ── TestSystemAdapterWorktreeFunctions ───────────────────────────────────────


class TestSystemAdapterWorktreeFunctions:
    def test_git_is_repo_true(self, git_repo: Path) -> None:
        assert _git.git_is_repo(str(git_repo)) is True

    def test_git_is_repo_false(self, tmp_path: Path) -> None:
        plain = tmp_path / "plain"
        plain.mkdir()
        assert _git.git_is_repo(str(plain)) is False

    def test_git_is_repo_nonexistent(self, tmp_path: Path) -> None:
        assert _git.git_is_repo(str(tmp_path / "gone")) is False

    def test_git_worktree_add_creates_branch(self, git_repo: Path, tmp_path: Path) -> None:
        wt = tmp_path / "wt"
        ok, err = _git.git_worktree_add(str(git_repo), str(wt), "docket/test/impl")
        assert ok, err
        assert wt.is_dir()
        branch = _git.git_current_branch(str(wt))
        assert branch == "docket/test/impl"

    def test_git_worktree_add_bad_repo_fails(self, tmp_path: Path) -> None:
        ok, err = _git.git_worktree_add(str(tmp_path), str(tmp_path / "wt"), "branch")
        assert not ok
        assert err != ""

    def test_git_worktree_remove_removes_dir(self, git_repo: Path, tmp_path: Path) -> None:
        wt = tmp_path / "wt2"
        ok, _ = _git.git_worktree_add(str(git_repo), str(wt), "docket/test/rm")
        assert ok
        ok2, err = _git.git_worktree_remove(str(git_repo), str(wt))
        assert ok2, err
        assert not wt.exists()

    def test_git_worktree_remove_nonexistent_fails_gracefully(
        self, git_repo: Path, tmp_path: Path
    ) -> None:
        ok, err = _git.git_worktree_remove(str(git_repo), str(tmp_path / "gone"))
        assert not ok
        assert err != ""

    def test_git_unavailable_worktree_add_fails(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        hide_git(monkeypatch, tmp_path / "no-bin")
        ok, err = _git.git_worktree_add(str(tmp_path), str(tmp_path / "wt"), "b")
        assert not ok
        assert "git not found" in err

    def test_git_unavailable_worktree_remove_fails(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        hide_git(monkeypatch, tmp_path / "no-bin")
        ok, err = _git.git_worktree_remove(str(tmp_path), str(tmp_path / "wt"))
        assert not ok
        assert "git not found" in err

    def test_git_branch_merged_true_for_unmodified_branch(self, git_repo: Path) -> None:
        cur = _git.git_current_branch(str(git_repo))
        subprocess.run(
            ["git", "-C", str(git_repo), "branch", "feat"], check=True, capture_output=True
        )
        assert _git.git_branch_merged(str(git_repo), "feat", cur) is True

    def test_git_branch_merged_false_for_diverged_branch(
        self, git_repo: Path, tmp_path: Path
    ) -> None:
        cur = _git.git_current_branch(str(git_repo))
        wt = tmp_path / "wt3"
        ok, err = _git.git_worktree_add(str(git_repo), str(wt), "feat2")
        assert ok, err
        (wt / "new.txt").write_text("x\n")
        subprocess.run(["git", "-C", str(wt), "add", "."], check=True, capture_output=True)
        subprocess.run(
            ["git", "-C", str(wt), "commit", "-m", "diverge"], check=True, capture_output=True
        )
        assert _git.git_branch_merged(str(git_repo), "feat2", cur) is False

    def test_git_branch_merged_git_unavailable_is_false(
        self, git_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        hide_git(monkeypatch, tmp_path / "no-bin")
        assert _git.git_branch_merged(str(git_repo), "feat", "main") is False

    def test_git_branch_delete_removes_merged_branch(self, git_repo: Path) -> None:
        subprocess.run(
            ["git", "-C", str(git_repo), "branch", "feat3"], check=True, capture_output=True
        )
        ok, err = _git.git_branch_delete(str(git_repo), "feat3")
        assert ok, err
        remaining = subprocess.run(
            ["git", "-C", str(git_repo), "branch", "--list", "feat3"],
            capture_output=True,
            text=True,
        ).stdout
        assert "feat3" not in remaining

    def test_git_branch_delete_refuses_unmerged_branch(
        self, git_repo: Path, tmp_path: Path
    ) -> None:
        wt = tmp_path / "wt4"
        ok, err = _git.git_worktree_add(str(git_repo), str(wt), "feat4")
        assert ok, err
        (wt / "new.txt").write_text("x\n")
        subprocess.run(["git", "-C", str(wt), "add", "."], check=True, capture_output=True)
        subprocess.run(
            ["git", "-C", str(wt), "commit", "-m", "diverge"], check=True, capture_output=True
        )
        _git.git_worktree_remove(str(git_repo), str(wt))
        ok2, err2 = _git.git_branch_delete(str(git_repo), "feat4")
        assert not ok2
        assert err2 != ""

    def test_git_unavailable_branch_delete_fails(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        hide_git(monkeypatch, tmp_path / "no-bin")
        ok, err = _git.git_branch_delete(str(tmp_path), "b")
        assert not ok
        assert "git not found" in err
