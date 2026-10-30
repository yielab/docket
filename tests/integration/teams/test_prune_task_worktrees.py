"""`docket task prune`: finished task worktrees removed, real git repos."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from tests.support.tasks import put_task, stored_task
from tests.support.tasks import task as _make_task

from docket.kernel.home import Home, current_home, use_home
from docket.tasks.application import worktree_prune
from docket.tasks.application.repository import TaskRepository
from docket.tasks.domain.parts import Worktree
from docket.teams import task_worktrees

SUBJECT = "docket.teams.pod_provisioning"

PROJECT = "myapp"
IMPL = "myapp-implementer"


def _git(path: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", "-C", str(path), *args], check=True, capture_output=True, text=True
    )
    return out.stdout


def _branches(repo: Path) -> set[str]:
    return {b.strip().lstrip("*+ ") for b in _git(repo, "branch").splitlines()}


@pytest.fixture()
def env(tmp_path: Path) -> Iterator[dict[str, Any]]:
    home = tmp_path / ".docket"
    (home / "state" / "workspaces" / "projects").mkdir(parents=True)
    with use_home(Home(home)):
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True)
        _git(repo, "config", "user.email", "t@t.com")
        _git(repo, "config", "user.name", "T")
        (repo / "a.txt").write_text("a\n")
        _git(repo, "add", ".")
        _git(repo, "commit", "-m", "init")
        ws = current_home().projects_dir / IMPL
        ws.mkdir()
        (ws / current_home().meta_file).write_text(
            json.dumps({"codebase": str(repo), "pod": PROJECT})
        )
        lead = current_home().projects_dir / f"{PROJECT}-lead"
        lead.mkdir()
        yield {"repo": repo}


def _add_task(
    env: dict[str, Any], task_id: str, status: str, *, commit: bool = False, **extra: str
) -> dict:
    rec, reason = task_worktrees.provision_task_worktree(IMPL, PROJECT, task_id, str(env["repo"]))
    assert reason == ""
    if commit:
        (Path(rec["dir"]) / f"{task_id}.txt").write_text("work\n")
        _git(Path(rec["dir"]), "add", ".")
        _git(Path(rec["dir"]), "commit", "-m", f"work {task_id}")
    TaskRepository.for_pod(PROJECT).add(
        _make_task(id=task_id, status=status, worktree=rec, **extra)
    )
    return rec


def test_removes_merged_keeps_unmerged_and_untouches_running(env: dict[str, Any]) -> None:
    merged = _add_task(env, "t-merged", "done")
    unmerged = _add_task(env, "t-unmerged", "failed", commit=True)
    running = _add_task(env, "t-running", "running")
    entries = {e.task_id: e for e in worktree_prune.prune_task_worktrees(PROJECT)}
    assert entries["t-merged"].action == "removed"
    assert entries["t-unmerged"].action == "kept"
    assert "not merged" in entries["t-unmerged"].reason
    assert "t-running" not in entries
    assert not Path(merged["dir"]).exists()
    assert merged["branch"] not in _branches(env["repo"])
    assert Path(unmerged["dir"]).is_dir() and unmerged["branch"] in _branches(env["repo"])
    assert Path(running["dir"]).is_dir()
    assert stored_task(PROJECT, "t-merged").worktree.pruned_at
    assert stored_task(PROJECT, "t-unmerged").worktree.pruned_at is None


def test_a_failed_task_dispatch_resume_would_reclaim_keeps_its_worktree(
    env: dict[str, Any],
) -> None:
    rec = _add_task(env, "t-stale", "failed", failure_kind="stale_claim")
    (entry,) = worktree_prune.prune_task_worktrees(PROJECT, force=True)
    assert entry.action == "kept" and "resumable" in entry.reason
    assert Path(rec["dir"]).is_dir()


def test_untracked_artifacts_do_not_keep_a_merged_worktree(env: dict[str, Any]) -> None:
    rec = _add_task(env, "t-cache", "done")
    (Path(rec["dir"]) / "__pycache__").mkdir()
    (Path(rec["dir"]) / "__pycache__" / "calc.pyc").write_text("x")
    (Path(rec["dir"]) / "out.txt").write_text("artifact\n")
    (entry,) = worktree_prune.prune_task_worktrees(PROJECT, dry_run=True)
    assert entry.action == "would-remove" and "2 untracked" in entry.reason
    (entry,) = worktree_prune.prune_task_worktrees(PROJECT)
    assert entry.action == "removed" and "2 untracked" in entry.reason
    assert not Path(rec["dir"]).exists()


def test_dirty_worktree_kept_without_force(env: dict[str, Any]) -> None:
    rec = _add_task(env, "t-dirty", "done")
    (Path(rec["dir"]) / "a.txt").write_text("edited, never committed\n")
    (entry,) = worktree_prune.prune_task_worktrees(PROJECT)
    assert entry.action == "kept" and "uncommitted" in entry.reason
    assert Path(rec["dir"]).is_dir()


def test_dry_run_changes_nothing(env: dict[str, Any]) -> None:
    rec = _add_task(env, "t-merged", "done")
    before = TaskRepository.for_pod(PROJECT).list()
    (entry,) = worktree_prune.prune_task_worktrees(PROJECT, dry_run=True)
    assert entry.action == "would-remove"
    assert Path(rec["dir"]).is_dir() and rec["branch"] in _branches(env["repo"])
    assert TaskRepository.for_pod(PROJECT).list() == before


def test_force_removes_unmerged_and_audits(env: dict[str, Any]) -> None:
    rec = _add_task(env, "t-unmerged", "done", commit=True)
    (entry,) = worktree_prune.prune_task_worktrees(PROJECT, force=True)
    assert entry.action == "removed"
    assert not Path(rec["dir"]).exists()
    assert rec["branch"] in _branches(env["repo"])  # the commits stay reachable
    assert stored_task(PROJECT, "t-unmerged").worktree.pruned_at
    log = current_home().audit_log.read_text()
    assert "pod.worktrees.prune" in log and "t-unmerged" in log


def test_dir_outside_member_tasks_dir_is_never_removed(env: dict[str, Any], tmp_path: Path) -> None:
    victim = tmp_path / "victim"
    victim.mkdir()
    (victim / "keep.txt").write_text("x")
    escaped = current_home().projects_dir / IMPL / "tasks" / ".." / ".." / ".." / ".." / "victim"
    put_task(
        PROJECT,
        _make_task(
            id="t-evil",
            status="done",
            worktree=Worktree(dir=str(escaped), branch="docket/t-evil", base_commit="abc"),
        ),
    )
    (entry,) = worktree_prune.prune_task_worktrees(PROJECT, force=True)
    assert entry.action == "kept"
    assert (victim / "keep.txt").exists()
    assert stored_task(PROJECT, "t-evil").worktree.pruned_at is None


def test_cli_verb_prints_and_rejects_bad_usage(env: dict[str, Any]) -> None:
    from typer.testing import CliRunner

    from docket.interfaces.cli.app import app

    rec = _add_task(env, "t-merged", "done")
    runner = CliRunner()
    dry = runner.invoke(app, ["task", "prune", "--dry-run", "--pod", PROJECT])
    assert dry.exit_code == 0, dry.output
    assert Path(rec["dir"]).is_dir()
    real = runner.invoke(app, ["task", "prune", "--pod", PROJECT])
    assert real.exit_code == 0, real.output
    assert not Path(rec["dir"]).exists()
    assert runner.invoke(app, ["task", "prune", "--frobnicate", "--pod", PROJECT]).exit_code == 2
