"""One git worktree per task: created at claim, recorded on the task, reused on re-entry.

Drives real ``dispatch_pod`` claims against a real git repo with a scripted runner that edits
files in the root the dispatcher hands each hop (``PIPELINE_WORKTREE_ENV``), so the evidence
the hop records is real git output, not a canned answer.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
from tests.conftest import repoint_docket_home

import docket.config as _cfg
from docket.cli import _pod
from docket.core import answers as _answers
from docket.core import dispatch as _dispatch
from docket.core import fleet as _fleet
from docket.core import pod_provisioning as _pp
from docket.core.runtime_driver import PIPELINE_WORKTREE_ENV, TurnResult
from docket.edges.adapters import system as _sys

SUBJECT = "docket.core.dispatch"

_ASK_PIPELINE_YAML = """\
name: ask
steps:
  - id: lead
    role: lead
  - id: ask
    input:
      from: lead
  - id: implementer
    role: implementer
"""


_COORDINATES_PIPELINE_YAML = """\
name: coordinates
steps:
  - id: lead
    role: lead
  - id: implementer
    role: implementer
  - id: coordinates
    run: 'echo "id=$DOCKET_TASK_ID base=$DOCKET_BASE_COMMIT head=$DOCKET_HEAD_COMMIT"'
"""

_NO_IMPLEMENTER_PIPELINE_YAML = """\
name: no-implementer
steps:
  - id: lead
    role: lead
  - id: coordinates
    run: 'echo "id=$DOCKET_TASK_ID base=$DOCKET_BASE_COMMIT head=$DOCKET_HEAD_COMMIT"'
