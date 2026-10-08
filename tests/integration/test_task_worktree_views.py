"""`docket task diff` and `docket task prune` against a real git repository and worktree."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
from tests.conftest import record_isolation_off, repoint_docket_home
from typer.testing import CliRunner

from docket.cli import _pod, app
from docket.core import dispatch as _dispatch
from docket.edges import store as _store

SUBJECT = "docket.cli._task"

_runner = CliRunner()


def _git(cwd: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", "-C", str(cwd), "-c", "user.name=t", "-c", "user.email=t@t", *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return out.stdout.strip()


@pytest.fixture()
def seeded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """A done task whose worktree holds an uncommitted change."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / "calc.py").write_text("x = 1\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "base")
    base = _git(repo, "rev-parse", "HEAD")
    home = tmp_path / ".docket"
    (home / "workspaces" / "projects").mkdir(parents=True)
    (home / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    repoint_docket_home(monkeypatch, home)
    record_isolation_off(home)
    _pod.build_pod("demo", _pod.pod.DEFAULT_POD_ROLES, codebase=str(repo))
    wt = tmp_path / "wt"
    _git(repo, "worktree", "add", "-q", "-b", "docket/demo/t1", str(wt), base)
    (wt / "calc.py").write_text("x = 2\n")
    task = _dispatch.enqueue_task("demo", "bump x")
    path = _dispatch.pod_task_list_path("demo")
    doc = _store.read_json(path)
    for t in doc["tasks"]:
        t["status"] = "done"
        t["worktree"] = {"dir": str(wt), "branch": "docket/demo/t1", "baseCommit": base}
    _store.write_json(path, doc)
    return {"id": task["id"], "wt": wt, "base": base}


def test_task_diff_prints_the_uncommitted_change_against_the_base(seeded: dict[str, Any]) -> None:
    result = _runner.invoke(app, ["task", "diff", seeded["id"], "--pod", "demo"])

    assert result.exit_code == 0, result.output
    assert "+x = 2" in result.output


def test_task_show_prints_a_command_that_yields_the_same_diff(seeded: dict[str, Any]) -> None:
    result = _runner.invoke(app, ["task", "show", seeded["id"], "--json", "--pod", "demo"])

    worktree = json.loads(result.output)["task"]["worktree"]
    assert Path(worktree["path"]).is_dir()
    assert "+x = 2" in _git(Path(worktree["path"]), "diff", worktree["baseCommit"])


def test_prune_dry_run_removes_nothing(seeded: dict[str, Any]) -> None:
    result = _runner.invoke(app, ["task", "prune", "--dry-run", "--pod", "demo"])

    assert result.exit_code == 0, result.output
    assert seeded["wt"].exists()


def test_prune_force_without_yes_off_a_tty_refuses(seeded: dict[str, Any]) -> None:
    result = _runner.invoke(app, ["task", "prune", "--force", "--pod", "demo"])

    assert result.exit_code == 1
    assert seeded["wt"].exists()
