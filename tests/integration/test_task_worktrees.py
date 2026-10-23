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

from docket.cli import _pod
from docket.core import answers as _answers
from docket.core import dispatch as _dispatch
from docket.core import fleet as _fleet
from docket.core import pod_provisioning as _pp
from docket.core.runtime_driver import PIPELINE_WORKTREE_ENV, TurnResult
from docket.edges.adapters import system as _sys
from docket.kernel.home import current_home

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

_CHANGED_PIPELINE_YAML = """\
name: changed
steps:
  - id: lead
    role: lead
  - id: implementer
    role: implementer
  - id: on-text
    when:
      changed: "*.txt"
    run: 'echo ran'
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


class _UncommittedRunner:
    """Implementer hops write files into their root and leave them uncommitted, as a real agent does."""

    def __init__(self, files: dict[str, str]) -> None:
        self.files = files

    def __call__(
        self,
        agent_id: str,
        session_key: str,
        message: str,
        timeout: int,
        env: dict[str, str] | None = None,
    ) -> TurnResult:
        if agent_id.endswith("-implementer"):
            root = Path(
                (env or {}).get(PIPELINE_WORKTREE_ENV) or _fleet.meta_get(agent_id, "codebase")
            )
            for name, body in self.files.items():
                (root / name).write_text(body)
        return TurnResult(True, "done", 0.0, {})


def _implementer_hop(task: dict[str, Any]) -> dict[str, Any]:
    return next(h for h in task["hops"] if h["role"] == "implementer")


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
    assert not (current_home().projects_dir / "demo-implementer" / "tasks").exists()


def test_two_tasks_back_to_back_each_get_their_own_branch_and_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    _seed_pod(tmp_path, monkeypatch, repo)

    first = _dispatch.enqueue_task("demo", "first", channel="cli")
    runner_one = _Runner("one.txt")
    (res_one,) = _dispatch.dispatch_pod("demo", runner=runner_one, max_tasks=1)
    assert res_one.status == "done", res_one.reason

    # The codebase moves on between tasks; nothing from task 1 is merged into it.
    (repo / "later.txt").write_text("later\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "later")
    head_at_task_two = _git(repo, "rev-parse", "HEAD")

    second = _dispatch.enqueue_task("demo", "second", channel="cli")
    runner_two = _Runner("two.txt")
    (res_two,) = _dispatch.dispatch_pod("demo", runner=runner_two, max_tasks=1)
    assert res_two.status == "done", res_two.reason

    tasks = {t["id"]: t for t in _dispatch.read_tasks("demo")}
    wt_one = tasks[first["id"]]["worktree"]
    wt_two = tasks[second["id"]]["worktree"]
    tasks_dir = current_home().projects_dir / "demo-implementer" / "tasks"
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

    queued = _dispatch.enqueue_task("demo", "needs a decision", channel="cli")
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
    _dispatch.enqueue_task("demo", "first", channel="cli")
    _dispatch.enqueue_task("demo", "second", channel="cli")
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

    _dispatch.enqueue_task("demo", "work", channel="cli")
    (res,) = _dispatch.dispatch_pod("demo", runner=runner, max_tasks=1)

    assert res.status == "done", res.reason
    record = _dispatch.read_tasks("demo")[0]["worktree"]
    assert record["dir"] == ""
    assert "disk full" in record["fallbackReason"]
    implementer_env = next(env for agent, env in seen if agent.endswith("-implementer"))
    assert PIPELINE_WORKTREE_ENV not in (implementer_env or {})


def _enqueue_with_base_ref(base_ref: str) -> None:
    from docket.edges import store as _store

    _dispatch.enqueue_task("demo", "continue the work", channel="cli")
    queue = _dispatch.read_tasks("demo")
    queue[0]["baseRef"] = base_ref
    _store.write_json(_dispatch.pod_task_list_path("demo"), {"tasks": queue})


def test_a_task_with_a_base_ref_starts_its_worktree_there(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    _git(repo, "checkout", "-b", "prev")
    (repo / "prev.txt").write_text("previous attempt\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "previous attempt")
    prev_sha = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "-")
    _seed_pod(tmp_path, monkeypatch, repo)
    _enqueue_with_base_ref("prev")

    (res,) = _dispatch.dispatch_pod("demo", runner=_Runner("b.txt"), max_tasks=1)

    assert res.status == "done", res.reason
    record = _dispatch.read_tasks("demo")[0]["worktree"]
    assert record["baseRef"] == "prev"
    assert record["baseCommit"] == prev_sha
    assert (Path(record["dir"]) / "prev.txt").is_file()


def test_an_unresolvable_base_ref_fails_the_task_before_any_hop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    _seed_pod(tmp_path, monkeypatch, repo)
    _enqueue_with_base_ref("nope")
    runner = _Runner("b.txt")

    (res,) = _dispatch.dispatch_pod("demo", runner=runner, max_tasks=1)

    task = _dispatch.read_tasks("demo")[0]
    assert (res.status, res.failure_kind) == ("failed", "base_ref")
    assert task["status"] == "failed"
    assert task["failureKind"] == "base_ref"
    assert "nope" in task["reason"]
    assert task["hops"] == []
    assert "worktree" not in task
    assert runner.roots == []
    assert not (_pp.task_worktrees_dir("demo-implementer") / task["id"]).exists()
    assert _pp.worktree_branch("demo", task["id"]) not in _git(repo, "branch", "--list")


def test_a_failed_worktree_add_with_a_base_ref_does_not_run_in_place(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    _seed_pod(tmp_path, monkeypatch, repo)
    monkeypatch.setattr(_sys, "git_worktree_add", lambda *_a, **_k: (False, "disk full"))
    _enqueue_with_base_ref("HEAD")

    (res,) = _dispatch.dispatch_pod("demo", runner=_Runner("b.txt"), max_tasks=1)

    assert (res.status, res.failure_kind) == ("failed", "base_ref")
    assert "disk full" in _dispatch.read_tasks("demo")[0]["reason"]


def test_a_command_step_gets_the_task_id_and_the_evidence_commits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    _seed_pod(tmp_path, monkeypatch, repo)
    _bind_pipeline(_COORDINATES_PIPELINE_YAML)

    queued = _dispatch.enqueue_task("demo", "work", channel="cli")
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

    queued = _dispatch.enqueue_task("demo", "work", channel="cli")
    (res,) = _dispatch.dispatch_pod("demo", runner=_plain_runner, max_tasks=1)

    assert res.status == "done", res.reason
    command = next(h for h in _dispatch.read_tasks("demo")[0]["hops"] if h["role"] == "coordinates")
    assert command["output"].strip() == f"id={queued['id']} base= head="


def test_uncommitted_work_is_committed_on_the_task_branch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    _seed_pod(tmp_path, monkeypatch, repo)
    _dispatch.enqueue_task("demo", "Add the notes file", channel="cli")

    runner = _UncommittedRunner({"README.md": "changed\n", "notes.txt": "new\n"})
    (res,) = _dispatch.dispatch_pod("demo", runner=runner, max_tasks=1)

    assert res.status == "done", res.reason
    task = _dispatch.read_tasks("demo")[0]
    record = task["worktree"]
    hop = _implementer_hop(task)
    evidence = hop["evidence"]
    assert evidence["commit"] != evidence["baseCommit"] == record["baseCommit"]
    assert evidence["commit"] == _git(repo, "rev-parse", record["branch"])
    assert _git(repo, "log", "-1", "--format=%s", record["branch"]) == "Add the notes file"
    assert evidence["diffStat"] == {"files": 2, "insertions": 2, "deletions": 1}
    assert hop["artifact"]["files_changed"] == ["README.md", "notes.txt"]
    assert _git(Path(record["dir"]), "status", "--porcelain") == ""
    _git(repo, "merge", record["branch"])
    assert (repo / "notes.txt").read_text() == "new\n"


class _LeadWritesRunner:
    """The Lead, a role that is not the Implementer, writes a file and leaves it untracked."""

    def __call__(
        self,
        agent_id: str,
        session_key: str,
        message: str,
        timeout: int,
        env: dict[str, str] | None = None,
    ) -> TurnResult:
        if agent_id.endswith("-lead"):
            root = Path(_dispatch.read_tasks("demo")[0]["worktree"]["dir"])
            (root / "research").mkdir(exist_ok=True)
            (root / "research" / "notes.md").write_text("findings\n")
        return TurnResult(True, "done", 0.0, {})


def test_work_a_non_implementer_hop_leaves_is_committed_on_the_task_branch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A research pipeline has no Implementer; its writer's file must still reach the branch."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    _seed_pod(tmp_path, monkeypatch, repo)
    _bind_pipeline("name: write\nsteps:\n  - id: lead\n    role: lead\n")
    _dispatch.enqueue_task("demo", "Write the notes", channel="cli")

    (res,) = _dispatch.dispatch_pod("demo", runner=_LeadWritesRunner(), max_tasks=1)

    assert res.status == "done", res.reason
    task = _dispatch.read_tasks("demo")[0]
    record = task["worktree"]
    head = _git(repo, "rev-parse", record["branch"])
    assert head != record["baseCommit"]
    assert _git(repo, "show", f"{head}:research/notes.md") == "findings"
    assert "lead hop" in _git(repo, "log", "-1", "--format=%b", record["branch"])
    assert _git(Path(record["dir"]), "status", "--porcelain") == ""
    (hop,) = task["hops"]
    assert hop["artifact"]["files_changed"] == ["research/"]
    assert hop["evidence"] is None


def test_an_unmerged_pinned_task_survives_prune_without_force(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    _seed_pod(tmp_path, monkeypatch, repo)
    _dispatch.enqueue_task("demo", "work", channel="cli")
    _dispatch.dispatch_pod("demo", runner=_UncommittedRunner({"only-new.txt": "x\n"}), max_tasks=1)

    (entry,) = _pp.prune_task_worktrees("demo")

    assert entry.action == "kept"
    assert "not merged" in entry.reason
    assert Path(_dispatch.read_tasks("demo")[0]["worktree"]["dir"], "only-new.txt").is_file()


def test_a_hop_that_changed_nothing_adds_no_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    _seed_pod(tmp_path, monkeypatch, repo)
    _dispatch.enqueue_task("demo", "work", channel="cli")

    _dispatch.dispatch_pod("demo", runner=_plain_runner, max_tasks=1)

    task = _dispatch.read_tasks("demo")[0]
    evidence = _implementer_hop(task)["evidence"]
    assert evidence["commit"] == evidence["baseCommit"]
    assert _git(repo, "rev-parse", task["worktree"]["branch"]) == evidence["baseCommit"]


def test_in_place_work_is_pinned_in_a_snapshot_without_touching_the_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    _seed_pod(tmp_path, monkeypatch, repo)
    monkeypatch.setattr(_sys, "git_worktree_add", lambda *_a, **_k: (False, "forced"))
    head = _git(repo, "rev-parse", "HEAD")
    _bind_pipeline(_COORDINATES_PIPELINE_YAML)
    _dispatch.enqueue_task("demo", "work", channel="cli")

    runner = _UncommittedRunner({"README.md": "changed\n", "notes.txt": "new\n"})
    (res,) = _dispatch.dispatch_pod("demo", runner=runner, max_tasks=1)

    assert res.status == "done", res.reason
    task = _dispatch.read_tasks("demo")[0]
    evidence = _implementer_hop(task)["evidence"]
    assert evidence["baseCommit"] == head != evidence["commit"]
    assert _git(repo, "show", f"{evidence['commit']}:notes.txt") == "new"
    assert _git(repo, "rev-parse", "HEAD") == head
    assert _git(repo, "diff", "--cached", "--name-only") == ""
    assert _git(repo, "diff", "--name-only") == "README.md"
    assert _git(repo, "ls-files", "--others") == "notes.txt"
    command = next(h for h in task["hops"] if h["role"] == "coordinates")
    assert f"head={evidence['commit']}" in command["output"]


def test_the_changed_predicate_sees_work_the_hop_left_uncommitted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    _seed_pod(tmp_path, monkeypatch, repo)
    _bind_pipeline(_CHANGED_PIPELINE_YAML)
    _dispatch.enqueue_task("demo", "work", channel="cli")

    _dispatch.dispatch_pod("demo", runner=_UncommittedRunner({"notes.txt": "x\n"}), max_tasks=1)

    assert [h["role"] for h in _dispatch.read_tasks("demo")[0]["hops"]][-1] == "on-text"


def test_a_failed_pin_records_no_commit_and_an_empty_head(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    _seed_pod(tmp_path, monkeypatch, repo)
    _bind_pipeline(_COORDINATES_PIPELINE_YAML)
    monkeypatch.setattr(_sys, "git_commit_all", lambda *_a, **_k: None)
    queued = _dispatch.enqueue_task("demo", "work", channel="cli")

    _dispatch.dispatch_pod("demo", runner=_UncommittedRunner({"notes.txt": "x\n"}), max_tasks=1)

    task = _dispatch.read_tasks("demo")[0]
    evidence = _implementer_hop(task)["evidence"]
    assert evidence["commit"] is None
    assert evidence["diffStat"] is None
    command = next(h for h in task["hops"] if h["role"] == "coordinates")
    assert command["output"].strip() == (f"id={queued['id']} base={evidence['baseCommit']} head=")
