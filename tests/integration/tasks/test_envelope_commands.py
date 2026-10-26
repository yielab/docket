"""Verify commands and ``run:`` steps run inside the isolation jail, driven through dispatch.

A command that writes outside the task worktree must fail with isolation on and succeed on the
host with it off; with isolation on and no usable backend nothing runs. See
specs/functional/security-gates.spec.md Exec sandbox item 11.
"""

from __future__ import annotations

import shutil
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from tests.support import home as _support_home
from tests.support.pods import write_meta as _write_meta

from docket.agent import ports as _rd
from docket.hops.application import executor as _executor
from docket.kernel.home import current_home
from docket.pipeline.domain import spec as _pipeline
from docket.pipeline.domain import step as _step
from docket.sandbox import landlock as _landlock
from docket.tasks.domain.parts import Worktree
from docket.tasks.domain.task import TaskRecord
from docket.teams import fleet as _fleet

_hermetic = _support_home.hermetic_trace_on

SUBJECT = "docket.tasks.application.queue"

needs_landlock = pytest.mark.skipif(
    not _landlock.landlock_available(), reason="Landlock not available on this kernel"
)


@pytest.fixture
def outside() -> Iterator[Path]:
    """A directory the jail never grants: under the checkout, not the shared temp dir."""
    path = Path(__file__).resolve().parents[3] / f".envelope-outside-{uuid.uuid4().hex[:8]}"
    path.mkdir()
    yield path
    shutil.rmtree(path, ignore_errors=True)


def _runner(
    agent_id: str, session_key: str, message: str, timeout: int, env: dict[str, str] | None = None
) -> _rd.TurnResult:
    return _rd.TurnResult(ok=True, output="ok", cost_usd=0.0, raw={})


def _worktree(tmp_path: Path) -> Path:
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    return worktree


def _verify_task(tmp_path: Path, cmd: str) -> TaskRecord:
    _write_meta("myapp-lead")
    _write_meta("myapp-implementer", {"codebase": str(tmp_path), "verifyCmd": cmd})
    return TaskRecord(
        id="e1",
        description="work",
        worktree=Worktree(dir=str(_worktree(tmp_path)), branch="b", base_commit=""),
    )


def _run_step_spec(cmd: str) -> _pipeline.PipelineSpec:
    return _pipeline.PipelineSpec(
        name="checks",
        steps=[_step.Step(id="plan", role="lead"), _step.Step(id="check", run=cmd)],
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
    res = _executor.dispatch_task("myapp", task, runner=_runner)
    assert res.status == "failed"
    assert not (outside / "escaped").exists()


@needs_landlock
def test_verify_writing_inside_the_worktree_passes(tmp_path: Path, isolation_on: None) -> None:
    task = _verify_task(tmp_path, "touch inside && test -f inside")
    res = _executor.dispatch_task("myapp", task, runner=_runner)
    assert res.status == "done", res.reason
    assert (tmp_path / "worktree" / "inside").exists()


@needs_landlock
def test_run_step_writing_outside_the_worktree_fails(
    tmp_path: Path, outside: Path, isolation_on: None
) -> None:
    _write_meta("myapp-lead")
    task = TaskRecord(
        id="e2",
        description="work",
        worktree=Worktree(dir=str(_worktree(tmp_path)), branch="b", base_commit=""),
    )
    res = _executor.dispatch_task(
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
    res = _executor.dispatch_task("myapp", task, runner=_runner)
    assert res.status == "failed"
    assert not (outside / "escaped").exists()


def test_isolation_off_runs_on_the_host(tmp_path: Path, outside: Path) -> None:
    task = _verify_task(tmp_path, f"touch {outside}/host")
    res = _executor.dispatch_task("myapp", task, runner=_runner)
    assert res.status == "done", res.reason
    assert (outside / "host").exists()


@needs_landlock
def test_a_jailed_verify_writes_its_home_under_the_pod_cache(
    tmp_path: Path, isolation_on: None
) -> None:
    task = _verify_task(tmp_path, 'touch "$HOME/probe" && test "$UV_CACHE_DIR" = "$HOME"')
    res = _executor.dispatch_task("myapp", task, runner=_runner)
    assert res.status == "done", res.reason
    assert (current_home().pod_cache_dir("myapp") / "probe").exists()


@needs_landlock
def test_a_jailed_verify_reads_a_granted_toolchain_and_cannot_write_it(
    tmp_path: Path, outside: Path, isolation_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    (outside / "tool.txt").write_text("v22")
    reads = f'test "$(cat {outside}/tool.txt)" = v22'
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    denied = _executor.dispatch_task("myapp", _verify_task(first, reads), runner=_runner)
    assert denied.status == "failed"

    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    _fleet.add_read_only(str(outside))
    task = _verify_task(second, f"{reads} && ! touch {outside}/written")
    task.id = "e3"
    res = _executor.dispatch_task("myapp", task, runner=_runner)
    assert res.status == "done", res.reason
    assert not (outside / "written").exists()
