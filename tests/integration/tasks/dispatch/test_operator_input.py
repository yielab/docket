"""Pod dispatch with operator input: asking steps, answers and the intake recipe."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from tests.support.dispatch_harness import (
    _ScriptedBackend,
)
from tests.support.fakes import FakeDriver
from tests.support.llm import final_response as _final_response
from tests.support.pods import bind_intake_pipeline as _bind_intake_pipeline
from tests.support.pods import bind_pipeline as _bind_pipeline
from tests.support.pods import seed_pod_isolation_off as _seed_pod

from docket.agent import ports as _rd
from docket.governance import secrets as _secrets
from docket.hops.application import answers as _answers
from docket.hops.application import driver as _dr
from docket.hops.application import sweep as _sweep
from docket.hops.application.driver import DocketDriver
from docket.hops.gates import pre_hop as _pre_hop
from docket.interfaces.cli.commands import pod as _pod
from docket.kernel import brief as _brief
from docket.kernel import operator_contract as _oc
from docket.pipeline.domain import spec as _pipeline
from docket.pipeline.domain import step as _step
from docket.tasks.application import queue as _queue
from docket.teams import fleet as _fleet

SUBJECT = "docket.tasks.application.queue"


_ASK_PIPELINE_YAML = """\
name: ask
steps:
  - lead: lead
  - ask:
      input:
        from: lead
  - implementer: implementer
"""


_ASK_DECLINE_CAP_PIPELINE_YAML = """\
name: ask-decline-cap
steps:
  - lead: lead
  - ask:
      input:
        from: lead
      on:
        declined:
          goto: lead
          max: 1
  - implementer: implementer
"""


def _ask_spec(on: dict[str, Any] | None = None) -> _pipeline.PipelineSpec:
    """Lead, then an `input` step asking about the Lead's own output, then Implementer."""
    return _pipeline.PipelineSpec(
        name="ask",
        steps=[
            _step.Step(id="lead", role="lead"),
            _step.Step(id="ask", input=_step.InputSpec(from_="lead"), on=on),
            _step.Step(id="implementer", role="implementer"),
        ],
    )


_LEAD_NEEDS_INPUT_SENTINEL = "SENTINEL_FIRST_LEAD_HOP"


_LEAD_READY_SENTINEL = "SENTINEL_SECOND_LEAD_HOP"


_LEAD_NEEDS_INPUT_REPLY = f"""{_LEAD_NEEDS_INPUT_SENTINEL}: I need two decisions before I can start.

```json
{{"objective": "add a widget", "acceptance": ["widget renders"], "questions": ["Which color?", "Which size?"]}}
```
NEEDS-INPUT"""


_LEAD_READY_REPLY = f"""{_LEAD_READY_SENTINEL}: thanks, now I have everything I need.

```json
{{"objective": "add a widget", "acceptance": ["widget renders", "matches spec"]}}
```
READY"""


_LEAD_READY_MISSING_SECRET_REPLY = """Needs one credential.

```json
{"objective": "call the API", "acceptance": ["call succeeds"], "resources": ["secret:MISSING_KEY"]}
```
READY"""


_LEAD_READY_NO_BRIEF_REPLY = "Nothing fancy, just doing it.\nREADY"


_LEAD_REJECT_REPLY = """This should not be attempted.

```json
{"objective": "delete production", "acceptance": []}
```
REJECT"""


class _IntakeRunner:
    """A scripted runner keyed by role, not call order -- the Lead may run more than once
    (NEEDS-INPUT -> answered -> re-run), so its replies are consumed in order, one per call,
    while every other role answers the same way every time."""

    def __init__(self, lead_replies: list[str], reviewer_reply: str = "APPROVE") -> None:
        self._lead_replies = list(lead_replies)
        self._reviewer_reply = reviewer_reply
        self.calls: list[tuple[str, str]] = []

    def __call__(
        self,
        agent_id: str,
        session_key: str,
        message: str,
        timeout: int,
        env: dict[str, str] | None = None,
    ) -> _rd.TurnResult:
        role = agent_id.rsplit("-", 1)[-1]
        self.calls.append((role, message))
        if role == "lead":
            reply = self._lead_replies.pop(0) if self._lead_replies else "READY"
            return _rd.TurnResult(True, reply, 0.0, {})
        if role == "reviewer":
            return _rd.TurnResult(True, self._reviewer_reply, 0.0, {})
        return _rd.TurnResult(True, "done", 0.0, {})


