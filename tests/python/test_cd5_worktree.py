"""CD-5: Git-worktree-native Implementer isolation.

Acceptance criteria:
  - provision_member() provisions the Implementer's workspace in a git worktree
    when the codebase is a git repo.
  - The worktree path and branch are recorded on the Implementer's meta.
  - teardown_member() calls git_worktree_remove for that worktree.
  - Non-repo pods (task pods, no codebase) are unaffected.
  - Non-Implementer roles (lead, reviewer) are not given worktrees.
  - git unavailable or non-repo codebase → flat-workspace fallback, no crash.
  - suite green.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

import docket.config as _cfg
import docket.edges.adapters.openclaw as _oc
import docket.edges.adapters.system as _sys
from docket.cli._pod import (
    _provision_worktree,
    _worktree_branch,
    provision_member,
    teardown_member,
)
from docket.core.pod import PodMember

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


OC_CONFIG: dict[str, Any] = {
    "agents": {
        "defaults": {"model": ""},
        "list": [],
    },
    "bindings": [],
    "channels": {},
    "security": {"gates": {"enabled": False}, "isolation": {"enabled": False}},
}


@pytest.fixture()
def pod_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    oc_dir = tmp_path / ".openclaw"
    oc_dir.mkdir()
    projects = oc_dir / "workspaces" / "projects"
    projects.mkdir(parents=True)
    config_file = oc_dir / "openclaw.json"
    config_file.write_text(json.dumps(OC_CONFIG))
    monkeypatch.setattr(_cfg, "OPENCLAW_DIR", oc_dir)
    monkeypatch.setattr(_cfg, "CONFIG_FILE", config_file)
    monkeypatch.setattr(_cfg, "PROJECTS_DIR", projects)
    monkeypatch.setattr(_oc, "CONFIG_FILE", config_file)
    monkeypatch.setattr(_sys, "restart_gateway", lambda: None)
    return oc_dir


@pytest.fixture()
def git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "myrepo"
    repo.mkdir()
    _init_git_repo(repo)
    return repo


# ── TestWorktreeBranchName ────────────────────────────────────────────────────


class TestWorktreeBranchName:
    def test_format(self) -> None:
        assert _worktree_branch("myapp", "myapp-implementer") == "docket/myapp/myapp-implementer"

    def test_indexed(self) -> None:
        branch = _worktree_branch("shop", "shop-implementer-2")
        assert branch == "docket/shop/shop-implementer-2"


# ── TestProvisionWorktreeHelper ───────────────────────────────────────────────


class TestProvisionWorktreeHelper:
    def test_non_implementer_skipped(self, git_repo: Path, pod_home: Path) -> None:
        m = _make_member("lead")
        wt, reason = _provision_worktree(m, "myapp", str(git_repo))
        assert wt == ""
        assert reason == ""

    def test_no_codebase_skipped(self, pod_home: Path) -> None:
        m = _make_member("implementer")
        wt, reason = _provision_worktree(m, "myapp", "")
        assert wt == ""
        assert reason == ""

    def test_non_repo_codebase_fallback(self, tmp_path: Path, pod_home: Path) -> None:
        plain_dir = tmp_path / "notarepo"
        plain_dir.mkdir()
        m = _make_member("implementer")
        wt, reason = _provision_worktree(m, "myapp", str(plain_dir))
        assert wt == ""
        assert "not a git repo" in reason

    def test_git_unavailable_fallback(self, git_repo: Path, pod_home: Path) -> None:
        m = _make_member("implementer")
        with mock.patch.object(_sys, "git_available", return_value=False):
            wt, reason = _provision_worktree(m, "myapp", str(git_repo))
        assert wt == ""
        assert "git not found" in reason or "not a git repo" in reason

    def test_worktree_add_failure_fallback(self, git_repo: Path, pod_home: Path) -> None:
        m = _make_member("implementer")
        with mock.patch.object(_sys, "git_worktree_add", return_value=(False, "some git error")):
            wt, reason = _provision_worktree(m, "myapp", str(git_repo))
        assert wt == ""
        assert "worktree add failed" in reason

    def test_worktree_created_for_repo(self, git_repo: Path, pod_home: Path) -> None:
        m = _make_member("implementer")
        wt, reason = _provision_worktree(m, "myapp", str(git_repo))
        assert reason == ""
        assert wt != ""
        assert Path(wt).is_dir()

    def test_worktree_on_correct_branch(self, git_repo: Path, pod_home: Path) -> None:
        m = _make_member("implementer")
        wt, reason = _provision_worktree(m, "myapp", str(git_repo))
        assert reason == ""
        branch = _sys.git_current_branch(wt)
        assert branch == _worktree_branch("myapp", m.member_id)


# ── TestProvisionMemberWorktree ───────────────────────────────────────────────


def _fake_register(member_id: str, ws: str, model: str) -> tuple[bool, str]:
    return True, ""


def _fake_add_agent(member_id: str, model: str, session_key: str, project_key: str) -> None:
    pass


def _fake_sync(member_id: str, session_key: str, project_key: str) -> None:
    pass


class TestProvisionMemberWorktree:
    def _provision(
        self,
        member: PodMember,
        codebase: str,
        projects_dir: Path,
    ) -> dict[str, Any]:
        with (
            mock.patch("shutil.which", return_value=None),
            mock.patch.object(_oc, "add_agent", side_effect=_fake_add_agent),
            mock.patch.object(_oc, "sync_session_key", side_effect=_fake_sync),
        ):
            ok, msg = provision_member(
                member,
                codebase=codebase,
                stack="Python",
                description="Test project",
                project=member.project,
                project_key="default",
            )
        assert ok, msg
        meta_path = projects_dir / member.member_id / _cfg.META_FILE
        return json.loads(meta_path.read_text())

    def test_worktree_dir_in_meta_for_repo(self, git_repo: Path, pod_home: Path) -> None:
        m = _make_member("implementer")
        meta = self._provision(m, str(git_repo), _cfg.PROJECTS_DIR)
        assert "worktreeDir" in meta
        assert "worktreeBranch" in meta
        assert Path(meta["worktreeDir"]).is_dir()

    def test_worktree_branch_value(self, git_repo: Path, pod_home: Path) -> None:
        m = _make_member("implementer")
        meta = self._provision(m, str(git_repo), _cfg.PROJECTS_DIR)
        assert meta["worktreeBranch"] == _worktree_branch("myapp", m.member_id)

    def test_no_worktree_for_task_pod(self, pod_home: Path) -> None:
        m = _make_member("implementer")
        meta = self._provision(m, "", _cfg.PROJECTS_DIR)
        assert "worktreeDir" not in meta
        assert "worktreeBranch" not in meta

    def test_no_worktree_for_lead(self, git_repo: Path, pod_home: Path) -> None:
        m = _make_member("lead")
        meta = self._provision(m, str(git_repo), _cfg.PROJECTS_DIR)
        assert "worktreeDir" not in meta

    def test_fallback_no_worktree_dir_for_non_repo(self, tmp_path: Path, pod_home: Path) -> None:
        plain = tmp_path / "plain"
        plain.mkdir()
        m = _make_member("implementer")
        meta = self._provision(m, str(plain), _cfg.PROJECTS_DIR)
        assert "worktreeDir" not in meta


# ── TestTeardownMemberWorktree ─────────────────────────────────────────────────


class TestTeardownMemberWorktree:
    def _write_meta(self, ws: Path, meta: dict[str, Any]) -> None:
        ws.mkdir(parents=True, exist_ok=True)
        (ws / _cfg.META_FILE).write_text(json.dumps(meta))

    def test_teardown_calls_worktree_remove(self, tmp_path: Path, pod_home: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)
        m = _make_member("implementer")
        ws = _cfg.PROJECTS_DIR / m.member_id
        wt = ws / "worktree"
        # Provision a real worktree so we can tear it down.
        ok, err = _sys.git_worktree_add(str(repo), str(wt), _worktree_branch("myapp", m.member_id))
        assert ok, err
        self._write_meta(
            ws,
            {
                "worktreeDir": str(wt),
                "codebase": str(repo),
                "worktreeBranch": _worktree_branch("myapp", m.member_id),
            },
        )
        with (
            mock.patch("shutil.which", return_value=None),
            mock.patch.object(_oc, "remove_agent"),
        ):
            ok, _ = teardown_member(m.member_id)
        assert ok
        assert not wt.exists()

    def test_teardown_no_worktree_field_no_crash(self, pod_home: Path) -> None:
        m = _make_member("implementer", "proj2")
        ws = _cfg.PROJECTS_DIR / m.member_id
        self._write_meta(ws, {"codebase": "", "role": "implementer"})
        remove_calls: list[str] = []
        with (
            mock.patch("shutil.which", return_value=None),
            mock.patch.object(_oc, "remove_agent"),
            mock.patch.object(_sys, "git_worktree_remove", side_effect=remove_calls.append),
        ):
            ok, _ = teardown_member(m.member_id)
        assert ok
        assert remove_calls == []

    def test_teardown_worktree_remove_failure_does_not_prevent_cleanup(
        self, git_repo: Path, pod_home: Path
    ) -> None:
        m = _make_member("implementer", "proj3")
        ws = _cfg.PROJECTS_DIR / m.member_id
        self._write_meta(
            ws,
            {
                "worktreeDir": "/nonexistent/path",
                "codebase": str(git_repo),
            },
        )
        with (
            mock.patch("shutil.which", return_value=None),
            mock.patch.object(_oc, "remove_agent"),
        ):
            ok, _ = teardown_member(m.member_id)
        assert ok
        assert not ws.exists()


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