"""


def _git(repo: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    )
    return done.stdout.strip()


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", str(path)], check=True, capture_output=True)
    _git(path, "config", "user.email", "t@t.test")
    _git(path, "config", "user.name", "T")
    (path / "README.md").write_text("hello\n")
    _git(path, "add", ".")
    _git(path, "commit", "-m", "init")


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOCKET_SERVICE_MANAGER", "none")
    monkeypatch.setenv("DOCKET_NO_TRACE", "0")


def _seed_pod(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, codebase: Path) -> None:
    home = tmp_path / ".docket"
    (home / "workspaces" / "projects").mkdir(parents=True)
    (home / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    repoint_docket_home(monkeypatch, home)
    _pod.build_pod("demo", _pod.pod.DEFAULT_POD_ROLES, codebase=str(codebase))


def _bind_pipeline(text: str) -> None:
    path = _pod.pod.bound_pipeline_path("demo")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    _fleet.meta_set(_pod.pod.member_id("demo", "lead"), "pipeline", digest)


class _Runner:
    """Implementer hops write ``<task file>`` into their root and commit it; the roots are kept."""

    def __init__(self, filename: str = "") -> None:
        self.filename = filename
        self.roots: list[str] = []

    def __call__(
        self,
        agent_id: str,
        session_key: str,
        message: str,
        timeout: int,
        env: dict[str, str] | None = None,
    ) -> TurnResult:
        if agent_id.endswith("-implementer"):
            root = Path((env or {})[PIPELINE_WORKTREE_ENV])
            self.roots.append(str(root))
            (root / self.filename).write_text("work\n")
            _git(root, "add", ".")
            _git(root, "commit", "-m", f"add {self.filename}")
        return TurnResult(True, "done", 0.0, {})


def _plain_runner(
    agent_id: str,
    session_key: str,
    message: str,
    timeout: int,
    env: dict[str, str] | None = None,
) -> TurnResult:
    return TurnResult(True, "done", 0.0, {})


def _worktree_paths(repo: Path) -> list[str]:
    lines = _git(repo, "worktree", "list", "--porcelain").splitlines()
    return [line.split(" ", 1)[1] for line in lines if line.startswith("worktree ")]


def test_provisioning_a_repo_pod_creates_no_worktree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    _seed_pod(tmp_path, monkeypatch, repo)
    assert _worktree_paths(repo) == [str(repo.resolve())]
    assert not (_cfg.PROJECTS_DIR / "demo-implementer" / "tasks").exists()


def test_two_tasks_back_to_back_each_get_their_own_branch_and_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    _seed_pod(tmp_path, monkeypatch, repo)

    first = _dispatch.enqueue_task("demo", "first")
    runner_one = _Runner("one.txt")
    (res_one,) = _dispatch.dispatch_pod("demo", runner=runner_one, max_tasks=1)
    assert res_one.status == "done", res_one.reason

    # The codebase moves on between tasks; nothing from task 1 is merged into it.
    (repo / "later.txt").write_text("later\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "later")
    head_at_task_two = _git(repo, "rev-parse", "HEAD")

    second = _dispatch.enqueue_task("demo", "second")
    runner_two = _Runner("two.txt")
    (res_two,) = _dispatch.dispatch_pod("demo", runner=runner_two, max_tasks=1)
    assert res_two.status == "done", res_two.reason

    tasks = {t["id"]: t for t in _dispatch.read_tasks("demo")}
    wt_one = tasks[first["id"]]["worktree"]
    wt_two = tasks[second["id"]]["worktree"]
    tasks_dir = _cfg.PROJECTS_DIR / "demo-implementer" / "tasks"
    assert wt_one["dir"] == str(tasks_dir / first["id"])
    assert wt_two["dir"] == str(tasks_dir / second["id"])
    assert wt_one["branch"] == f"docket/demo/{first['id']}"
    assert wt_two["branch"] == f"docket/demo/{second['id']}"
    assert runner_one.roots == [wt_one["dir"]]
    assert runner_two.roots == [wt_two["dir"]]

    evidence = next(h for h in tasks[second["id"]]["hops"] if h["role"] == "implementer")[
        "evidence"
    ]
    assert evidence["baseCommit"] == wt_two["baseCommit"] == head_at_task_two
    assert evidence["commit"] == _sys.git_head_sha(wt_two["dir"])
    # Task 1's commit is on task 1's branch only: task 2's stat is its own file.
    assert evidence["diffStat"] == {"files": 1, "insertions": 1, "deletions": 0}
    assert "one.txt" not in _git(repo, "ls-tree", "--name-only", wt_two["branch"])


def test_a_parked_then_answered_task_resumes_in_the_same_worktree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    _seed_pod(tmp_path, monkeypatch, repo)
    digest = hashlib.sha256(_ASK_PIPELINE_YAML.encode("utf-8")).hexdigest()
    path = _pod.pod.bound_pipeline_path("demo")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_ASK_PIPELINE_YAML, encoding="utf-8")
    _fleet.meta_set(_pod.pod.member_id("demo", "lead"), "pipeline", digest)

    queued = _dispatch.enqueue_task("demo", "needs a decision")
    runner = _Runner("answer.txt")
    (parked,) = _dispatch.dispatch_pod("demo", runner=runner, max_tasks=1)
    assert parked.status == "waiting_input"
    recorded = _dispatch.read_tasks("demo")[0]["worktree"]
    assert Path(recorded["dir"]).is_dir()
    assert runner.roots == []

    _answers.answer_task(
        "demo", queued["id"], "accept", {"answer": "yes"}, channel="cli", actor="op"
    )
    (done,) = _dispatch.dispatch_pod("demo", runner=runner, max_tasks=1)

    assert done.status == "done", done.reason
    assert runner.roots == [recorded["dir"]]
    assert _dispatch.read_tasks("demo")[0]["worktree"] == recorded
    assert len([p for p in _worktree_paths(repo) if "/tasks/" in p]) == 1


def test_removing_the_member_leaves_no_task_worktree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    _seed_pod(tmp_path, monkeypatch, repo)
    _dispatch.enqueue_task("demo", "first")
    _dispatch.enqueue_task("demo", "second")
    _dispatch.dispatch_pod("demo", runner=_Runner("a.txt"), max_tasks=1)
    _dispatch.dispatch_pod("demo", runner=_Runner("b.txt"), max_tasks=1)
    assert len([p for p in _worktree_paths(repo) if "/tasks/" in p]) == 2

    ok, note = _pp.teardown_member("demo-implementer")

    assert ok
    assert _worktree_paths(repo) == [str(repo.resolve())]
    assert note.count("git branch -D") == 2


def test_worktree_add_failure_runs_in_place_with_a_recorded_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    _seed_pod(tmp_path, monkeypatch, repo)
    monkeypatch.setattr(_sys, "git_worktree_add", lambda *_a: (False, "disk full"))
    seen: list[Any] = []

    def runner(
        agent_id: str,
        session_key: str,
        message: str,
        timeout: int,
        env: dict[str, str] | None = None,
    ) -> TurnResult:
        seen.append((agent_id, env))
        return TurnResult(True, "done", 0.0, {})

    _dispatch.enqueue_task("demo", "work")
    (res,) = _dispatch.dispatch_pod("demo", runner=runner, max_tasks=1)

    assert res.status == "done", res.reason
    record = _dispatch.read_tasks("demo")[0]["worktree"]
    assert record["dir"] == ""
    assert "disk full" in record["fallbackReason"]
    implementer_env = next(env for agent, env in seen if agent.endswith("-implementer"))
    assert PIPELINE_WORKTREE_ENV not in (implementer_env or {})


def test_an_in_place_pod_never_gets_task_worktrees(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    _seed_pod(tmp_path, monkeypatch, repo)
    _fleet.meta_set("demo-implementer", "inPlace", True)

    _dispatch.enqueue_task("demo", "work")
    _dispatch.dispatch_pod("demo", runner=_plain_runner, max_tasks=1)

    assert "worktree" not in _dispatch.read_tasks("demo")[0]
    assert _worktree_paths(repo) == [str(repo.resolve())]


def test_a_command_step_gets_the_task_id_and_the_evidence_commits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    _seed_pod(tmp_path, monkeypatch, repo)
    _bind_pipeline(_COORDINATES_PIPELINE_YAML)

    queued = _dispatch.enqueue_task("demo", "work")
    (res,) = _dispatch.dispatch_pod("demo", runner=_Runner("work.txt"), max_tasks=1)

    assert res.status == "done", res.reason
    task = _dispatch.read_tasks("demo")[0]
    evidence = next(h for h in task["hops"] if h["role"] == "implementer")["evidence"]
    command = next(h for h in task["hops"] if h["role"] == "coordinates")
    assert evidence["baseCommit"] and evidence["commit"]
    assert evidence["baseCommit"] == task["worktree"]["baseCommit"]
    assert command["output"].strip() == (
        f"id={queued['id']} base={evidence['baseCommit']} head={evidence['commit']}"
    )


def test_a_command_step_without_an_implementer_hop_gets_empty_commits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    _seed_pod(tmp_path, monkeypatch, repo)
    _bind_pipeline(_NO_IMPLEMENTER_PIPELINE_YAML)

    queued = _dispatch.enqueue_task("demo", "work")
    (res,) = _dispatch.dispatch_pod("demo", runner=_plain_runner, max_tasks=1)

    assert res.status == "done", res.reason
    command = next(h for h in _dispatch.read_tasks("demo")[0]["hops"] if h["role"] == "coordinates")
    assert command["output"].strip() == f"id={queued['id']} base= head="
