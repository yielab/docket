"""`docket task prune`: finished task worktrees removed, real git repos."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
from tests.conftest import repoint_docket_home

import docket.config as _cfg
from docket.core import pod_provisioning as pp

SUBJECT = "docket.core.pod_provisioning"

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
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    home = tmp_path / ".docket"
    (home / "workspaces" / "projects").mkdir(parents=True)
    repoint_docket_home(monkeypatch, home)
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True)
    _git(repo, "config", "user.email", "t@t.com")
    _git(repo, "config", "user.name", "T")
    (repo / "a.txt").write_text("a\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "init")
    ws = _cfg.PROJECTS_DIR / IMPL
    ws.mkdir()
    (ws / _cfg.META_FILE).write_text(json.dumps({"codebase": str(repo), "pod": PROJECT}))
    lead = _cfg.PROJECTS_DIR / f"{PROJECT}-lead"
    lead.mkdir()
    return {"repo": repo, "tasks": lead / "TASK_LIST.json"}


def _add_task(
    env: dict[str, Any], task_id: str, status: str, *, commit: bool = False, **extra: str
) -> dict:
    rec, reason = pp.provision_task_worktree(IMPL, PROJECT, task_id, str(env["repo"]))
    assert reason == ""
    if commit:
        (Path(rec["dir"]) / f"{task_id}.txt").write_text("work\n")
        _git(Path(rec["dir"]), "add", ".")
        _git(Path(rec["dir"]), "commit", "-m", f"work {task_id}")
    path: Path = env["tasks"]
    doc = json.loads(path.read_text()) if path.exists() else {"tasks": []}
    doc["tasks"].append({"id": task_id, "status": status, "worktree": rec, **extra})
    path.write_text(json.dumps(doc))
    return rec


def _task(env: dict[str, Any], task_id: str) -> dict[str, Any]:
    return next(t for t in json.loads(env["tasks"].read_text())["tasks"] if t["id"] == task_id)


def test_removes_merged_keeps_unmerged_and_untouches_running(env: dict[str, Any]) -> None:
    merged = _add_task(env, "t-merged", "done")
    unmerged = _add_task(env, "t-unmerged", "failed", commit=True)
    running = _add_task(env, "t-running", "running")
    entries = {e.task_id: e for e in pp.prune_task_worktrees(PROJECT)}
    assert entries["t-merged"].action == "removed"
    assert entries["t-unmerged"].action == "kept"
    assert "not merged" in entries["t-unmerged"].reason
    assert "t-running" not in entries
    assert not Path(merged["dir"]).exists()
    assert merged["branch"] not in _branches(env["repo"])
    assert Path(unmerged["dir"]).is_dir() and unmerged["branch"] in _branches(env["repo"])
    assert Path(running["dir"]).is_dir()
    assert _task(env, "t-merged")["worktree"]["prunedAt"]
    assert "prunedAt" not in _task(env, "t-unmerged")["worktree"]


def test_a_failed_task_dispatch_resume_would_reclaim_keeps_its_worktree(
    env: dict[str, Any],
) -> None:
    rec = _add_task(env, "t-stale", "failed", failureKind="stale_claim")
    (entry,) = pp.prune_task_worktrees(PROJECT, force=True)
    assert entry.action == "kept" and "resumable" in entry.reason
    assert Path(rec["dir"]).is_dir()


def test_untracked_artifacts_do_not_keep_a_merged_worktree(env: dict[str, Any]) -> None:
    rec = _add_task(env, "t-cache", "done")
    (Path(rec["dir"]) / "__pycache__").mkdir()
    (Path(rec["dir"]) / "__pycache__" / "calc.pyc").write_text("x")
    (Path(rec["dir"]) / "out.txt").write_text("artifact\n")
    (entry,) = pp.prune_task_worktrees(PROJECT, dry_run=True)
    assert entry.action == "would-remove" and "2 untracked" in entry.reason
    (entry,) = pp.prune_task_worktrees(PROJECT)
    assert entry.action == "removed" and "2 untracked" in entry.reason
    assert not Path(rec["dir"]).exists()


def test_dirty_worktree_kept_without_force(env: dict[str, Any]) -> None:
    rec = _add_task(env, "t-dirty", "done")
    (Path(rec["dir"]) / "a.txt").write_text("edited, never committed\n")
    (entry,) = pp.prune_task_worktrees(PROJECT)
    assert entry.action == "kept" and "uncommitted" in entry.reason
    assert Path(rec["dir"]).is_dir()


def test_dry_run_changes_nothing(env: dict[str, Any]) -> None:
    rec = _add_task(env, "t-merged", "done")
    before = env["tasks"].read_text()
    (entry,) = pp.prune_task_worktrees(PROJECT, dry_run=True)
    assert entry.action == "would-remove"
    assert Path(rec["dir"]).is_dir() and rec["branch"] in _branches(env["repo"])
    assert env["tasks"].read_text() == before


def test_force_removes_unmerged_and_audits(env: dict[str, Any]) -> None:
    rec = _add_task(env, "t-unmerged", "done", commit=True)
    (entry,) = pp.prune_task_worktrees(PROJECT, force=True)
    assert entry.action == "removed"
    assert not Path(rec["dir"]).exists()
    assert rec["branch"] in _branches(env["repo"])  # the commits stay reachable
    assert _task(env, "t-unmerged")["worktree"]["prunedAt"]
    log = _cfg.AUDIT_LOG.read_text()
    assert "pod.worktrees.prune" in log and "t-unmerged" in log


def test_dir_outside_member_tasks_dir_is_never_removed(env: dict[str, Any], tmp_path: Path) -> None:
    victim = tmp_path / "victim"
    victim.mkdir()
    (victim / "keep.txt").write_text("x")
    env["tasks"].write_text(
        json.dumps(
            {
                "tasks": [
                    {
                        "id": "t-evil",
                        "status": "done",
                        "worktree": {
                            "dir": str(
                                _cfg.PROJECTS_DIR
                                / IMPL
                                / "tasks"
                                / ".."
                                / ".."
                                / ".."
                                / ".."
                                / "victim"
                            )
                        },
                    }
                ]
            }
        )
    )
    (entry,) = pp.prune_task_worktrees(PROJECT, force=True)
    assert entry.action == "kept"
    assert (victim / "keep.txt").exists()
    assert "prunedAt" not in _task(env, "t-evil")["worktree"]


def test_cli_verb_prints_and_rejects_bad_usage(env: dict[str, Any]) -> None:
    from typer.testing import CliRunner

    from docket.cli import app

    rec = _add_task(env, "t-merged", "done")
    runner = CliRunner()
    dry = runner.invoke(app, ["task", "prune", "--dry-run", "--pod", PROJECT])
    assert dry.exit_code == 0, dry.output
    assert Path(rec["dir"]).is_dir()
    real = runner.invoke(app, ["task", "prune", "--pod", PROJECT])
    assert real.exit_code == 0, real.output
    assert not Path(rec["dir"]).exists()
    assert runner.invoke(app, ["task", "prune", "--frobnicate", "--pod", PROJECT]).exit_code == 2
