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
from pathlib import Path
from typing import Any
from unittest import mock

import pytest
from tests.conftest import repoint_docket_home

import docket.config as _cfg
import docket.edges.adapters.system as _sys
from docket.cli._pod import (
    _provision_task_worktree,
    _worktree_branch,
    provision_member,
    teardown_member,
)
from docket.core.pod import PodMember

SUBJECT = "docket.cli._pod"

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
    "security": {"gatesEnabled": False, "isolationEnabled": False},
    "defaults": {"model": ""},
}


@pytest.fixture()
def pod_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / ".docket"
    home.mkdir()
    projects = home / "workspaces" / "projects"
    projects.mkdir(parents=True)
    fleet_file = home / "fleet.json"
    fleet_file.write_text(json.dumps(FLEET_CONFIG))
    repoint_docket_home(monkeypatch, home)
    return home


@pytest.fixture()
def git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "myrepo"
    repo.mkdir()
    _init_git_repo(repo)
    return repo


# ── TestWorktreeBranchName ────────────────────────────────────────────────────


class TestWorktreeBranchName:
    def test_format(self) -> None:
        assert _worktree_branch("myapp", "task-1") == "docket/myapp/task-1"


# ── TestProvisionTaskWorktree ─────────────────────────────────────────────────


class TestProvisionTaskWorktree:
    def test_non_repo_codebase_fallback(self, tmp_path: Path, pod_home: Path) -> None:
        plain_dir = tmp_path / "notarepo"
        plain_dir.mkdir()
        rec, reason = _provision_task_worktree("myapp-implementer", "myapp", "t1", str(plain_dir))
        assert rec == {}
        assert "not a git repo" in reason

    def test_git_unavailable_fallback(self, git_repo: Path, pod_home: Path) -> None:
        with mock.patch.object(_sys, "git_available", return_value=False):
            rec, reason = _provision_task_worktree(
                "myapp-implementer", "myapp", "t1", str(git_repo)
            )
        assert rec == {}
        assert reason

    def test_worktree_add_failure_fallback(self, git_repo: Path, pod_home: Path) -> None:
        with mock.patch.object(_sys, "git_worktree_add", return_value=(False, "some git error")):
            rec, reason = _provision_task_worktree(
                "myapp-implementer", "myapp", "t1", str(git_repo)
            )
        assert rec == {}
        assert "worktree add failed" in reason

    def test_worktree_created_under_member_tasks_dir(self, git_repo: Path, pod_home: Path) -> None:
        rec, reason = _provision_task_worktree("myapp-implementer", "myapp", "t1", str(git_repo))
        assert reason == ""
        assert rec["dir"] == str(_cfg.PROJECTS_DIR / "myapp-implementer" / "tasks" / "t1")
        assert Path(rec["dir"]).is_dir()
        assert rec["branch"] == _worktree_branch("myapp", "t1")
        assert _sys.git_current_branch(rec["dir"]) == rec["branch"]
        assert rec["baseCommit"] == _sys.git_head_sha(str(git_repo))

    def test_two_tasks_get_two_directories(self, git_repo: Path, pod_home: Path) -> None:
        one, _ = _provision_task_worktree("myapp-implementer", "myapp", "t1", str(git_repo))
        two, _ = _provision_task_worktree("myapp-implementer", "myapp", "t2", str(git_repo))
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
        return json.loads((_cfg.PROJECTS_DIR / member.member_id / _cfg.META_FILE).read_text())

    def test_repo_implementer_has_no_worktree(self, git_repo: Path, pod_home: Path) -> None:
        m = _make_member("implementer")
        meta = self._provision(m, str(git_repo))
        assert "worktreeDir" not in meta
        assert "worktreeBranch" not in meta
        assert not (_cfg.PROJECTS_DIR / m.member_id / "tasks").exists()
        listing = subprocess.run(
            ["git", "-C", str(git_repo), "worktree", "list"], capture_output=True, text=True
        ).stdout
        assert len(listing.strip().splitlines()) == 1


# ── TestTeardownMemberWorktree ─────────────────────────────────────────────────


