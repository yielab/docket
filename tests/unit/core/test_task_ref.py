"""One task reference resolves everywhere: full id, short id, prefix, or a run id."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from tests.conftest import repoint_docket_home

import docket.config as _cfg
from docket.core import dispatch as _dispatch
from docket.core import fleet as _fleet
from docket.core import runs as _runs
from docket.core import task_ref as _task_ref

SUBJECT = "docket.core.task_ref"


@pytest.fixture()
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    h = tmp_path / ".docket"
    (h / "workspaces" / "projects").mkdir(parents=True)
    (h / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    repoint_docket_home(monkeypatch, h)
    return h


def _lead(project: str) -> None:
    member = f"{project}-lead"
    ws = _cfg.PROJECTS_DIR / member
    ws.mkdir(parents=True, exist_ok=True)
    meta: dict[str, Any] = {
        "schemaVersion": 1,
        "kind": "project",
        "scope": "project",
        "role": "lead",
        "name": member,
        "codebase": str(ws),
        "model": "anthropic/claude-haiku-4-5",
        "modelSource": "policy",
        "sessionKey": f"agent:{member}:default",
        "projectKey": "default",
        "created": "2026-07-30T00:00:00+00:00",
    }
    (ws / ".docket-meta.json").write_text(json.dumps(meta))
    _fleet.add_agent(member)


def _task(project: str, task_id: str) -> None:
    if not (_cfg.PROJECTS_DIR / f"{project}-lead").exists():
        _lead(project)
    _dispatch.enqueue_task(project, f"work {task_id}")
    path = _dispatch.pod_task_list_path(project)
    doc = json.loads(path.read_text())
    doc["tasks"][-1]["id"] = task_id
    path.write_text(json.dumps(doc))


@pytest.fixture()
def two_pods(home: Path) -> None:
    _task("a", "task-04ff2ff5-7be8-aaaa")
    _task("b", "task-04ff9999-1111-bbbb")


class TestResolveTask:
    def test_full_short_and_prefix_resolve_to_the_same_task(self, two_pods: None) -> None:
        full = _task_ref.resolve_task("a", "task-04ff2ff5-7be8-aaaa")
        assert _task_ref.resolve_task("a", "task-04ff2ff5-7be8") == full
        assert _task_ref.resolve_task(None, "task-04ff2") == full
        assert full.project == "a"
        expected = _dispatch.read_tasks("a")[0]["id"]
        assert full.task_id == expected

    def test_session_key_is_the_lead_hop_key(self, two_pods: None) -> None:
        ref = _task_ref.resolve_task("a", "task-04ff2")
        assert ref.session_key == _dispatch.step_session_key("a-lead", "a", ref.task_id, "lead")

    def test_ambiguous_prefix_lists_every_candidate_with_its_pod(self, two_pods: None) -> None:
        with pytest.raises(_task_ref.TaskRefError) as exc:
            _task_ref.resolve_task(None, "task-04ff")
        text = str(exc.value)
        assert "task-04ff2ff5-7be8-aaaa (pod a)" in text
        assert "task-04ff9999-1111-bbbb (pod b)" in text

    def test_pod_scope_disambiguates(self, two_pods: None) -> None:
        assert _task_ref.resolve_task("a", "task-04ff").project == "a"
        assert _task_ref.resolve_task("b", "task-04ff").project == "b"

    def test_unknown_reference_names_what_was_searched(self, two_pods: None) -> None:
        with pytest.raises(_task_ref.TaskRefError) as exc:
            _task_ref.resolve_task(None, "task-zzzz")
        assert "task-zzzz" in str(exc.value)
        assert "a, b" in str(exc.value)
        with pytest.raises(_task_ref.TaskRefError, match="pod a"):
            _task_ref.resolve_task("a", "task-zzzz")

    def test_empty_reference_is_refused(self, two_pods: None) -> None:
        with pytest.raises(_task_ref.TaskRefError):
            _task_ref.resolve_task(None, "  ")


class TestRunIds:
    def test_a_run_id_resolves_to_its_task_and_task_lists_its_runs(
        self, two_pods: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(_cfg, "RUNS_FILE", tmp_path / "docket-runs.json", raising=True)
        task_id = _dispatch.read_tasks("b")[0]["id"]
        run = _runs.create_run("cli", "b")
        _runs.finish_run(run["id"], state="succeeded", task_ids=[task_id])
        via_run = _task_ref.resolve_task(None, run["id"])
        assert via_run.task_id == task_id
        assert via_run.project == "b"
        assert via_run.run_ids == (run["id"],)
        assert _task_ref.resolve_task("b", "task-04ff").run_ids == (run["id"],)

    def test_run_of_another_pod_or_unknown_run_is_refused(
        self, two_pods: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(_cfg, "RUNS_FILE", tmp_path / "docket-runs.json", raising=True)
        task_id = _dispatch.read_tasks("b")[0]["id"]
        run = _runs.create_run("cli", "b")
        _runs.finish_run(run["id"], state="succeeded", task_ids=[task_id])
        with pytest.raises(_task_ref.TaskRefError, match="pod b"):
            _task_ref.resolve_task("a", run["id"])
        with pytest.raises(_task_ref.TaskRefError):
            _task_ref.resolve_task(None, "run-nope")
