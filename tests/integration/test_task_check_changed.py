"""A task whose diff edits what checks it parks for a person, whatever the profile.

Drives real ``dispatch_pod`` claims against a real git repo with a scripted runner that edits
files in the root the dispatcher hands the implementer hop, then resolves the approval the way
``docket task approve|deny`` does.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from tests.pods import build_pod

from docket.cli import _pod
from docket.core import approval as _ap
from docket.core import audit as _audit
from docket.core import dispatch as _dispatch
from docket.core import fleet as _fleet
from docket.core.runtime_driver import PIPELINE_WORKTREE_ENV, TurnResult
from docket.kernel.home import Home, use_home

SUBJECT = "docket.core.dispatch"

_PIPELINE = (
    "name: two\nsteps:\n  - id: lead\n    role: lead\n  - id: implementer\n    role: implementer\n"
)
_GATED_PIPELINE = (
    "name: gated\nsteps:\n  - id: lead\n    role: lead\n  - id: implementer\n"
    "    role: implementer\n    gate: {type: mechanical, command: 'bash scripts/check.sh'}\n"
)


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
    (path / "package.json").write_text('{"scripts": {"test": "vitest"}}\n')
    (path / "scripts").mkdir()
    (path / "scripts" / "check.sh").write_text("exit 0\n")
    (path / "src").mkdir()
    (path / "src" / "app.js").write_text("console.log(1)\n")
    _git(path, "add", ".")
    _git(path, "commit", "-m", "init")


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOCKET_SERVICE_MANAGER", "none")


@contextmanager
def _seed_pod(tmp_path: Path, repo: Path, pipeline: str = _PIPELINE) -> Iterator[None]:
    home = tmp_path / ".docket"
    (home / "workspaces" / "projects").mkdir(parents=True)
    (home / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    with use_home(Home(home)):
        build_pod("demo", _pod.pod.DEFAULT_POD_ROLES, codebase=str(repo))
        path = _pod.pod.bound_pipeline_path("demo")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(pipeline, encoding="utf-8")
        digest = hashlib.sha256(pipeline.encode("utf-8")).hexdigest()
        _fleet.meta_set(_pod.pod.member_id("demo", "lead"), "pipeline", digest)
        yield


class _Editor:
    """The implementer hop writes ``edits`` into its root and leaves them uncommitted."""

    def __init__(self, edits: dict[str, str]) -> None:
        self.edits = edits

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
            for rel, text in self.edits.items():
                (root / rel).write_text(text)
        return TurnResult(True, "done", 0.0, {})


def _only_task() -> dict[str, object]:
    (task,) = _dispatch.read_tasks("demo")
    return task


def _resolve(token: str, decision: str) -> None:
    if decision == "granted":
        _ap.approval_grant(token, channel="cli")
    else:
        _ap.approval_deny(token, channel="cli", reason="not now")
    _dispatch.resolve_waiting_approval_detail(token, decision, channel="cli", reason="not now")


def _lights_out(monkeypatch: pytest.MonkeyPatch) -> None:
    _fleet.set_profile("lights-out")
    monkeypatch.setattr(_dispatch._profile, "project_violations", lambda project, steps: [])


def test_a_lights_out_task_that_edits_package_json_parks_naming_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    with _seed_pod(tmp_path, repo):
        _lights_out(monkeypatch)
        _dispatch.enqueue_task_once("demo", "bump", channel="cli")

        (res,) = _dispatch.dispatch_pod(
            "demo", runner=_Editor({"package.json": "{}\n"}), max_tasks=1
        )

        task = _only_task()
        assert (res.status, task["status"]) == ("waiting_approval", "waiting_approval")
        assert task["checkChanged"] == ["package.json"]
        assert "package.json" in str(task["reason"])
        record = _ap.approval_get(str(task["approvalToken"]))
        assert record["context"]["kind"] == "check_changed"
        assert record["context"]["paths"] == ["package.json"]


def test_a_grant_ends_the_parked_task_done_and_a_deny_fails_it_check_changed(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    with _seed_pod(tmp_path, repo):
        _dispatch.enqueue_task_once("demo", "bump one", channel="cli")
        _dispatch.enqueue_task_once("demo", "bump two", channel="cli")

        _dispatch.dispatch_pod("demo", runner=_Editor({"package.json": "{}\n"}), max_tasks=2)

        first, second = _dispatch.read_tasks("demo")
        tokens = [str(first["approvalToken"]), str(second["approvalToken"])]
        _resolve(tokens[0], "granted")
        _resolve(tokens[1], "denied")
        granted, denied = _dispatch.read_tasks("demo")
        assert granted["status"] == "done" and "failureKind" not in granted
        assert granted["checkChanged"] == ["package.json"] and not granted.get("approvalToken")
        assert (denied["status"], denied["failureKind"]) == ("failed", "check_changed")
        assert denied["reason"] == "approval denied: not now"
        entries = _audit.read_audit()
        for action, token in (("approval.grant", tokens[0]), ("approval.deny", tokens[1])):
            details = [
                e["detail"] for e in entries if e["action"] == action and token in e["detail"]
            ]
            assert details and "channel=cli" in details[0]


def test_a_task_that_edits_the_script_its_gate_runs_parks(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    with _seed_pod(tmp_path, repo, _GATED_PIPELINE):
        _dispatch.enqueue_task_once("demo", "loosen", channel="cli")

        _dispatch.dispatch_pod(
            "demo", runner=_Editor({"scripts/check.sh": "# nothing to see\nexit 0\n"}), max_tasks=1
        )

        task = _only_task()
        assert task["status"] == "waiting_approval"
        assert task["checkChanged"] == ["scripts/check.sh"]


def test_a_task_that_edits_only_src_ends_done(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    with _seed_pod(tmp_path, repo, _GATED_PIPELINE):
        _dispatch.enqueue_task_once("demo", "feature", channel="cli")

        (res,) = _dispatch.dispatch_pod(
            "demo", runner=_Editor({"src/app.js": "console.log(2)\n"}), max_tasks=1
        )

        task = _only_task()
        assert (res.status, task["status"]) == ("done", "done")
        assert "checkChanged" not in task


def test_a_team_pattern_protects_a_path_the_defaults_do_not(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    with _seed_pod(tmp_path, repo):
        _fleet.meta_set("demo-lead", "protects", "src/*.js")
        _dispatch.enqueue_task_once("demo", "feature", channel="cli")

        _dispatch.dispatch_pod(
            "demo", runner=_Editor({"src/app.js": "console.log(2)\n"}), max_tasks=1
        )

        assert _only_task()["checkChanged"] == ["src/app.js"]
