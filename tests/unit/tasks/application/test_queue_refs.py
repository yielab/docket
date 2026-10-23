"""One task reference resolves everywhere: full id, short id, prefix, or a run id."""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from docket.hops.application import runner as _runner
from docket.kernel.home import Home, current_home, use_home
from docket.tasks.application import queue as _queue
from docket.tasks.application import queue as _task_ref
from docket.tasks.application import runs as _runs
from docket.tasks.domain import refs as _task_ref_types
from docket.teams import fleet as _fleet
from docket.teams import settings as _settings

SUBJECT = "docket.tasks.application.queue"


@pytest.fixture()
def home(tmp_path: Path) -> Iterator[Path]:
    h = tmp_path / ".docket"
    (h / "workspaces" / "projects").mkdir(parents=True)
    (h / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    with use_home(Home(h)):
        yield h


def _lead(project: str) -> None:
    member = f"{project}-lead"
    ws = current_home().projects_dir / member
    ws.mkdir(parents=True, exist_ok=True)
    meta: dict[str, Any] = {
        "schemaVersion": 1,
        "kind": "project",
        "scope": "project",
        "role": "lead",
        "name": member,
        "codebase": str(ws),
        "model": "anthropic/claude-haiku-4-5",
        "sessionKey": f"agent:{member}:default",
        "projectKey": "default",
        "created": "2026-07-30T00:00:00+00:00",
    }
    (ws / ".docket-meta.json").write_text(json.dumps(meta))
    _fleet.add_agent(member)


def _task(project: str, task_id: str) -> None:
    if not (current_home().projects_dir / f"{project}-lead").exists():
        _lead(project)
    _queue.enqueue_task_once(project, f"work {task_id}", channel="cli")
    path = _settings.pod_task_list_path(project)
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
        expected = _queue.read_tasks("a")[0]["id"]
        assert full.task_id == expected

    def test_session_key_is_the_lead_hop_key(self, two_pods: None) -> None:
        ref = _task_ref.resolve_task("a", "task-04ff2")
        assert ref.session_key == _runner.step_session_key("a-lead", "a", ref.task_id, "lead")

    def test_ambiguous_prefix_lists_every_candidate_with_its_pod(self, two_pods: None) -> None:
        with pytest.raises(_task_ref_types.TaskRefError) as exc:
            _task_ref.resolve_task(None, "task-04ff")
        text = str(exc.value)
        assert "task-04ff2ff5-7be8-aaaa (pod a)" in text
        assert "task-04ff9999-1111-bbbb (pod b)" in text

    def test_pod_scope_disambiguates(self, two_pods: None) -> None:
        assert _task_ref.resolve_task("a", "task-04ff").project == "a"
        assert _task_ref.resolve_task("b", "task-04ff").project == "b"

    def test_unknown_reference_names_what_was_searched(self, two_pods: None) -> None:
        with pytest.raises(_task_ref_types.TaskRefError) as exc:
            _task_ref.resolve_task(None, "task-zzzz")
        assert "task-zzzz" in str(exc.value)
        assert "a, b" in str(exc.value)
        with pytest.raises(_task_ref_types.TaskRefError, match="pod a"):
            _task_ref.resolve_task("a", "task-zzzz")

    def test_empty_reference_is_refused(self, two_pods: None) -> None:
        with pytest.raises(_task_ref_types.TaskRefError):
            _task_ref.resolve_task(None, "  ")


class TestRunIds:
    def test_a_run_id_resolves_to_its_task_and_task_lists_its_runs(
        self, two_pods: None, tmp_path: Path
    ) -> None:
        with use_home(
            dataclasses.replace(current_home(), runs_file_override=tmp_path / "docket-runs.json")
        ):
            task_id = _queue.read_tasks("b")[0]["id"]
            run = _runs.create_run("cli", "b")
            _runs.finish_run(run["id"], state="succeeded", task_ids=[task_id])
            via_run = _task_ref.resolve_task(None, run["id"])
            assert via_run.task_id == task_id
            assert via_run.project == "b"
            assert via_run.run_ids == (run["id"],)
            assert _task_ref.resolve_task("b", "task-04ff").run_ids == (run["id"],)

    def test_run_of_another_pod_or_unknown_run_is_refused(
        self, two_pods: None, tmp_path: Path
    ) -> None:
        with use_home(
            dataclasses.replace(current_home(), runs_file_override=tmp_path / "docket-runs.json")
        ):
            task_id = _queue.read_tasks("b")[0]["id"]
            run = _runs.create_run("cli", "b")
            _runs.finish_run(run["id"], state="succeeded", task_ids=[task_id])
            with pytest.raises(_task_ref_types.TaskRefError, match="pod b"):
                _task_ref.resolve_task("a", run["id"])
            with pytest.raises(_task_ref_types.TaskRefError):
                _task_ref.resolve_task(None, "run-nope")
