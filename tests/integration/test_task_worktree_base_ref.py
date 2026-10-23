"""``provision_task_worktree``: a task's worktree starts from ``base_ref`` when one is given.

Runs real ``git`` against a temporary repository; no model endpoint is involved.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from docket.teams import pod_provisioning as _pp

SUBJECT = "docket.teams.pod_provisioning"


def _git(repo: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    )
    return done.stdout.strip()


def _repo_with_prev_branch(path: Path) -> tuple[str, str]:
    """Init a repo on ``main`` plus branch ``prev`` one commit ahead; HEAD stays on ``main``."""
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "-b", "main", str(path)], check=True, capture_output=True)
    _git(path, "config", "user.email", "t@t.test")
    _git(path, "config", "user.name", "T")
    (path / "a.txt").write_text("a\n")
    _git(path, "add", ".")
    _git(path, "commit", "-m", "init")
    main_sha = _git(path, "rev-parse", "HEAD")
    _git(path, "checkout", "-b", "prev")
    (path / "b.txt").write_text("b\n")
    _git(path, "add", ".")
    _git(path, "commit", "-m", "prev work")
    prev_sha = _git(path, "rev-parse", "HEAD")
    _git(path, "checkout", "main")
    return main_sha, prev_sha


def test_task_worktree_starts_from_base_ref(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    main_sha, prev_sha = _repo_with_prev_branch(repo)

    record, reason = _pp.provision_task_worktree("p-implementer", "p", "t1", str(repo), "prev")

    assert reason == ""
    assert record["baseRef"] == "prev"
    assert record["baseCommit"] == prev_sha != main_sha
    assert _git(Path(record["dir"]), "rev-parse", "HEAD") == prev_sha
    assert (Path(record["dir"]) / "b.txt").is_file()


def test_task_worktree_without_base_ref_starts_from_head(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    main_sha, _ = _repo_with_prev_branch(repo)

    record, reason = _pp.provision_task_worktree("p-implementer", "p", "t1", str(repo))

    assert reason == ""
    assert record["baseCommit"] == main_sha
    assert "baseRef" not in record


def test_unresolvable_base_ref_leaves_no_worktree_or_branch(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _repo_with_prev_branch(repo)

    record, reason = _pp.provision_task_worktree("p-implementer", "p", "t1", str(repo), "nope")

    assert record == {}
    assert "nope" in reason
    assert not (_pp.task_worktrees_dir("p-implementer") / "t1").exists()
    assert _pp.worktree_branch("p", "t1") not in _git(repo, "branch", "--list")
