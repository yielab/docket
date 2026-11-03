"""An Implementer hop that stops on a transport failure keeps the work it wrote; no other hop does."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from tests.support.pods import build_pod

from docket.agent.ports import PIPELINE_WORKTREE_ENV, FailureKind, TurnResult
from docket.hops.application import sweep as _sweep
from docket.interfaces.cli.commands import pod as _pod
from docket.kernel.home import Home, use_home
from docket.tasks.application import queue as _queue
from docket.tasks.application.repository import TaskRepository
from docket.tasks.domain.task import HopResult

SUBJECT = "docket.tasks.application.record"


def _git(path: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-C", str(path), *args], check=True, capture_output=True, text=True
    )
    return done.stdout


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True)
    subprocess.run(["git", "init", str(path)], check=True, capture_output=True)
    _git(path, "config", "user.email", "t@t.test")
    _git(path, "config", "user.name", "T")
    (path / "README.md").write_text("hello\n")
    _git(path, "add", ".")
    _git(path, "commit", "-m", "init")


@contextmanager
def _seed_pod(tmp_path: Path, roles: tuple[str, ...]) -> Iterator[None]:
    repo = tmp_path / "repo"
    _init_repo(repo)
    home = tmp_path / "home"
    (home / "state" / "workspaces" / "projects").mkdir(parents=True)
    (home / "state" / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    with use_home(Home(home)):
        build_pod("demo", roles, codebase=str(repo))
        yield


class _WritesThenStops:
    """A runner whose *stopping* role writes `<role>.txt` into its tree, then ends on `kind`."""

    def __init__(self, stopping: str, kind: FailureKind) -> None:
        self.stopping = stopping
        self.kind = kind

    def __call__(
        self,
        agent_id: str,
        session_key: str,
        message: str,
        timeout: int,
        env: dict[str, str] | None = None,
    ) -> TurnResult:
        role = agent_id.rsplit("-", 1)[-1]
        if role != self.stopping:
            return TurnResult(True, "done", {})
        root = Path((env or {})[PIPELINE_WORKTREE_ENV])
        (root / "app.txt").write_text("fixed\n")
        return TurnResult(False, "", {}, "stopped", failure_kind=self.kind)


def _run(tmp_path: Path, runner: _WritesThenStops) -> tuple[HopResult, Path, str]:
    _queue.enqueue_task_once("demo", "make app.txt", channel="cli")
    _sweep.dispatch_pod("demo", runner=runner, max_tasks=1)
    task = TaskRepository.for_pod("demo").list()[0]
    hop = next(h for h in task.hops if h.role == runner.stopping)
    return hop, Path(task.worktree.dir), task.worktree.branch


@pytest.mark.parametrize("kind", ["timeout", "daemon_error"])
def test_an_implementer_transport_stop_pins_the_file_it_wrote(
    tmp_path: Path, kind: FailureKind
) -> None:
    """The hop is `ok: false` with its file in the artifact, on a commit, and no `budget`."""
    with _seed_pod(tmp_path, _pod.pod.DEFAULT_POD_ROLES):
        hop, tree, branch = _run(tmp_path, _WritesThenStops("implementer", kind))

        assert hop.ok is False
        assert hop.budget is None
        assert hop.artifact is not None
        assert hop.artifact.files_changed == ["app.txt"]
        assert hop.artifact.diff_ref == branch
        assert hop.evidence is not None and hop.evidence["commit"]
        assert _git(tree, "status", "--porcelain") == ""
        assert "app.txt" in _git(tree, "show", "--name-only", "--format=", branch)


def test_a_reviewer_transport_stop_pins_nothing(tmp_path: Path) -> None:
    """A Reviewer that ends `timeout` leaves its file uncommitted and out of the artifact."""
    with _seed_pod(tmp_path, _pod.pod.FULL_POD_ROLES):
        hop, tree, branch = _run(tmp_path, _WritesThenStops("reviewer", "timeout"))

        assert hop.ok is False
        assert hop.artifact is not None
        assert hop.artifact.files_changed == []
        assert hop.evidence is None
        assert "app.txt" in _git(tree, "status", "--porcelain")
        assert "app.txt" not in _git(tree, "ls-tree", "-r", "--name-only", branch)
