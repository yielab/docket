"""Verify commands and ``run:`` steps run inside the isolation jail, driven through dispatch.

A command that writes outside the task worktree must fail with isolation on and succeed on the
host with it off; with isolation on and no usable backend nothing runs. See
specs/functional/security-gates.spec.md Exec sandbox item 11.
"""

from __future__ import annotations

import json
import shutil
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from tests.conftest import repoint_docket_home

import docket.config as _cfg
from docket.core import dispatch as _dispatch
from docket.core import fleet as _fleet
from docket.core import pipeline as _pipeline
from docket.core import runtime_driver as _rd
from docket.edges.adapters import system as _sys

SUBJECT = "docket.core.dispatch"

needs_landlock = pytest.mark.skipif(
    not _sys.landlock_available(), reason="Landlock not available on this kernel"
)


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DOCKET_SERVICE_MANAGER", "none")
    monkeypatch.setenv("DOCKET_NO_TRACE", "0")
    home = tmp_path / ".docket"
    (home / "workspaces" / "projects").mkdir(parents=True)
    (home / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    repoint_docket_home(monkeypatch, home)


@pytest.fixture
def outside() -> Iterator[Path]:
    """A directory the jail never grants: under the checkout, not the shared temp dir."""
    path = Path(__file__).resolve().parents[2] / f".envelope-outside-{uuid.uuid4().hex[:8]}"
    path.mkdir()
    yield path
    shutil.rmtree(path, ignore_errors=True)


def _write_meta(member_id: str, extra: dict[str, Any] | None = None) -> None:
    ws = _cfg.PROJECTS_DIR / member_id
    ws.mkdir(parents=True, exist_ok=True)
    meta: dict[str, Any] = {
        "schemaVersion": 1,
        "kind": "project",
        "scope": "project",
        "role": member_id.split("-")[-1],
        "name": member_id,
        "codebase": str(ws),
        "model": "anthropic/claude-haiku-4-5",
        "sessionKey": f"agent:{member_id}:default",
        "projectKey": "default",
        "created": "2026-06-25T00:00:00+00:00",
    }
    if extra:
        meta.update(extra)
    (ws / ".docket-meta.json").write_text(json.dumps(meta))
    _fleet.add_agent(member_id)


def _runner(
    agent_id: str, session_key: str, message: str, timeout: int, env: dict[str, str] | None = None
) -> _rd.TurnResult:
    return _rd.TurnResult(ok=True, output="ok", cost_usd=0.0, raw={})


def _worktree(tmp_path: Path) -> Path:
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    return worktree


def _verify_task(tmp_path: Path, cmd: str) -> dict[str, Any]:
    _write_meta("myapp-lead")
    _write_meta("myapp-implementer", {"codebase": str(tmp_path), "verifyCmd": cmd})
    return {
        "id": "e1",
        "description": "work",
        "status": "pending",
        "worktree": {"dir": str(_worktree(tmp_path)), "branch": "b", "baseCommit": ""},
    }


def _run_step_spec(cmd: str) -> _pipeline.PipelineSpec:
    return _pipeline.PipelineSpec(
        name="checks",
        steps=[_pipeline.Step(id="plan", role="lead"), _pipeline.Step(id="check", run=cmd)],
    )


@pytest.fixture
def isolation_on(monkeypatch: pytest.MonkeyPatch) -> None:
    _fleet.set_sandbox_isolation("on")
    monkeypatch.setenv("DOCKET_SANDBOX_BACKEND", "landlock")


@needs_landlock
def test_verify_writing_outside_the_worktree_fails(
    tmp_path: Path, outside: Path, isolation_on: None
) -> None:
    task = _verify_task(tmp_path, f"touch {outside}/escaped")
    res = _dispatch.dispatch_task("myapp", task, runner=_runner)
    assert res.status == "failed"
    assert not (outside / "escaped").exists()


@needs_landlock
def test_verify_writing_inside_the_worktree_passes(tmp_path: Path, isolation_on: None) -> None:
    task = _verify_task(tmp_path, "touch inside && test -f inside")
    res = _dispatch.dispatch_task("myapp", task, runner=_runner)
    assert res.status == "done", res.reason
    assert (tmp_path / "worktree" / "inside").exists()


@needs_landlock
def test_run_step_writing_outside_the_worktree_fails(
    tmp_path: Path, outside: Path, isolation_on: None
) -> None:
    _write_meta("myapp-lead")
    task = {
        "id": "e2",
        "description": "work",
        "status": "pending",
        "worktree": {"dir": str(_worktree(tmp_path)), "branch": "b", "baseCommit": ""},
    }
    res = _dispatch.dispatch_task(
        "myapp", task, runner=_runner, spec=_run_step_spec(f"touch {outside}/escaped")
    )
    assert res.status == "failed"
    assert not (outside / "escaped").exists()


def test_isolation_on_with_no_backend_runs_nothing(
    tmp_path: Path, outside: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fleet.set_sandbox_isolation("on")
    monkeypatch.setenv("DOCKET_SANDBOX_BACKEND", "none")
    task = _verify_task(tmp_path, f"touch {outside}/escaped")
    res = _dispatch.dispatch_task("myapp", task, runner=_runner)
    assert res.status == "failed"
    assert not (outside / "escaped").exists()


def test_isolation_off_runs_on_the_host(tmp_path: Path, outside: Path) -> None:
    task = _verify_task(tmp_path, f"touch {outside}/host")
    res = _dispatch.dispatch_task("myapp", task, runner=_runner)
    assert res.status == "done", res.reason
    assert (outside / "host").exists()
