"""POST /tasks/<project> — enqueue a task over HTTP.

See specs/data/serve-read-api.spec.md ("POST /tasks/<project>") for the
endpoint contract this suite pins. Test classes: TestAuth (Bearer-gated
like ``/dispatch/`` and ``/runs``), TestBadRequests (malformed/invalid
bodies are 400 before ``enqueue_task_once`` runs), TestMissingPod (no pod is
404, not 500), TestPolicyGates (``pre_input`` gate behaves as the CLI
path does, since this route calls the same ``enqueue_task_once``),
TestSuccess (happy path), and TestExecuteUnitDirectly (``_execute_unit``
and two extracted phases, called directly with a hand-built
``_UnitContext``/``PlannedUnit``).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from tests.conftest import record_isolation_off
from tests.pods import build_pod

from docket.agent import driver as _drt
from docket.agent.llm import ChatResponse, TokenUsage, assistant
from docket.hops.application import record as _record
from docket.kernel.home import Home, current_home, use_home
from docket.observability import trace as _trace
from docket.pipeline.domain import plan as _orch
from docket.tasks.application import lifecycle as _lifecycle
from docket.tasks.application import queue as _queue
from docket.tasks.application import sweep as _sweep
from docket.tasks.domain import task as _task
from docket.teams import settings as _settings

SUBJECT = "docket.tasks.domain.task"


_HOP_STARTED_KEYS = {"task", "step", "role", "member", "model", "provider", "cycle", "attempt"}
_HOP_FINISHED_KEYS = _HOP_STARTED_KEYS | {"ok", "verdict", "gate", "usage", "durationMs", "error"}


class TestHopEvents:
    def test_hop_record_round_trips_model_and_provider(self) -> None:
        """A hop's model and provider survive the persisted record; an old record reads them empty."""
        hop = _task.HopResult(
            role="lead", member_id="m", ok=True, model="local/x", provider="local"
        )
        rec = _record._hop_record(hop)
        assert (rec["model"], rec["provider"]) == ("local/x", "local")
        back = _record._hop_from_record(rec)
        assert (back.model, back.provider) == ("local/x", "local")
        old = _record._hop_from_record({"role": "lead"})
        assert (old.model, old.provider) == ("", "")

    def test_a_two_hop_run_pairs_hop_events_and_sums_task_usage(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Each hop writes one hop_started and one hop_finished, and the task sums its usage."""
        home = tmp_path / ".docket"
        (home / "workspaces" / "projects").mkdir(parents=True)
        (home / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
        with use_home(Home(home)):
            record_isolation_off(home)
            build_pod("demo", ("lead", "implementer"), codebase="/src/demo")
            monkeypatch.setenv("DOCKET_NO_TRACE", "0")
            backend = _ScriptedBackend(["lead plan", "implementer done"])
            driver = _drt.DocketDriver(backend_factory=lambda model: backend)
            monkeypatch.setattr(_drt, "default_driver", lambda: driver)
            task = _queue.enqueue_task_once("demo", "two hops", channel="cli")[0]
            assert _sweep.dispatch_pod("demo")[0].status == "done"

            events = [e for e in _trace_events("demo") if e["event_type"].startswith("hop_")]
            assert [e["event_type"] for e in events] == [
                "hop_started",
                "hop_finished",
                "hop_started",
                "hop_finished",
            ]
            for event in events:
                keys = (
                    _HOP_STARTED_KEYS
                    if event["event_type"] == "hop_started"
                    else _HOP_FINISHED_KEYS
                )
                assert set(event["payload"]) == keys
            started = [e["payload"] for e in events if e["event_type"] == "hop_started"]
            assert [p["model"] for p in started] == [
                "anthropic/claude-haiku-4-5",
                "anthropic/claude-sonnet-4-6",
            ]
            assert [p["provider"] for p in started] == ["anthropic", "anthropic"]
            finished = [e["payload"] for e in events if e["event_type"] == "hop_finished"]
            assert {(p["model"], p["provider"]) for p in finished} == {
                ("local/served-model", "local")
            }
            raw = json.loads(_settings.pod_task_list_path("demo").read_text())
            (stored,) = [t for t in raw["tasks"] if t["id"] == str(task["id"])]
            assert [(h["model"], h["provider"]) for h in stored["hops"]] == [
                ("local/served-model", "local"),
                ("local/served-model", "local"),
            ]
            assert stored["usage"] == {
                "input": 14,
                "cached": 0,
                "cacheWrite": 0,
                "output": 6,
                "byModel": {
                    "local/served-model": {"input": 14, "cached": 0, "cacheWrite": 0, "output": 6}
                },
            }

    def test_by_model_sums_cache_reads_and_writes_per_model(self, tmp_path: Path) -> None:
        """The task's usage and each byModel entry sum input, cached, cacheWrite and output."""
        home = tmp_path / ".docket"
        (home / "workspaces" / "projects").mkdir(parents=True)
        (home / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
        with use_home(Home(home)):
            record_isolation_off(home)
            build_pod("demo", ("lead", "implementer"), codebase="/src/demo")
            task = _queue.enqueue_task_once("demo", "usage", channel="cli")[0]
            task_id = str(task["id"])
            hops = [
                _task.HopResult(
                    role="lead",
                    member_id="m",
                    ok=True,
                    model="local/x",
                    provider="local",
                    usage={"input": 100, "cached": 60, "cacheWrite": 5, "output": 7},
                ),
                _task.HopResult(
                    role="implementer",
                    member_id="m",
                    ok=True,
                    model="local/x",
                    provider="local",
                    usage={"input": 50, "cached": 10, "cacheWrite": 0, "output": 3},
                ),
            ]
            _lifecycle._finalize_task(
                "demo", task_id, _task.TaskResult(task_id=task_id, status="done", hops=hops)
            )
            raw = json.loads(_settings.pod_task_list_path("demo").read_text())
            (stored,) = [t for t in raw["tasks"] if t["id"] == task_id]
            assert stored["usage"] == {
                "input": 150,
                "cached": 70,
                "cacheWrite": 5,
                "output": 10,
                "byModel": {"local/x": {"input": 150, "cached": 70, "cacheWrite": 5, "output": 10}},
            }


class _ScriptedBackend:
    def __init__(self, texts: list[str]) -> None:
        self._texts = list(texts)

    def complete(self, messages: Any, **_: Any) -> ChatResponse:
        return ChatResponse(
            ok=True,
            message=assistant(self._texts.pop(0)),
            finish_reason="stop",
            usage=TokenUsage(7, 3),
            model="served-model",
            provider="local",
        )


def _trace_events(project: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    traces_dir = current_home().traces_dir / project
    if traces_dir.is_dir():
        for f in traces_dir.glob("*.jsonl"):
            events.extend(_trace.read_trace(f))
    return events


class TestGroupResume:
    """A parallel group is finished only when every child's latest hop succeeded."""

    @staticmethod
    def _unit(step_id: str) -> _orch.PlannedUnit:
        return _orch.PlannedUnit(
            step_id=step_id,
            role=step_id,
            agent=None,
            archetype=None,
            member_id=f"demo-{step_id}",
            gate=None,
            retries=None,
            timeout=None,
        )

    def _group(self) -> _orch.PlannedGroup:
        return _orch.PlannedGroup(
            step_id="reviews", children=(self._unit("reviewer"), self._unit("tester"))
        )

    def test_a_failed_child_leaves_the_group_unfinished(self) -> None:
        prior = [
            _task.HopResult("reviewer", "demo-reviewer", False, error="budget", step_id="reviewer"),
            _task.HopResult("tester", "demo-tester", True, output="PASS", step_id="tester"),
        ]
        assert _record._group_complete(self._group(), prior) is False

    def test_every_child_succeeded_finishes_the_group(self) -> None:
        prior = [
            _task.HopResult(
                "reviewer", "demo-reviewer", True, output="APPROVE", step_id="reviewer"
            ),
            _task.HopResult("tester", "demo-tester", True, output="PASS", step_id="tester"),
        ]
        assert _record._group_complete(self._group(), prior) is True

    def test_a_child_that_failed_then_succeeded_counts_by_its_latest_hop(self) -> None:
        prior = [
            _task.HopResult("reviewer", "demo-reviewer", False, error="budget", step_id="reviewer"),
            _task.HopResult("tester", "demo-tester", True, output="PASS", step_id="tester"),
            _task.HopResult(
                "reviewer", "demo-reviewer", True, output="APPROVE", step_id="reviewer"
            ),
        ]
        assert _record._group_complete(self._group(), prior) is True