class TestOperatorInputStepsPark:
    def test_reaching_an_input_step_parks_with_no_hop_and_a_default_schema(
        self, tmp_path: Path
    ) -> None:
        with _seed_pod(tmp_path) as oc_dir:
            _queue.enqueue_task_once("demo", "needs a decision", channel="cli")

            results = _sweep.dispatch_pod("demo", runner=FakeDriver(), spec=_ask_spec())

            assert len(results) == 1
            assert results[0].status == "waiting_input"
            task = _queue.read_tasks("demo")[0]
            assert task["status"] == "waiting_input"
            # Only the Lead's real hop is persisted -- the park itself leaves no hop, the same
            # posture as the pre-hop require_approval gate's `waiting_approval`.
            assert [h["role"] for h in task["hops"]] == ["lead"]
            question = task["question"]
            assert question["step"] == "ask"
            assert question["requestedSchema"]["properties"] == {"answer": {"type": "string"}}
            assert question["requestedSchema"]["required"] == ["answer"]

            trace_files = list((oc_dir / "traces" / "demo").glob("*.jsonl"))
            events = [
                json.loads(line) for tf in trace_files for line in tf.read_text().splitlines()
            ]
            requested = [e for e in events if e["event_type"] == "input_requested"]
            assert len(requested) == 1
            assert requested[0]["payload"]["step"] == "ask"
            assert requested[0]["payload"]["questionId"] == question["id"]

    def test_a_waiting_input_task_is_never_reclaimed_by_a_plain_dispatch(
        self, tmp_path: Path
    ) -> None:
        with _seed_pod(tmp_path):
            _queue.enqueue_task_once("demo", "needs a decision", channel="cli")
            _sweep.dispatch_pod("demo", runner=FakeDriver(), spec=_ask_spec())
            assert _queue.read_tasks("demo")[0]["status"] == "waiting_input"

            for _ in range(3):
                assert _sweep.dispatch_pod("demo", runner=FakeDriver(), spec=_ask_spec()) == []
            assert _queue.read_tasks("demo")[0]["status"] == "waiting_input"


