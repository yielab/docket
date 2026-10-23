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
from pathlib import Path
from typing import Any

import pytest
from tests.conftest import repoint_docket_home

from docket.cli import _pod
from docket.core import dispatch as _dispatch
from docket.core import fleet as _fleet
from docket.core import trace as _trace
from docket.core.runtime_driver import PIPELINE_WORKTREE_ENV, TurnResult
from docket.kernel.home import current_home

SUBJECT = "docket.core.prepare"

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


def _git(repo: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    )
    return done.stdout.strip()


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
    monkeypatch.setenv("DOCKET_SERVICE_MANAGER", "none")
    monkeypatch.setenv("DOCKET_NO_TRACE", "0")
    bin_dir = tmp_path / "fakebin"
    bin_dir.mkdir()
    npm = bin_dir / "npm"
    npm.write_text(_FAKE_NPM)
    npm.chmod(npm.stat().st_mode | stat.S_IXUSR)
    log = tmp_path / "npm.log"
    monkeypatch.setenv("FAKE_NPM_LOG", str(log))
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    return log


def _seed_pod(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, codebase: Path) -> None:
    home = tmp_path / ".docket"
    (home / "workspaces" / "projects").mkdir(parents=True)
    (home / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    repoint_docket_home(monkeypatch, home)
    _pod.build_pod("demo", _pod.pod.DEFAULT_POD_ROLES, codebase=str(codebase))
    _bind_pipeline(
        "name: two\nsteps:\n  - id: lead\n    role: lead\n  - id: implementer\n    role: implementer\n"
    )


def _bind_pipeline(text: str) -> None:
    path = _pod.pod.bound_pipeline_path("demo")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    _fleet.meta_set(_pod.pod.member_id("demo", "lead"), "pipeline", digest)


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
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, npm_log: Path
) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    _seed_pod(tmp_path, monkeypatch, repo)
    _dispatch.enqueue_task("demo", "work", channel="cli")
    runner = _Runner()

    (res,) = _dispatch.dispatch_pod("demo", runner=runner, max_tasks=1)

    assert res.status == "done", res.reason
    assert [s["tool"] for s in runner.seen] == [True]
    task = _dispatch.read_tasks("demo")[0]
    assert task["prepared"]["command"] == "npm ci"
    assert task["prepared"]["source"] == "lockfile"
    assert task["prepared"]["cacheHit"] is False
    assert task["prepared"]["lockHash"] == hashlib.sha256(_LOCK.encode()).hexdigest()
    (event,) = _prepare_events(task["id"])
    assert event["payload"]["command"] == "npm ci"
    assert event["payload"]["cacheHit"] is False
    assert event["payload"]["exit"] == 0
    wt = Path(task["worktree"]["dir"])
    assert (wt / "node_modules").is_symlink()
    assert _git(wt, "status", "--porcelain") == ""


def test_a_second_task_with_the_same_lockfile_is_a_cache_hit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, npm_log: Path
) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    _seed_pod(tmp_path, monkeypatch, repo)
    _dispatch.enqueue_task("demo", "first", channel="cli")
    _dispatch.enqueue_task("demo", "second", channel="cli")
    runner = _Runner()

    results = _dispatch.dispatch_pod("demo", runner=runner, max_tasks=2)

    assert [r.status for r in results] == ["done", "done"]
    assert [s["tool"] for s in runner.seen] == [True, True]
    assert _npm_calls(npm_log) == ["ci"]
    tasks = _dispatch.read_tasks("demo")
    assert sorted(t["prepared"]["cacheHit"] for t in tasks) == [False, True]
    hit = next(t for t in tasks if t["prepared"]["cacheHit"])
    (event,) = _prepare_events(hit["id"])
    assert event["payload"]["cacheHit"] is True and event["payload"]["exit"] is None


def test_a_broken_lockfile_fails_the_task_before_any_hop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo, lock="broken")
    _seed_pod(tmp_path, monkeypatch, repo)
    _dispatch.enqueue_task("demo", "work", channel="cli")
    runner = _Runner()

    (res,) = _dispatch.dispatch_pod("demo", runner=runner, max_tasks=1)

    task = _dispatch.read_tasks("demo")[0]
    assert (res.status, res.failure_kind) == ("failed", "prepare")
    assert task["failureKind"] == "prepare"
    assert "lockfile is broken" in task["reason"] and "npm ci" in task["reason"]
    assert task["hops"] == [] and runner.seen == []
    assert "prepared" not in task
    assert [p for p in current_home().prepare_cache_dir.glob("*/*") if p.is_dir()] == []
    (event,) = _prepare_events(task["id"])
    assert event["payload"]["exit"] == 1


def test_a_blank_task_prepare_skips_the_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, npm_log: Path
) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    _seed_pod(tmp_path, monkeypatch, repo)
    _dispatch.enqueue_task("demo", "work", channel="cli", prepare="")
    runner = _Runner()

    (res,) = _dispatch.dispatch_pod("demo", runner=runner, max_tasks=1)

    assert res.status == "done", res.reason
    assert [s["tool"] for s in runner.seen] == [False]
    assert _npm_calls(npm_log) == []
    task = _dispatch.read_tasks("demo")[0]
    assert "prepared" not in task and _prepare_events(task["id"]) == []


def test_a_pods_prepare_setting_wins_over_the_lockfile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, npm_log: Path
) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    _seed_pod(tmp_path, monkeypatch, repo)
    _fleet.meta_set(_pod.pod.member_id("demo", "lead"), "prepare", "none")
    _dispatch.enqueue_task("demo", "work", channel="cli")

    (res,) = _dispatch.dispatch_pod("demo", runner=_Runner(), max_tasks=1)

    assert res.status == "done", res.reason
    assert _npm_calls(npm_log) == []
