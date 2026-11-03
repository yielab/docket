"""A hop that runs out of budget is asked for a report, and the report is never an approval.

The whole product runs for real as ``python -m docket`` subprocesses; only the model is faked. The
verdict-gated Reviewer spends its rounds, answers ``APPROVE`` in its report, and the task still
fails with ``budget`` and applies no gate. A command that outlives the hop's clock is clamped, one
tool-free request follows, and the hop says the time ran out.
"""

from __future__ import annotations

from collections.abc import Callable

from tests.support import e2e_oracles as oracles
from tests.support.e2e import World
from tests.support.model_server import FakeModel, call, say

REVIEW_PIPELINE = """name: budget-landing-review
steps:
  - plan: lead
  - implement: implementer
  - review: reviewer
    verdict: [APPROVE, REQUEST-CHANGES]
"""

CLOCK_PIPELINE = """name: budget-landing-clock
steps:
  - plan: lead
  - implement: implementer
"""


def test_a_reviewer_that_runs_out_cannot_approve_in_its_report(
    world: Callable[..., World], fake_model: Callable[..., FakeModel]
) -> None:
    model = fake_model(
        script={
            "lead": [say("Plan: nothing to change.")],
            "implementer": [say("Nothing to change.")],
            "reviewer": [
                call("read", "c1", path="one.txt"),
                call("read", "c2", path="two.txt"),
                say("Looked at two files and ran no checks. The change looks fine: APPROVE"),
            ],
        }
    )
    w = world(model, env={"AGENT_LOOP_MAX_ITERATIONS": "2"})
    w.make_pod(REVIEW_PIPELINE)
    task_id = w.add_task("Review the change")

    w.docket("run", "--pipeline", str(w.pipeline), "--timeout", "30", check=False)

    task = w.stored_task(task_id)
    assert task["status"] == "failed" and task["failureKind"] == "budget"
    hop = next(h for h in task["hops"] if h["stepId"] == "review")
    assert hop["ok"] is False
    assert hop["budget"]["bound"] == "rounds"
    assert hop["artifact"]["summary"].endswith("APPROVE")
    assert hop["artifact"]["verdict"] is None
    landing = model.by_role("reviewer")[2]
    assert landing.tools == [] and "rounds" in landing.last_user_text
    skeleton = oracles.trace_skeleton(w, w.pod, task_id)
    assert ("hop_finished", "reviewer", "fail") in skeleton
    assert not any(event[0] in ("route_taken", "rework_started") for event in skeleton)


def test_a_command_that_outlives_the_hop_clock_ends_in_one_landing_request(
    world: Callable[..., World], fake_model: Callable[..., FakeModel]
) -> None:
    model = fake_model(
        script={
            "lead": [say("Plan: wait.")],
            "implementer": [
                call("bash", "c1", command="tail -f /dev/null"),
                say("Waited for a command; it was cut off. Nothing was changed."),
            ],
        }
    )
    w = world(model)
    w.make_pod(CLOCK_PIPELINE)
    task_id = w.add_task("Wait for the command")

    w.docket("run", "--pipeline", str(w.pipeline), "--timeout", "1", check=False)

    task = w.stored_task(task_id)
    assert task["status"] == "failed" and task["failureKind"] == "budget"
    hop = next(h for h in task["hops"] if h["stepId"] == "implement")
    assert hop["budget"]["bound"] == "time" and hop["budget"]["limit"] == 1
    requests = model.by_role("implementer")
    assert len(requests) == 2 and requests[1].tools == []
    assert hop["artifact"]["summary"].startswith("Waited for a command")
