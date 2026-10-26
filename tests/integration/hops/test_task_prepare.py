"""A task's fresh worktree is prepared before its first hop, cached per lockfile, and fails closed.

Drives real ``dispatch_pod`` claims against a real git repo whose ``package-lock.json`` makes
docket derive ``npm ci``; a fake ``npm`` first on PATH installs a local file tree, so nothing
touches the network. The scripted runner reports what the implementer hop sees in its root.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from tests.support.git import git as _git
from tests.support.pods import bind_demo_pipeline as _bind_pipeline
from tests.support.pods import build_pod

from docket.agent.ports import PIPELINE_WORKTREE_ENV, TurnResult
from docket.hops.application import sweep as _sweep
from docket.interfaces.cli.commands import pod as _pod
from docket.kernel.home import Home, current_home, use_home
from docket.observability import trace as _trace
from docket.tasks.application import queue as _queue
from docket.tasks.application.repository import TaskRepository
from docket.teams import fleet as _fleet

SUBJECT = "docket.teams.workspace.prepare"

_FAKE_NPM = """\
#!/bin/sh
echo "$@" >> "$FAKE_NPM_LOG"
[ "$1" = ci ] || exit 2
if grep -q broken package-lock.json; then
  echo "npm ERR! the lockfile is broken" >&2
  exit 1
fi
mkdir -p node_modules/.bin
printf '#!/bin/sh\\necho vitest\\n' > node_modules/.bin/vitest
chmod +x node_modules/.bin/vitest
"""

_LOCK = json.dumps({"lockfileVersion": 3, "packages": {"": {"devDependencies": {"vitest": "1"}}}})


def _init_repo(path: Path, lock: str = _LOCK) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", str(path)], check=True, capture_output=True)
    _git(path, "config", "user.email", "t@t.test")
    _git(path, "config", "user.name", "T")
    (path / "README.md").write_text("hello\n")
    (path / "package-lock.json").write_text(lock)
    _git(path, "add", ".")
    _git(path, "commit", "-m", "init")


@pytest.fixture(autouse=True)
def npm_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    bin_dir = tmp_path / "fakebin"
    bin_dir.mkdir()
    npm = bin_dir / "npm"
    npm.write_text(_FAKE_NPM)
    npm.chmod(npm.stat().st_mode | stat.S_IXUSR)
    log = tmp_path / "npm.log"
    monkeypatch.setenv("FAKE_NPM_LOG", str(log))
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    return log


@contextmanager
def _seed_pod(tmp_path: Path, codebase: Path) -> Iterator[None]:
    home = tmp_path / ".docket"
    (home / "workspaces" / "projects").mkdir(parents=True)
    (home / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    with use_home(Home(home)):
        build_pod("demo", _pod.pod.DEFAULT_POD_ROLES, codebase=str(codebase))
        _bind_pipeline("name: two\nsteps:\n  - lead: lead\n  - implementer: implementer\n")
        yield


class _Runner:
    """Records what the implementer hop finds in its root; never touches the files."""

    def __init__(self) -> None:
        self.seen: list[dict[str, Any]] = []

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
            tool = root / "node_modules" / ".bin" / "vitest"
            self.seen.append({"root": root, "tool": tool.exists()})
        return TurnResult(True, "done", 0.0, {})


def _npm_calls(log: Path) -> list[str]:
    return log.read_text().splitlines() if log.exists() else []


def _prepare_events(task_id: str) -> list[dict[str, Any]]:
    path = current_home().traces_dir / "demo" / f"agent:demo:{task_id}.jsonl"
    return [r for r in _trace.read_trace(path) if r["event_type"] == "prepare"]


def test_the_implementer_hop_finds_the_installed_tool_and_the_task_records_it(
    tmp_path: Path, npm_log: Path
) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    with _seed_pod(tmp_path, repo):
        _queue.enqueue_task_once("demo", "work", channel="cli")
        runner = _Runner()

        (res,) = _sweep.dispatch_pod("demo", runner=runner, max_tasks=1)

        assert res.status == "done", res.reason
        assert [s["tool"] for s in runner.seen] == [True]
        task = TaskRepository.for_pod("demo").list()[0]
        assert task.prepared.command == "npm ci"
        assert task.prepared.source == "lockfile"
        assert task.prepared.cache_hit is False
        assert task.prepared.lock_hash == hashlib.sha256(_LOCK.encode()).hexdigest()
        (event,) = _prepare_events(task.id)
        assert event["payload"]["command"] == "npm ci"
        assert event["payload"]["cacheHit"] is False
        assert event["payload"]["exit"] == 0
        wt = Path(task.worktree.dir)
        assert (wt / "node_modules").is_symlink()
        assert _git(wt, "status", "--porcelain") == ""


def test_a_second_task_with_the_same_lockfile_is_a_cache_hit(tmp_path: Path, npm_log: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    with _seed_pod(tmp_path, repo):
        _queue.enqueue_task_once("demo", "first", channel="cli")
        _queue.enqueue_task_once("demo", "second", channel="cli")
        runner = _Runner()

        results = _sweep.dispatch_pod("demo", runner=runner, max_tasks=2)

        assert [r.status for r in results] == ["done", "done"]
        assert [s["tool"] for s in runner.seen] == [True, True]
        assert _npm_calls(npm_log) == ["ci"]
        tasks = TaskRepository.for_pod("demo").list()
        assert sorted(t.prepared.cache_hit for t in tasks) == [False, True]
        hit = next(t for t in tasks if t.prepared.cache_hit)
        (event,) = _prepare_events(hit.id)
        assert event["payload"]["cacheHit"] is True and event["payload"]["exit"] is None


def test_a_broken_lockfile_fails_the_task_before_any_hop(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo, lock="broken")
    with _seed_pod(tmp_path, repo):
        _queue.enqueue_task_once("demo", "work", channel="cli")
        runner = _Runner()

        (res,) = _sweep.dispatch_pod("demo", runner=runner, max_tasks=1)

        task = TaskRepository.for_pod("demo").list()[0]
        assert (res.status, res.failure_kind) == ("failed", "prepare")
        assert task.failure_kind == "prepare"
        assert "lockfile is broken" in task.reason and "npm ci" in task.reason
        assert task.hops == [] and runner.seen == []
        assert task.prepared is None
        assert [p for p in current_home().prepare_cache_dir.glob("*/*") if p.is_dir()] == []
        (event,) = _prepare_events(task.id)
        assert event["payload"]["exit"] == 1


def test_a_blank_task_prepare_skips_the_install(tmp_path: Path, npm_log: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    with _seed_pod(tmp_path, repo):
        _queue.enqueue_task_once("demo", "work", channel="cli", prepare="")
        runner = _Runner()

        (res,) = _sweep.dispatch_pod("demo", runner=runner, max_tasks=1)

        assert res.status == "done", res.reason
        assert [s["tool"] for s in runner.seen] == [False]
        assert _npm_calls(npm_log) == []
        task = TaskRepository.for_pod("demo").list()[0]
        assert task.prepared is None and _prepare_events(task.id) == []


def test_a_pods_prepare_setting_wins_over_the_lockfile(tmp_path: Path, npm_log: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    with _seed_pod(tmp_path, repo):
        _fleet.meta_set(_pod.pod.member_id("demo", "lead"), "prepare", "none")
        _queue.enqueue_task_once("demo", "work", channel="cli")

        (res,) = _sweep.dispatch_pod("demo", runner=_Runner(), max_tasks=1)

        assert res.status == "done", res.reason
        assert _npm_calls(npm_log) == []
