"""How ``dispatch_pod`` hands a claimed task to ``hops.workspace.prepare``: skips, the jail, the refusal."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from docket.agent import isolation_posture as _isolation_posture
from docket.agent import loop_trace as _loop_trace
from docket.hops.application import compose as _compose_c
from docket.hops.gates import post_hop as _post_hop_c
from docket.hops.gates import pre_hop as _pre_hop_c
from docket.hops.workspace import prepare as _prepare
from docket.observability import trace as _trace
from docket.pipeline.application import steps as _steps_c
from docket.sandbox import launch as _launch
from docket.tasks.application import actions as _actions_c
from docket.tasks.application import lifecycle as _lifecycle_c
from docket.tasks.application import queue as _queue
from docket.tasks.application import sweep as _sweep_c
from docket.teams import fleet as _fleet
from docket.teams import settings as _settings

SUBJECT = "docket.tasks.application.queue"


@pytest.fixture
def worktree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "wt"
    root.mkdir()
    (root / "package-lock.json").write_text("{}")
    monkeypatch.setattr(_settings, "_pod_settings", lambda project: SimpleNamespace(prepare=""))
    monkeypatch.setattr(_actions_c, "_pod_settings", lambda project: SimpleNamespace(prepare=""))
    monkeypatch.setattr(_queue, "_pod_settings", lambda project: SimpleNamespace(prepare=""))
    monkeypatch.setattr(_lifecycle_c, "_pod_settings", lambda project: SimpleNamespace(prepare=""))
    monkeypatch.setattr(_compose_c, "_pod_settings", lambda project: SimpleNamespace(prepare=""))
    monkeypatch.setattr(_pre_hop_c, "_pod_settings", lambda project: SimpleNamespace(prepare=""))
    monkeypatch.setattr(_post_hop_c, "_pod_settings", lambda project: SimpleNamespace(prepare=""))
    monkeypatch.setattr(_steps_c, "_pod_settings", lambda project: SimpleNamespace(prepare=""))
    monkeypatch.setattr(_fleet, "meta_get", lambda *a, **k: str(tmp_path / "repo"))
    return root


def _task(root: Path, **extra: Any) -> dict[str, Any]:
    return {"id": "t1", "worktree": {"dir": str(root), "commonDir": "/common"}, **extra}


def test_a_task_that_runs_in_place_is_never_prepared(
    worktree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        _prepare, "prepare_worktree", lambda *a: pytest.fail("prepared an in-place task")
    )
    assert _queue._prepare_claimed_task("demo", {"id": "t1", "worktree": {"dir": ""}}) is None
    assert _queue._prepare_claimed_task("demo", {"id": "t1"}) is None


def test_a_task_already_prepared_for_this_lockfile_is_not_prepared_again(
    worktree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = _prepare.resolve(worktree, task_prepare=None, pod_prepare="")
    assert spec is not None
    prepared = _prepare.record(spec, _prepare.PrepareOutcome(True, False, 0, 0.0, ""))
    monkeypatch.setattr(
        _prepare, "prepare_worktree", lambda *a: pytest.fail("prepared a prepared task")
    )
    assert _queue._prepare_claimed_task("demo", _task(worktree, prepared=prepared)) is None


def test_a_failed_install_refuses_the_task_with_the_command_status_and_tail(
    worktree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outcome = _prepare.PrepareOutcome(False, False, 1, 0.5, "x" * 5000 + "TAIL")
    monkeypatch.setattr(_prepare, "prepare_worktree", lambda *a: outcome)
    monkeypatch.setattr(_trace, "trace_event", lambda *a, **k: "written")
    monkeypatch.setattr(_loop_trace, "trace_event", lambda *a, **k: "written")
    seen: list[tuple[str, str]] = []
    monkeypatch.setattr(
        _queue,
        "_refuse_claimed_task",
        lambda project, task, kind, reason: seen.append((kind, reason)) or "refused",
    )
    monkeypatch.setattr(
        _sweep_c,
        "_refuse_claimed_task",
        lambda project, task, kind, reason: seen.append((kind, reason)) or "refused",
    )
    assert _queue._prepare_claimed_task("demo", _task(worktree)) == "refused"
    ((kind, reason),) = seen
    assert kind == "prepare" and reason.startswith("prepare failed: npm ci (exit 1): ")
    assert reason.endswith("TAIL") and len(reason) < 4200


def test_the_install_runs_on_the_host_when_isolation_is_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        _isolation_posture, "resolve_command_jail", lambda project, label: (None, None)
    )
    calls: list[tuple[Any, ...]] = []
    monkeypatch.setattr(_launch, "run_command", lambda *a, **k: calls.append((a, k)) or (0, ""))
    assert _queue._run_prepare_command("demo", "npm ci", "/wt") == (0, "")
    ((args, kwargs),) = calls
    assert args[:2] == ("npm ci", "/wt") and "jail" not in kwargs


def test_a_refused_posture_is_reported_as_not_run(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        _isolation_posture, "resolve_command_jail", lambda project, label: (None, "no backend")
    )
    assert _queue._run_prepare_command("demo", "npm ci", "/wt") == (
        None,
        "[prepare not run: no backend]",
    )
