"""A task's own ``pipeline`` and ``gate``, run through ``dispatch_pod``: a pod-local pipeline on a
real driver against the loopback stub, and a task gate after the implementer's own ``verifyCmd``.

Spec: pod-dispatch.spec.md "Pipeline order and participation" item 7 and "Generalized gate
execution" item 7.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from tests.support.fakes import FakeDriver
from tests.support.home import record_isolation_off, register_local_provider
from tests.support.model_server import FakeModel, say
from tests.support.pods import build_pod

from docket.hops.application import sweep as _sweep
from docket.interfaces.cli.commands import pod as _pod
from docket.kernel.home import Home, current_home, use_home
from docket.observability import trace as _trace
from docket.tasks.application import queue as _application_queue
from docket.tasks.application.repository import TaskRepository
from docket.teams import fleet as _fleet

SUBJECT = "docket.tasks.application.queue"

_TWO = "name: two\nsteps:\n  - kickoff: lead\n  - assemble: implementer\n"


@pytest.fixture()
def home(tmp_path: Path) -> Iterator[Path]:
    root = tmp_path / ".docket"
    (root / "state" / "workspaces" / "projects").mkdir(parents=True)
    (root / "state" / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    with use_home(Home(root)):
        record_isolation_off(root)
        build_pod("demo", _pod.pod.DEFAULT_POD_ROLES, codebase=str(tmp_path))
        _fleet.meta_set("demo-implementer", "codebase", str(tmp_path))
        yield root


def _pod_pipeline(name: str, text: str) -> None:
    target = current_home().pod_config_dir("demo") / "pipelines"
    target.mkdir(parents=True, exist_ok=True)
    (target / f"{name}.yaml").write_text(text, encoding="utf-8")


def _task_events(task_id: str, event_type: str) -> list[dict[str, Any]]:
    tf = current_home().traces_dir / "demo" / f"agent:demo:{task_id}.jsonl"
    return [e for e in _trace.read_trace(tf) if e["event_type"] == event_type]


@pytest.fixture()
def stub() -> Iterator[FakeModel]:
    with FakeModel(sequence=[say("done, nothing to change")], repeat_last=True) as server:
        yield server


def _queue(**options: Any) -> str:
    return str(
        _application_queue.enqueue_task_once("demo", "ship it", channel="cli", **options)[0].id
    )


class TestPipelineOnTheStubServer:
    def test_a_named_pod_pipeline_runs_two_hops_on_the_real_driver(
        self, home: Path, stub: FakeModel
    ) -> None:
        register_local_provider(
            home,
            "local",
            [{"id": "stub", "contextWindow": 16384, "maxTokens": 4096}],
            stub.base_url,
        )
        for member in ("demo-lead", "demo-implementer"):
            _fleet.meta_set(member, "model", "local/stub")
        _fleet.meta_set("demo-implementer", "verifyCmd", "")
        _pod_pipeline("two", _TWO)
        _queue(pipeline="two")

        results = _sweep.dispatch_pod("demo")

        assert results[0].status == "done", results[0].reason
        assert [h.step_id for h in results[0].hops] == ["kickoff", "assemble"]
        assert len(stub.requests) >= 2
        assert TaskRepository.for_pod("demo").list()[0].pipeline_source == "pod:two"


def _implementer_only(home: Path) -> None:
    _pod_pipeline("build", "name: build\nsteps:\n  - build: implementer\n")


class TestTaskGateAfterVerifyCmd:
    def test_a_failing_task_gate_fails_the_task_after_verify_passed(self, home: Path) -> None:
        _fleet.meta_set("demo-implementer", "verifyCmd", "true")
        _implementer_only(home)
        task_id = _queue(pipeline="build", gate={"command": "false"})

        res = _sweep.dispatch_pod("demo", runner=FakeDriver())[0]

        assert res.status == "failed"
        assert res.failure_kind == "gate_failed"
        verify = res.hops[0].verify
        assert verify["cmd"] == "false"
        assert verify["source"] == "task"
        assert verify["label"] == "fail"
        failed = _task_events(task_id, "verification_failed")
        assert [e["payload"]["source"] for e in failed] == ["task"]
        assert failed[0]["payload"]["cmd"] == "false"
        assert TaskRepository.for_pod("demo").list()[0].gate_applied is True

    def test_a_passing_task_gate_keeps_the_verify_evidence_and_nests_its_own(
        self, home: Path
    ) -> None:
        _fleet.meta_set("demo-implementer", "verifyCmd", "echo verified")
        _implementer_only(home)
        _queue(pipeline="build", gate={"command": "echo accepted"})

        res = _sweep.dispatch_pod("demo", runner=FakeDriver())[0]

        assert res.status == "done", res.reason
        verify = res.hops[0].verify
        assert verify["cmd"] == "echo verified"
        assert "accepted" in verify["taskGate"]["outputTail"]
        assert verify["taskGate"]["source"] == "task"

    def test_the_task_gate_does_not_run_when_verify_failed(self, home: Path) -> None:
        marker = home.parent / "task-gate-ran"
        _fleet.meta_set("demo-implementer", "verifyCmd", "false")
        _implementer_only(home)
        task_id = _queue(pipeline="build", gate={"command": f"touch {marker}"})

        res = _sweep.dispatch_pod("demo", runner=FakeDriver())[0]

        assert res.status == "failed"
        assert not marker.exists()
        assert [
            e["payload"].get("source") for e in _task_events(task_id, "verification_failed")
        ] == [None]

    def test_the_gate_runs_after_the_last_implementer_step_only(self, home: Path) -> None:
        marker = home.parent / "gate-count"
        _fleet.meta_set("demo-implementer", "verifyCmd", "true")
        _pod_pipeline(
            "twice",
            "name: twice\nsteps:\n  - first: implementer\n  - second: implementer\n",
        )
        _queue(pipeline="twice", gate={"command": f"echo x >> {marker}"})

        res = _sweep.dispatch_pod("demo", runner=FakeDriver())[0]

        assert res.status == "done", res.reason
        assert marker.read_text().count("x") == 1
        assert "taskGate" in res.hops[1].verify
        assert "taskGate" not in res.hops[0].verify

    def test_a_task_gate_routes_through_the_steps_on_map(self, home: Path) -> None:
        _fleet.meta_set("demo-implementer", "verifyCmd", "true")
        _pod_pipeline(
            "routed",
            "name: routed\nsteps:\n  - build: implementer\n    on:\n      fail: stop\n",
        )
        _queue(pipeline="routed", gate={"command": "false"})

        res = _sweep.dispatch_pod("demo", runner=FakeDriver())[0]

        assert res.status == "done"
        assert res.hops[0].verify["label"] == "fail"
