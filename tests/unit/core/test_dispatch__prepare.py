"""How ``dispatch_pod`` hands a claimed task to ``core.prepare``: skips, the jail, the refusal."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from docket.core import dispatch as _dispatch
from docket.core import prepare as _prepare
from docket.edges.adapters import system as _system

SUBJECT = "docket.core.dispatch"


@pytest.fixture
def worktree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "wt"
    root.mkdir()
    (root / "package-lock.json").write_text("{}")
    monkeypatch.setattr(_dispatch, "_pod_settings", lambda project: SimpleNamespace(prepare=""))
    monkeypatch.setattr(_dispatch._fleet, "meta_get", lambda *a, **k: str(tmp_path / "repo"))
    return root


def _task(root: Path, **extra: Any) -> dict[str, Any]:
    return {"id": "t1", "worktree": {"dir": str(root), "commonDir": "/common"}, **extra}


def test_a_task_that_runs_in_place_is_never_prepared(
    worktree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        _prepare, "prepare_worktree", lambda *a: pytest.fail("prepared an in-place task")
    )
    assert _dispatch._prepare_claimed_task("demo", {"id": "t1", "worktree": {"dir": ""}}) is None
    assert _dispatch._prepare_claimed_task("demo", {"id": "t1"}) is None


def test_a_task_already_prepared_for_this_lockfile_is_not_prepared_again(
    worktree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = _prepare.resolve(worktree, task_prepare=None, pod_prepare="")
    assert spec is not None
    prepared = _prepare.record(spec, _prepare.PrepareOutcome(True, False, 0, 0.0, ""))
    monkeypatch.setattr(
        _prepare, "prepare_worktree", lambda *a: pytest.fail("prepared a prepared task")
    )
    assert _dispatch._prepare_claimed_task("demo", _task(worktree, prepared=prepared)) is None


def test_a_failed_install_refuses_the_task_with_the_command_status_and_tail(
    worktree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outcome = _prepare.PrepareOutcome(False, False, 1, 0.5, "x" * 5000 + "TAIL")
    monkeypatch.setattr(_prepare, "prepare_worktree", lambda *a: outcome)
    monkeypatch.setattr(_dispatch._trace, "trace_event", lambda *a, **k: "written")
    seen: list[tuple[str, str]] = []
    monkeypatch.setattr(
        _dispatch,
        "_refuse_claimed_task",
        lambda project, task, kind, reason: seen.append((kind, reason)) or "refused",
    )
    assert _dispatch._prepare_claimed_task("demo", _task(worktree)) == "refused"
    ((kind, reason),) = seen
    assert kind == "prepare" and reason.startswith("prepare failed: npm ci (exit 1): ")
    assert reason.endswith("TAIL") and len(reason) < 4200


def test_the_install_runs_on_the_host_when_isolation_is_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_dispatch._dr, "resolve_command_jail", lambda project, label: (None, None))
    calls: list[tuple[Any, ...]] = []
    monkeypatch.setattr(_system, "run_command", lambda *a, **k: calls.append((a, k)) or (0, ""))
    assert _dispatch._run_prepare_command("demo", "npm ci", "/wt") == (0, "")
    ((args, kwargs),) = calls
    assert args[:2] == ("npm ci", "/wt") and "jail" not in kwargs


def test_the_install_opens_the_network_for_its_own_launch_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pods_jail = _system.JailPolicy(network=False)
    monkeypatch.setattr(
        _dispatch._dr, "resolve_command_jail", lambda project, label: (pods_jail, None)
    )
    seen: list[_system.JailPolicy] = []
    monkeypatch.setattr(_system, "run_command", lambda *a, **k: seen.append(k["jail"]) or (0, ""))
    _dispatch._run_prepare_command("demo", "npm ci", "/wt")
    assert [j.network for j in seen] == [True] and pods_jail.network is False


def test_a_refused_posture_is_reported_as_not_run(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        _dispatch._dr, "resolve_command_jail", lambda project, label: (None, "no backend")
    )
    assert _dispatch._run_prepare_command("demo", "npm ci", "/wt") == (
        None,
        "[prepare not run: no backend]",
    )


def test_a_gate_in_the_jail_reads_the_cache_entry_its_worktree_links_into(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    entry = tmp_path / "entry"
    monkeypatch.setattr(_prepare, "linked_entries", lambda root: (entry,))
    monkeypatch.setattr(
        _dispatch._dr, "resolve_command_jail", lambda project, label: (_system.JailPolicy(), None)
    )
    seen: list[_system.JailPolicy] = []
    monkeypatch.setattr(_system, "run_command", lambda *a, **k: seen.append(k["jail"]) or (0, ""))
    _dispatch._run_in_envelope("demo", "verify", "npx eslint", str(tmp_path), 60)
    assert seen[0].read_only == (entry,)
