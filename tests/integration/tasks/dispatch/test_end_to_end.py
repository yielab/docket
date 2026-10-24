"""Pod dispatch end to end with a scripted model, and concurrent dispatch."""

from __future__ import annotations

import dataclasses
import json
import threading
import time
from collections import Counter
from pathlib import Path

import pytest
from tests.support.dispatch_harness import (
    _ScriptedBackend,
)
from tests.support.fakes import FakeDriver
from tests.support.llm import final_response as _final_response
from tests.support.pods import seed_pod_2 as _seed_pod

from docket.agent import ports as _rd
from docket.agent import session as _session
from docket.agent.ports import ChatResponse, TokenUsage, ToolCall, assistant
from docket.hops.application import driver as _dr
from docket.hops.application import runner as _runner
from docket.hops.application.driver import DocketDriver
from docket.kernel.home import current_home, use_home
from docket.kernel.threads import new_thread
from docket.pipeline.application import executor as _executor
from docket.pipeline.domain import spec as _pipeline
from docket.pipeline.domain import step as _step
from docket.tasks.application import actions as _actions
from docket.tasks.application import queue as _queue
from docket.tasks.application import sweep as _sweep
from docket.teams import fleet as _fleet

SUBJECT = "docket.tasks.application.queue"


class TestEndToEnd:
    def test_full_stack_through_docket_driver(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No injected runner -> a real pod-dispatch hop executes through `DocketDriver`."""
        with _seed_pod(tmp_path) as oc_dir:
            backend = _ScriptedBackend(
                [_final_response("lead plan"), _final_response("implementer done")]
            )
            driver = DocketDriver(backend_factory=lambda model: backend)
            monkeypatch.setattr(_dr, "default_driver", lambda: driver)

            _queue.enqueue_task_once("demo", "End to end", channel="cli")
            results = _sweep.dispatch_pod("demo")
            assert results[0].status == "done"
            # cost_usd stays 0.0 through DocketDriver — CLAUDE.md's standing rule
            # against turning a measured-token estimate into a billing claim.
            assert results[0].cost_usd == 0.0
            assert len(backend.calls) == 2  # one turn per pod hop (lead, implementer)
            tasks = _queue.read_tasks("demo")
            assert tasks[0]["status"] == "done"
            assert (oc_dir / "traces" / "demo").is_dir()

    def test_agent_loop_trace_records_carry_the_claimed_tasks_id(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Every record the real agent loop writes for a hop is filed under the claimed
        task's id; dispatch's own task-level session_start/session_end bookkeeping records
        (written directly by core/dispatch.py, untouched by this card) carry no task_id."""
        with _seed_pod(tmp_path) as oc_dir:
            backend = _ScriptedBackend(
                [_final_response("lead plan"), _final_response("implementer done")]
            )
            driver = DocketDriver(backend_factory=lambda model: backend)
            monkeypatch.setattr(_dr, "default_driver", lambda: driver)

            task = _queue.enqueue_task_once("demo", "Trace task id", channel="cli")[0]
            results = _sweep.dispatch_pod("demo")
            assert results[0].status == "done"

            trace_files = list((oc_dir / "traces" / "demo").glob("*.jsonl"))
            assert len(trace_files) == 1
            events = [json.loads(line) for line in trace_files[0].read_text().splitlines()]
            llm_events = [e for e in events if e["event_type"] == "llm_call"]
            assert len(llm_events) == 2  # one per hop (lead, implementer)
            assert all(e.get("task_id") == task["id"] for e in llm_events)
            session_events = [
                e for e in events if e["event_type"] in ("session_start", "session_end")
            ]
            assert session_events
            assert all("task_id" not in e for e in session_events)

    def test_refuse_approval_mode_fails_a_gated_hop_immediately_instead_of_waiting(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The measured trigger this card closes: a real policy-gated `bash` call, through the
        real `DocketDriver`, ends the hop well under `TOOL_APPROVAL_TIMEOUT` and fails the task
        with the `approval_unavailable` reason recorded, instead of blocking on nobody."""
        from docket.governance.policy import install_policies

        with (
            _seed_pod(tmp_path) as oc_dir,
            use_home(dataclasses.replace(current_home(), tool_approval_timeout=2)),
        ):
            install_policies()
            _fleet.meta_set("demo-lead", "approvalMode", "refuse")

            # "lead" denies the `bash` tool outright (teams/roles.py); the gated call has
            # to be the Implementer's, so the Lead's turn gets an ordinary final response first.
            call = ToolCall(id="c1", name="bash", arguments=json.dumps({"command": "rm -rf build"}))
            backend = _ScriptedBackend(
                [
                    _final_response("lead plan"),
                    ChatResponse(
                        ok=True,
                        message=assistant("", tool_calls=[call]),
                        finish_reason="tool_calls",
                        usage=TokenUsage(10, 5),
                    ),
                ]
            )
            driver = DocketDriver(backend_factory=lambda model: backend)
            monkeypatch.setattr(_dr, "default_driver", lambda: driver)

            _queue.enqueue_task_once("demo", "clean the build dir", channel="cli")
            started = time.monotonic()
            results = _sweep.dispatch_pod("demo")
            elapsed = time.monotonic() - started

            assert elapsed < 1.0, f"took {elapsed:.2f}s -- refuse mode should not wait"
            assert results[0].status == "failed"
            assert "approval_unavailable" in results[0].reason
            tasks = _queue.read_tasks("demo")
            assert tasks[0]["status"] == "failed"
            assert "approval_unavailable" in tasks[0]["reason"]
            trace_files = list((oc_dir / "traces" / "demo").glob("*.jsonl"))
            assert trace_files
            trace_events = [json.loads(line) for line in trace_files[0].read_text().splitlines()]
            assert any(
                ev["event_type"] == "error"
                and "approval_unavailable" in ev["payload"].get("text", "")
                for ev in trace_events
            )

    def test_park_approval_mode_parks_a_gated_hop_immediately_instead_of_waiting(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A real policy-gated `bash` call, through the real `DocketDriver`, ends the hop
        well under `TOOL_APPROVAL_TIMEOUT` and parks the task, token recorded."""
        from docket.governance.policy import install_policies

        with (
            _seed_pod(tmp_path) as oc_dir,
            use_home(dataclasses.replace(current_home(), tool_approval_timeout=2)),
        ):
            install_policies()
            _fleet.meta_set("demo-lead", "approvalMode", "park")

            call = ToolCall(id="c1", name="bash", arguments=json.dumps({"command": "rm -rf build"}))
            backend = _ScriptedBackend(
                [
                    _final_response("lead plan"),
                    ChatResponse(
                        ok=True,
                        message=assistant("", tool_calls=[call]),
                        finish_reason="tool_calls",
                        usage=TokenUsage(10, 5),
                    ),
                ]
            )
            driver = DocketDriver(backend_factory=lambda model: backend)
            monkeypatch.setattr(_dr, "default_driver", lambda: driver)

            _queue.enqueue_task_once("demo", "clean the build dir", channel="cli")
            started = time.monotonic()
            results = _sweep.dispatch_pod("demo")
            elapsed = time.monotonic() - started

            assert elapsed < 1.0, f"took {elapsed:.2f}s -- park mode should not wait"
            assert results[0].status == "waiting_approval", results[0].reason
            assert results[0].approval_token
            tasks = _queue.read_tasks("demo")
            assert tasks[0]["status"] == "waiting_approval"
            assert tasks[0]["approvalToken"] == results[0].approval_token
            # The parked hop is persisted (audit/trace history stays true) --
            # `parked: true`, not silently dropped.
            assert tasks[0]["hops"][-1]["role"] == "implementer"
            assert tasks[0]["hops"][-1]["parked"] is True
            trace_files = list((oc_dir / "traces" / "demo").glob("*.jsonl"))
            assert trace_files
            trace_events = [
                json.loads(line) for tf in trace_files for line in tf.read_text().splitlines()
            ]
            assert any(
                ev["event_type"] == "approval_required"
                and ev["payload"].get("token") == results[0].approval_token
                for ev in trace_events
            )

    def test_park_grant_resumes_the_parked_hop_with_a_single_use_pregrant(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The resume path: `docket task approve <t>` then `docket run` re-runs the
        implementer hop (not the lead's already-persisted one) at its own index, and the exact
        same tool call the human approved passes once via a single-use pre-grant."""
        from docket.governance import approval as _approval_mod
        from docket.governance.policy import install_policies

        with (
            _seed_pod(tmp_path),
            use_home(dataclasses.replace(current_home(), tool_approval_timeout=2)),
        ):
            install_policies()
            _fleet.meta_set("demo-lead", "approvalMode", "park")

            call = ToolCall(id="c1", name="bash", arguments=json.dumps({"command": "rm -rf build"}))
            park_backend = _ScriptedBackend(
                [
                    _final_response("lead plan"),
                    ChatResponse(
                        ok=True,
                        message=assistant("", tool_calls=[call]),
                        finish_reason="tool_calls",
                        usage=TokenUsage(10, 5),
                    ),
                ]
            )
            driver = DocketDriver(backend_factory=lambda model: park_backend)
            monkeypatch.setattr(_dr, "default_driver", lambda: driver)

            _queue.enqueue_task_once("demo", "clean the build dir", channel="cli")
            parked = _sweep.dispatch_pod("demo")
            token = parked[0].approval_token
            assert token

            # docket task approve <token>
            _approval_mod.approval_grant(token, channel="cli")
            assert _actions.resolve_waiting_approval(token, "granted") is True
            task = _queue.read_tasks("demo")[0]
            assert task["status"] == "pending"
            assert len(task["pregrants"]) == 1
            assert task["pregrants"][0]["token"] == token
            assert task["pregrants"][0]["tool"] == "bash"
            assert task["pregrants"][0]["argsDigest"]
            # The override-index field is for skipping a pre-hop approval *gate*,
            # never reused to re-run an already-attempted hop.
            assert task.get("gateOverridePipelineIndex") is None

            # docket run -- the implementer's identical call is
            # re-issued by the model and this time passes via the pre-grant, then
            # the hop finishes normally.
            resume_backend = _ScriptedBackend(
                [
                    ChatResponse(
                        ok=True,
                        message=assistant("", tool_calls=[call]),
                        finish_reason="tool_calls",
                        usage=TokenUsage(10, 5),
                    ),
                    _final_response("implementer done"),
                ]
            )
            driver2 = DocketDriver(backend_factory=lambda model: resume_backend)
            monkeypatch.setattr(_dr, "default_driver", lambda: driver2)

            second = _sweep.dispatch_pod("demo")

            assert second[0].status == "done", second[0].reason
            final = _queue.read_tasks("demo")[0]
            # Lead's already-persisted hop was not re-run; the implementer step
            # appears twice -- the parked attempt and the real one -- exactly the
            # same "each attempt is its own audit record" shape a rework cycle's
            # repeated reviewer hop already has, never overwritten in place.
            assert [h["role"] for h in final["hops"]] == ["lead", "implementer", "implementer"]
            assert final["hops"][1]["parked"] is True
            assert final["hops"][1]["ok"] is False
            assert final["hops"][-1]["parked"] is False
            assert final["hops"][-1]["ok"] is True

    def test_park_deny_fails_the_task_approval_denied(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from docket.governance import approval as _approval_mod
        from docket.governance.policy import install_policies

        with (
            _seed_pod(tmp_path),
            use_home(dataclasses.replace(current_home(), tool_approval_timeout=2)),
        ):
            install_policies()
            _fleet.meta_set("demo-lead", "approvalMode", "park")

            call = ToolCall(id="c1", name="bash", arguments=json.dumps({"command": "rm -rf build"}))
            backend = _ScriptedBackend(
                [
                    _final_response("lead plan"),
                    ChatResponse(
                        ok=True,
                        message=assistant("", tool_calls=[call]),
                        finish_reason="tool_calls",
                        usage=TokenUsage(10, 5),
                    ),
                ]
            )
            driver = DocketDriver(backend_factory=lambda model: backend)
            monkeypatch.setattr(_dr, "default_driver", lambda: driver)

            _queue.enqueue_task_once("demo", "clean the build dir", channel="cli")
            parked = _sweep.dispatch_pod("demo")
            token = parked[0].approval_token

            _approval_mod.approval_deny(token, channel="cli")
            assert _actions.resolve_waiting_approval(token, "denied") is True

            task = _queue.read_tasks("demo")[0]
            assert task["status"] == "failed"
            assert task["failureKind"] == "approval_denied"

    def test_park_expiry_past_deadline_denies_via_sweep(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A parked approval's own `expiresAt` (not the default APPROVAL_TIMEOUT) governs it,
        and the fail-closed sweep denies it once past that deadline -- same resolution path as
        an explicit human deny."""
        from docket.governance import approval as _approval_mod
        from docket.governance.policy import install_policies

        with (
            _seed_pod(tmp_path),
            use_home(dataclasses.replace(current_home(), tool_approval_timeout=2)),
        ):
            install_policies()
            _fleet.meta_set("demo-lead", "approvalMode", "park")

            call = ToolCall(id="c1", name="bash", arguments=json.dumps({"command": "rm -rf build"}))
            backend = _ScriptedBackend(
                [
                    _final_response("lead plan"),
                    ChatResponse(
                        ok=True,
                        message=assistant("", tool_calls=[call]),
                        finish_reason="tool_calls",
                        usage=TokenUsage(10, 5),
                    ),
                ]
            )
            driver = DocketDriver(backend_factory=lambda model: backend)
            monkeypatch.setattr(_dr, "default_driver", lambda: driver)

            _queue.enqueue_task_once("demo", "clean the build dir", channel="cli")
            parked = _sweep.dispatch_pod("demo")
            token = parked[0].approval_token
            assert token

            # Force this record's own expiresAt into the past -- the parked
            # record carries its own deadline (governance/gate.py's `_park`),
            # never the generic APPROVAL_TIMEOUT.
            rec_path = current_home().approvals_dir / f"{token}.json"
            rec = json.loads(rec_path.read_text(encoding="utf-8"))
            assert rec["expiresAt"]
            rec["expiresAt"] = "2000-01-01T00:00:00Z"
            rec_path.write_text(json.dumps(rec), encoding="utf-8")

            swept = _approval_mod.approval_sweep_expired()
            assert swept == 1

            task = _queue.read_tasks("demo")[0]
            assert task["status"] == "failed"
            assert task["failureKind"] == "approval_denied"

    def test_each_step_replays_only_its_history_and_receives_typed_handoff_once(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The production dispatch -> driver -> loop path must not give the
        Implementer both Lead's raw assistant turn and the handoff that already
        carries it."""
        with (
            _seed_pod(tmp_path) as home,
            use_home(dataclasses.replace(current_home(), sessions_dir_override=home / "sessions")),
        ):
            backend = _ScriptedBackend(
                [
                    _final_response("LEAD_RAW_PLAN_SENTINEL"),
                    _final_response("implementation done"),
                ]
            )
            driver = DocketDriver(backend_factory=lambda model: backend)
            monkeypatch.setattr(_dr, "default_driver", lambda: driver)

            task = _queue.enqueue_task_once("demo", "Keep context bounded", channel="cli")[0]
            legacy_task_key = f"agent:demo:{task['id']}"
            legacy_message = assistant("LEGACY_TASK_WIDE_HISTORY")
            _session.append_messages(legacy_task_key, [legacy_message])
            result = _sweep.dispatch_pod("demo")[0]
            assert result.status == "done"

            lead_key = _runner.step_session_key("demo-lead", "demo", task["id"], "lead")
            implementer_key = _runner.step_session_key(
                "demo-implementer", "demo", task["id"], "implementer"
            )
            assert lead_key != implementer_key

            lead_history = _session.load_messages(lead_key)
            implementer_history = _session.load_messages(implementer_key)
            assert any(
                m.role == "assistant" and m.content == "LEAD_RAW_PLAN_SENTINEL"
                for m in lead_history
            )
            assert not any(
                m.role == "assistant" and m.content == "LEAD_RAW_PLAN_SENTINEL"
                for m in implementer_history
            )

            implementer_backend_messages = backend.calls[1]
            assert (
                sum("LEAD_RAW_PLAN_SENTINEL" in m.content for m in implementer_backend_messages)
                == 1
            )
            assert all("LEGACY_TASK_WIDE_HISTORY" not in m.content for m in backend.calls[0])
            assert all(
                "LEGACY_TASK_WIDE_HISTORY" not in m.content for m in implementer_backend_messages
            )
            assert any(
                m.role == "user" and "LEAD_RAW_PLAN_SENTINEL" in m.content
                for m in implementer_backend_messages
            )

            assert [s.session_id for s in driver.list_sessions("demo-lead")] == [lead_key]
            assert [s.session_id for s in driver.list_sessions("demo-implementer")] == [
                implementer_key
            ]
            assert _session.load_messages(legacy_task_key) == [legacy_message]
            assert [s.session_id for s in driver.list_sessions("demo")] == [legacy_task_key]

            trace_files = list((home / "traces" / "demo").glob("*.jsonl"))
            assert len(trace_files) == 1
            trace_events = [json.loads(line) for line in trace_files[0].read_text().splitlines()]
            assert trace_events[0]["session_id"] == f"agent:demo:{task['id']}"
            assert all(e["session_id"] == f"agent:demo:{task['id']}" for e in trace_events)
            assert sum(e["event_type"] == "session_compaction" for e in trace_events) == 2
            assert {path.name for path in (home / "traces").iterdir()} == {"demo"}

    def test_step_history_key_encodes_custom_step_ids_without_collisions(self) -> None:
        colon = _runner.step_session_key("member", "demo", "task-1", "review:security")
        slash = _runner.step_session_key("member", "demo", "task-1", "review/security")

        assert colon.endswith(":step:review%3Asecurity")
        assert slash.endswith(":step:review%2Fsecurity")
        assert colon != slash

    def test_parallel_children_with_one_role_receive_distinct_step_histories(
        self, tmp_path: Path
    ) -> None:
        with _seed_pod(tmp_path):
            spec = _pipeline.PipelineSpec(
                name="parallel-repeat",
                steps=[
                    _step.Step(
                        id="fanout",
                        parallel=[
                            _step.Step(id="implement-a", role="implementer"),
                            _step.Step(id="implement-b", role="implementer"),
                        ],
                    )
                ],
            )
            runner = FakeDriver()
            task = {"id": "task-parallel", "description": "compare", "status": "pending"}

            result = _executor.dispatch_task("demo", task, runner=runner, spec=spec)

            assert result.status == "done"
            assert {call[1] for call in runner.calls} == {
                _runner.step_session_key(
                    "demo-implementer", "demo", "task-parallel", "implement-a"
                ),
                _runner.step_session_key(
                    "demo-implementer", "demo", "task-parallel", "implement-b"
                ),
            }


class TestConcurrentDispatch:
    """The double-run regression this exists to close: an unlocked ``dispatch_pod`` could let
    two concurrent callers both run the same ``pending`` task from a stale queue snapshot.
    ``_claim_next_task``'s locked read-modify-write prevents this: never the same task twice."""

    def test_two_concurrent_dispatch_pod_calls_never_double_run_a_task(
        self, tmp_path: Path
    ) -> None:
        with _seed_pod(tmp_path):
            n_tasks = 8
            for i in range(n_tasks):
                _queue.enqueue_task_once("demo", f"task {i}", channel="cli")

            calls: list[str] = []
            calls_lock = threading.Lock()

            class _SlowRunner:
                """Sleeps on every hop so concurrent claim attempts actually overlap."""

                def __call__(
                    self,
                    agent_id: str,
                    session_key: str,
                    message: str,
                    timeout: int,
                    env: dict[str, str] | None = None,
                ) -> _rd.TurnResult:
                    time.sleep(0.02)
                    with calls_lock:
                        calls.append(session_key)
                    return _rd.TurnResult(True, f"done by {agent_id}", 0.0, {"output": "x"})

            runner = _SlowRunner()
            errors: list[BaseException] = []

            def _run() -> None:
                try:
                    _sweep.dispatch_pod("demo", runner=runner)
                except BaseException as exc:  # surfaced via `errors`, not swallowed
                    errors.append(exc)

            threads = [new_thread(target=_run) for _ in range(4)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=15)

            assert not errors, f"dispatch_pod raised in a worker thread: {errors}"
            # Each task is a 2-hop pipeline (lead, implementer) with two distinct
            # step-history keys. Group by the embedded task component: exactly two
            # calls per task means no claim ran twice and no task was skipped.
            task_ids = [key.split(":task:", 1)[1].split(":step:", 1)[0] for key in calls]
            counts = Counter(task_ids)
            assert len(counts) == n_tasks, f"expected {n_tasks} distinct tasks, got {counts}"
            assert all(c == 2 for c in counts.values()), counts
            assert len(set(calls)) == n_tasks * 2
            tasks = _queue.read_tasks("demo")
            assert len(tasks) == n_tasks
            assert all(t["status"] == "done" for t in tasks)
            assert len({t["id"] for t in tasks}) == n_tasks  # uuid4 ids never collide