class TestTeardownMemberWorktree:
    def _write_meta(self, ws: Path, meta: dict[str, Any]) -> None:
        ws.mkdir(parents=True, exist_ok=True)
        (ws / _cfg.META_FILE).write_text(json.dumps(meta))

    def _setup(self, tmp_path: Path, project: str, tasks: tuple[str, ...]) -> tuple[Path, str]:
        repo = tmp_path / f"repo-{project}"
        repo.mkdir()
        _init_git_repo(repo)
        member_id = f"{project}-implementer"
        ws = _cfg.PROJECTS_DIR / member_id
        self._write_meta(ws, {"codebase": str(repo), "pod": project, "role": "implementer"})
        for task in tasks:
            _rec, reason = _provision_task_worktree(member_id, project, task, str(repo))
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
        assert not (_cfg.PROJECTS_DIR / member_id).exists()

    def test_teardown_without_tasks_dir_no_crash(self, pod_home: Path) -> None:
        ws = _cfg.PROJECTS_DIR / "proj2-implementer"
        self._write_meta(ws, {"codebase": "", "role": "implementer"})
        with mock.patch.object(_sys, "git_worktree_remove") as remove:
            ok, _ = teardown_member("proj2-implementer")
        assert ok
        remove.assert_not_called()

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
        wt = _cfg.PROJECTS_DIR / member_id / "tasks" / "t1"
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
        assert _sys.git_is_repo(str(git_repo)) is True

    def test_git_is_repo_false(self, tmp_path: Path) -> None:
        plain = tmp_path / "plain"
        plain.mkdir()
        assert _sys.git_is_repo(str(plain)) is False

    def test_git_is_repo_nonexistent(self, tmp_path: Path) -> None:
        assert _sys.git_is_repo(str(tmp_path / "gone")) is False

    def test_git_worktree_add_creates_branch(self, git_repo: Path, tmp_path: Path) -> None:
        wt = tmp_path / "wt"
        ok, err = _sys.git_worktree_add(str(git_repo), str(wt), "docket/test/impl")
        assert ok, err
        assert wt.is_dir()
        branch = _sys.git_current_branch(str(wt))
        assert branch == "docket/test/impl"

    def test_git_worktree_add_bad_repo_fails(self, tmp_path: Path) -> None:
        ok, err = _sys.git_worktree_add(str(tmp_path), str(tmp_path / "wt"), "branch")
        assert not ok
        assert err != ""

    def test_git_worktree_remove_removes_dir(self, git_repo: Path, tmp_path: Path) -> None:
        wt = tmp_path / "wt2"
        ok, _ = _sys.git_worktree_add(str(git_repo), str(wt), "docket/test/rm")
        assert ok
        ok2, err = _sys.git_worktree_remove(str(git_repo), str(wt))
        assert ok2, err
        assert not wt.exists()

    def test_git_worktree_remove_nonexistent_fails_gracefully(
        self, git_repo: Path, tmp_path: Path
    ) -> None:
        ok, err = _sys.git_worktree_remove(str(git_repo), str(tmp_path / "gone"))
        assert not ok
        assert err != ""

    def test_git_unavailable_worktree_add_fails(self, tmp_path: Path) -> None:
        with mock.patch.object(_sys, "git_available", return_value=False):
            ok, err = _sys.git_worktree_add(str(tmp_path), str(tmp_path / "wt"), "b")
        assert not ok
        assert "git not found" in err

    def test_git_unavailable_worktree_remove_fails(self, tmp_path: Path) -> None:
        with mock.patch.object(_sys, "git_available", return_value=False):
            ok, err = _sys.git_worktree_remove(str(tmp_path), str(tmp_path / "wt"))
        assert not ok
        assert "git not found" in err

    def test_git_branch_merged_true_for_unmodified_branch(self, git_repo: Path) -> None:
        cur = _sys.git_current_branch(str(git_repo))
        subprocess.run(
            ["git", "-C", str(git_repo), "branch", "feat"], check=True, capture_output=True
        )
        assert _sys.git_branch_merged(str(git_repo), "feat", cur) is True

    def test_git_branch_merged_false_for_diverged_branch(
        self, git_repo: Path, tmp_path: Path
    ) -> None:
        cur = _sys.git_current_branch(str(git_repo))
        wt = tmp_path / "wt3"
        ok, err = _sys.git_worktree_add(str(git_repo), str(wt), "feat2")
        assert ok, err
        (wt / "new.txt").write_text("x\n")
        subprocess.run(["git", "-C", str(wt), "add", "."], check=True, capture_output=True)
        subprocess.run(
            ["git", "-C", str(wt), "commit", "-m", "diverge"], check=True, capture_output=True
        )
        assert _sys.git_branch_merged(str(git_repo), "feat2", cur) is False

    def test_git_branch_merged_git_unavailable_is_false(self, git_repo: Path) -> None:
        with mock.patch.object(_sys, "git_available", return_value=False):
            assert _sys.git_branch_merged(str(git_repo), "feat", "main") is False

    def test_git_branch_delete_removes_merged_branch(self, git_repo: Path) -> None:
        subprocess.run(
            ["git", "-C", str(git_repo), "branch", "feat3"], check=True, capture_output=True
        )
        ok, err = _sys.git_branch_delete(str(git_repo), "feat3")
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
        ok, err = _sys.git_worktree_add(str(git_repo), str(wt), "feat4")
        assert ok, err
        (wt / "new.txt").write_text("x\n")
        subprocess.run(["git", "-C", str(wt), "add", "."], check=True, capture_output=True)
        subprocess.run(
            ["git", "-C", str(wt), "commit", "-m", "diverge"], check=True, capture_output=True
        )
        _sys.git_worktree_remove(str(git_repo), str(wt))
        ok2, err2 = _sys.git_branch_delete(str(git_repo), "feat4")
        assert not ok2
        assert err2 != ""

    def test_git_unavailable_branch_delete_fails(self, tmp_path: Path) -> None:
        with mock.patch.object(_sys, "git_available", return_value=False):
            ok, err = _sys.git_branch_delete(str(tmp_path), "b")
        assert not ok
        assert "git not found" in err