class TestAnswerTaskResumesDispatch:
    """An answered `input` step's synthetic hop carries its own `nextStep`, so the resume
    builder (and its `route_counts` rebuild) continues correctly across a resume boundary."""

    def test_an_accepted_answer_resumes_straight_through_to_done(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            _bind_pipeline("demo", _ASK_PIPELINE_YAML)
            task = _queue.enqueue_task_once("demo", "needs a decision", channel="cli")[0]
            _sweep.dispatch_pod("demo", runner=FakeDriver())
            assert _queue.read_tasks("demo")[0]["status"] == "waiting_input"

            result = _answers.answer_task(
                "demo", task["id"], "accept", {"answer": "go ahead"}, channel="cli", actor="op"
            )
            assert result.action == "accept"

            parked = _queue.read_tasks("demo")[0]
            assert parked["status"] == "pending"
            assert parked["answers"][0]["content"] == {"answer": "go ahead"}
            assert [h["role"] for h in parked["hops"]] == ["lead", "operator"]
            assert parked["hops"][-1]["nextStep"] is None  # no `on:` route -- ordinary advance

            # The crash/resume boundary: a fresh `dispatch_pod` call (as `serve --dispatch`'s
            # next sweep would make) claims the re-opened task and must continue past `ask`
            # straight to `implementer`, never re-asking.
            final_results = _sweep.dispatch_pod("demo", runner=FakeDriver())
            assert final_results[0].status == "done"
            final = _queue.read_tasks("demo")[0]
            assert [h["role"] for h in final["hops"]] == ["lead", "operator", "implementer"]

    def test_a_declined_answer_routes_backward_and_a_second_decline_exhausts_its_cap(
        self, tmp_path: Path
    ) -> None:
        """`max: 1` -- proves `route_counts` is rebuilt from the persisted hop's `nextStep`
        on resume: the second decline, a brand new `answer_task` call, must still see it."""
        with _seed_pod(tmp_path):
            _bind_pipeline("demo", _ASK_DECLINE_CAP_PIPELINE_YAML)
            task = _queue.enqueue_task_once("demo", "needs a decision", channel="cli")[0]
            _sweep.dispatch_pod("demo", runner=FakeDriver())
            assert _queue.read_tasks("demo")[0]["status"] == "waiting_input"

            _answers.answer_task("demo", task["id"], "decline", None, channel="cli", actor="op")
            after_first = _queue.read_tasks("demo")[0]
            assert after_first["status"] == "pending"
            assert after_first["hops"][-1]["nextStep"] == "lead"

            # Resume: replays back to `lead`, re-runs it (a fresh hop), reaches `ask` again and
            # parks with a brand new question -- `route_counts` for ("ask", "declined") is now 1,
            # rebuilt purely from the first operator hop's own persisted `nextStep`.
            _sweep.dispatch_pod("demo", runner=FakeDriver())
            reparked = _queue.read_tasks("demo")[0]
            assert reparked["status"] == "waiting_input"
            assert [h["role"] for h in reparked["hops"]] == ["lead", "operator", "lead"]

            # A second decline exhausts the `max: 1` budget -- `answer_task` settles the task
            # `failed` right here (no live dispatch context exists to do it for it).
            _answers.answer_task("demo", task["id"], "decline", None, channel="cli", actor="op")
            final = _queue.read_tasks("demo")[0]
            assert final["status"] == "failed"
            assert final["hops"][-1]["nextStep"] is None
            assert final["hops"][-1]["role"] == "operator"


class TestCheckBriefResources:
    """Direct, dispatch-free coverage of `_check_brief_resources`'s three resource kinds --
    the intake-recipe integration tests above exercise `secret:` end to end through a real
    pipeline; these isolate `path:` and `verify` (and `secret:` again, for symmetry)."""

    def test_an_unconfigured_secret_is_missing(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            brief = _brief.TaskBrief(objective="x", resources=["secret:NOPE"])
            assert _pre_hop._check_brief_resources("demo", brief) == ["secret:NOPE"]

    def test_a_configured_secret_is_not_missing(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            _secrets.save_secrets({"YES": "shh"})
            brief = _brief.TaskBrief(objective="x", resources=["secret:YES"])
            assert _pre_hop._check_brief_resources("demo", brief) == []

    def test_a_missing_path_is_reported(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            missing = str(tmp_path / "does-not-exist.txt")
            brief = _brief.TaskBrief(objective="x", resources=[f"path:{missing}"])
            assert _pre_hop._check_brief_resources("demo", brief) == [f"path:{missing}"]

    def test_an_existing_path_is_not_missing(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            present = tmp_path / "exists.txt"
            present.write_text("x")
            brief = _brief.TaskBrief(objective="x", resources=[f"path:{present}"])
            assert _pre_hop._check_brief_resources("demo", brief) == []

    def test_verify_is_missing_with_no_configured_verify_cmd(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            brief = _brief.TaskBrief(objective="x", resources=["verify"])
            assert _pre_hop._check_brief_resources("demo", brief) == ["verify"]

    def test_verify_is_not_missing_once_the_implementer_has_a_verify_cmd(
        self, tmp_path: Path
    ) -> None:
        with _seed_pod(tmp_path):
            _fleet.meta_set(_pod.pod.member_id("demo", "implementer"), "verifyCmd", "pytest -q")
            brief = _brief.TaskBrief(objective="x", resources=["verify"])
            assert _pre_hop._check_brief_resources("demo", brief) == []

    def test_a_brief_with_no_resources_has_nothing_missing(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            assert _pre_hop._check_brief_resources("demo", _brief.TaskBrief(objective="x")) == []


class TestRequireVerify:
    def test_require_verify_true_fails_task_with_no_verify_cmd(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When requireVerify is true, a task fails immediately if no verifyCmd is set."""
        with _seed_pod(tmp_path):
            _fleet.meta_set("demo-lead", "requireVerify", True)

            backend = _ScriptedBackend(
                [_final_response("lead plan"), _final_response("implementer done")]
            )
            driver = DocketDriver(backend_factory=lambda model: backend)
            monkeypatch.setattr(_dr, "default_driver", lambda: driver)

            _queue.enqueue_task_once("demo", "Should fail verification", channel="cli")
            results = _sweep.dispatch_pod("demo")
            assert results[0].status == "failed"
            assert "verifyCmd required but not set" in results[0].reason

    def test_require_verify_false_skips_missing_verify_cmd(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When requireVerify is false (the default), a task with no verifyCmd reaches done."""
        with _seed_pod(tmp_path):
            # Explicitly set requireVerify to False (or just use default)
            _fleet.meta_set("demo-lead", "requireVerify", False)

            backend = _ScriptedBackend(
                [_final_response("lead plan"), _final_response("implementer done")]
            )
            driver = DocketDriver(backend_factory=lambda model: backend)
            monkeypatch.setattr(_dr, "default_driver", lambda: driver)

            _queue.enqueue_task_once("demo", "Should skip verification", channel="cli")
            results = _sweep.dispatch_pod("demo")
            assert results[0].status == "done"


class TestIntakeRecipeTaskBrief:
    def test_needs_input_then_ready_reaches_the_implementer_with_a_brief_view(
        self, tmp_path: Path
    ) -> None:
        with _seed_pod(tmp_path, roles=("lead", "implementer", "reviewer")):
            _bind_intake_pipeline("demo")
            task = _queue.enqueue_task_once("demo", "build the widget", channel="cli")[0]
            runner = _IntakeRunner([_LEAD_NEEDS_INPUT_REPLY, _LEAD_READY_REPLY])

            first = _sweep.dispatch_pod("demo", runner=runner)
            assert first[0].status == "waiting_input"
            question = _queue.read_tasks("demo")[0]["question"]
            assert question["requestedSchema"]["properties"]["q1"]["title"] == "Which color?"
            assert question["requestedSchema"]["properties"]["q2"]["title"] == "Which size?"
            assert question["requestedSchema"]["required"] == ["q1", "q2"]
            assert question["message"] == "The Lead needs answers before starting: add a widget"

            _answers.answer_task(
                "demo",
                task["id"],
                "accept",
                {"q1": "blue", "q2": "large"},
                channel="cli",
                actor="op",
            )

            final = _sweep.dispatch_pod("demo", runner=runner)
            assert final[0].status == "done"

            implementer_messages = [msg for role, msg in runner.calls if role == "implementer"]
            assert len(implementer_messages) == 1
            implementer_message = implementer_messages[0]
            assert "## Brief" in implementer_message
            assert "widget renders" in implementer_message
            assert "matches spec" in implementer_message
            # The READY reply is the *latest* brief-bearing hop -- its own prose preamble is
            # replaced by "## Brief" entirely. The earlier NEEDS-INPUT hop's prose is still
            # carried forward as ordinary prior-hop context (unaffected by this feature).
            assert _LEAD_READY_SENTINEL not in implementer_message

    def test_a_brief_naming_a_missing_secret_blocks_with_resources(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path, roles=("lead", "implementer", "reviewer")):
            _bind_intake_pipeline("demo")
            _queue.enqueue_task_once("demo", "call the API", channel="cli")
            runner = _IntakeRunner([_LEAD_READY_MISSING_SECRET_REPLY])

            results = _sweep.dispatch_pod("demo", runner=runner)

            assert results[0].status == "blocked"
            task = _queue.read_tasks("demo")[0]
            assert task["status"] == "blocked"
            assert task["blockedReason"] == "resources"
            assert "secret:MISSING_KEY" in task["reason"]
            assert _oc.a2a_state("blocked", blocked_reason=task["blockedReason"]) == "AUTH_REQUIRED"
            # No Implementer hop was ever attempted -- the check happens before that turn.
            assert [h["role"] for h in task["hops"]] == ["lead"]

    def test_a_resources_block_does_not_stop_the_run_from_claiming_the_next_task(
        self, tmp_path: Path
    ) -> None:
        with _seed_pod(tmp_path, roles=("lead", "implementer", "reviewer")):
            _bind_intake_pipeline("demo")
            _queue.enqueue_task_once("demo", "call the API", channel="cli")
            _queue.enqueue_task_once("demo", "do the plain thing", channel="cli")
            runner = _IntakeRunner([_LEAD_READY_MISSING_SECRET_REPLY, _LEAD_READY_NO_BRIEF_REPLY])

            results = _sweep.dispatch_pod("demo", runner=runner)

            assert [r.status for r in results] == ["blocked", "done"]

    def test_a_configured_secret_is_not_reported_missing(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path, roles=("lead", "implementer", "reviewer")):
            _bind_intake_pipeline("demo")
            _secrets.save_secrets({"MISSING_KEY": "shh"})
            _queue.enqueue_task_once("demo", "call the API", channel="cli")
            runner = _IntakeRunner([_LEAD_READY_MISSING_SECRET_REPLY])

            results = _sweep.dispatch_pod("demo", runner=runner)

            assert results[0].status == "done"

    def test_a_reply_with_no_parseable_brief_but_a_ready_marker_still_advances(
        self, tmp_path: Path
    ) -> None:
        with _seed_pod(tmp_path, roles=("lead", "implementer", "reviewer")):
            _bind_intake_pipeline("demo")
            _queue.enqueue_task_once("demo", "do the plain thing", channel="cli")
            runner = _IntakeRunner([_LEAD_READY_NO_BRIEF_REPLY])

            results = _sweep.dispatch_pod("demo", runner=runner)

            assert results[0].status == "done"
            task = _queue.read_tasks("demo")[0]
            assert [h["role"] for h in task["hops"]] == ["lead", "implementer", "reviewer"]

    def test_reject_fails_the_task_as_rejected(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path, roles=("lead", "implementer", "reviewer")):
            _bind_intake_pipeline("demo")
            _queue.enqueue_task_once("demo", "delete production", channel="cli")
            runner = _IntakeRunner([_LEAD_REJECT_REPLY])

            results = _sweep.dispatch_pod("demo", runner=runner)

            assert results[0].status == "failed"
            task = _queue.read_tasks("demo")[0]
            assert task["failureKind"] == "rejected"
            assert _oc.a2a_state("failed", failure_kind=task["failureKind"]) == "REJECTED"
