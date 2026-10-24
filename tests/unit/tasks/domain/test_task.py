"""POST /tasks/<project> — enqueue a task over HTTP.

See specs/data/serve-read-api.spec.md ("POST /tasks/<project>") for the
endpoint contract this suite pins. Test classes: TestAuth (Bearer-gated
like ``/dispatch/`` and ``/runs``), TestBadRequests (malformed/invalid
bodies are 400 before ``enqueue_task_once`` runs), TestMissingPod (no pod is
404, not 500), TestPolicyGates (``pre_input`` gate behaves as the CLI
path does, since this route calls the same ``enqueue_task_once``),
TestSuccess (happy path), and TestExecuteUnitDirectly (``execute_unit``
and two extracted phases, called directly with a hand-built
``UnitContext``/``PlannedUnit``).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from tests.support.home import record_isolation_off
from tests.support.pods import build_pod

from docket.agent.ports import ChatResponse, TokenUsage, assistant
from docket.hops.application import driver as _drt
from docket.hops.application import sweep as _sweep
from docket.kernel.home import Home, current_home, use_home
from docket.observability import trace as _trace
from docket.pipeline.domain import plan as _orch
from docket.tasks.application import lifecycle as _lifecycle
from docket.tasks.application import queue as _queue
from docket.tasks.application import record as _record
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
        rec = _record.hop_record(hop)
        assert (rec["model"], rec["provider"]) == ("local/x", "local")
        back = _record.hop_from_record(rec)
        assert (back.model, back.provider) == ("local/x", "local")
        old = _record.hop_from_record({"role": "lead"})
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
            _lifecycle.finalize_task(
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
            _task.HopResult(
                role="reviewer",
                member_id="demo-reviewer",
                ok=False,
                error="budget",
                step_id="reviewer",
            ),
            _task.HopResult(
                role="tester", member_id="demo-tester", ok=True, output="PASS", step_id="tester"
            ),
        ]
        assert _record._group_complete(self._group(), prior) is False

    def test_every_child_succeeded_finishes_the_group(self) -> None:
        prior = [
            _task.HopResult(
                role="reviewer",
                member_id="demo-reviewer",
                ok=True,
                output="APPROVE",
                step_id="reviewer",
            ),
            _task.HopResult(
                role="tester", member_id="demo-tester", ok=True, output="PASS", step_id="tester"
            ),
        ]
        assert _record._group_complete(self._group(), prior) is True

    def test_a_child_that_failed_then_succeeded_counts_by_its_latest_hop(self) -> None:
        prior = [
            _task.HopResult(
                role="reviewer",
                member_id="demo-reviewer",
                ok=False,
                error="budget",
                step_id="reviewer",
            ),
            _task.HopResult(
                role="tester", member_id="demo-tester", ok=True, output="PASS", step_id="tester"
            ),
            _task.HopResult(
                role="reviewer",
                member_id="demo-reviewer",
                ok=True,
                output="APPROVE",
                step_id="reviewer",
            ),
        ]
        assert _record._group_complete(self._group(), prior) is True


class TestHopResultModel:
    def test_the_dump_is_the_persisted_hop(self) -> None:
        hop = _task.HopResult(
            role="reviewer", member_id="m", ok=True, output="APPROVE", cost_usd=0.12345678
        )
        dumped = hop.model_dump(by_alias=True, mode="json")
        assert dumped["member"] == "m"
        assert dumped["stepId"] == "reviewer"
        assert dumped["costUsd"] == 0.123457
        assert dumped["repoFiles"] is None
        assert dumped["nextStep"] is None
        assert dumped["artifact"]["summary"] == "APPROVE"
        assert "verification_skipped" not in dumped
        assert "verificationSkipped" not in dumped

    def test_a_step_id_that_differs_from_the_role_is_kept(self) -> None:
        hop = _task.HopResult(role="reviewer", member_id="m", ok=True, step_id="review-2")
        assert hop.model_dump(by_alias=True)["stepId"] == "review-2"

    def test_an_empty_artifact_is_rebuilt_from_the_output(self) -> None:
        hop = _task.HopResult(role="lead", member_id="m", ok=True, output="the plan")
        assert hop.artifact is not None
        assert hop.artifact.summary == "the plan"

    def test_a_hop_round_trips_through_its_dump(self) -> None:
        hop = _task.HopResult(
            role="implementer",
            member_id="m",
            ok=False,
            error="boom",
            attempts=2,
            next_step="fail",
            parked=True,
            verify={"cmd": "pytest", "exitCode": 1},
            evidence={"commit": "abc"},
            usage={"input": 3, "output": 4},
            trace={"project": "demo"},
            repo_files={"a.py": "sha"},
        )
        dumped = hop.model_dump(by_alias=True, mode="json")
        again = _task.HopResult.model_validate(dumped)
        assert again.model_dump(by_alias=True, mode="json") == dumped

    def test_an_invalid_artifact_is_rebuilt_from_the_output(self) -> None:
        hop = _task.HopResult.model_validate(
            {"role": "lead", "member": "m", "ok": True, "output": "plan", "artifact": "garbage"}
        )
        assert hop.artifact is not None
        assert hop.artifact.summary == "plan"

    @pytest.mark.parametrize(
        ("key", "attribute", "default"),
        [
            ("verify", "verify", None),
            ("evidence", "evidence", None),
            ("usage", "usage", None),
            ("trace", "trace", None),
            ("repoFiles", "repo_files", {}),
        ],
    )
    def test_each_invalid_value_degrades_alone(
        self, key: str, attribute: str, default: object
    ) -> None:
        raw = {"role": "lead", "output": "x", "verify": {"cmd": "c"}, "usage": {"input": 1}}
        hop = _task.HopResult.model_validate({**raw, key: "garbage"})
        assert getattr(hop, attribute) == default
        if key != "verify":
            assert hop.verify == {"cmd": "c"}
        if key != "usage":
            assert hop.usage == {"input": 1}

    def test_a_record_with_only_a_role_reads(self) -> None:
        hop = _task.HopResult.model_validate({"role": "lead"})
        assert (hop.member_id, hop.ok, hop.model, hop.provider) == ("", False, "", "")

    def test_the_in_memory_flag_is_never_written(self) -> None:
        hop = _task.HopResult(role="lead", member_id="m", ok=True, verification_skipped=True)
        assert hop.verification_skipped is True
        assert "verification_skipped" not in hop.model_dump(by_alias=True)

    def test_a_key_the_hop_does_not_have_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            _task.HopResult.model_validate({"role": "lead", "typo": 1})
