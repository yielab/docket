"""A retry runs the step that failed again, in its own session, and does not start over.

The Implementer runs out of rounds after writing the file. `docket task retry` and `docket run`
replay the failed hop to its own index, and its next request continues the session with a
message that names the stop and the changed path instead of repeating the task.
"""

from __future__ import annotations

from collections.abc import Callable

from tests.support import e2e_oracles as oracles
from tests.support.e2e import World
from tests.support.model_server import FakeModel, call, say, write_file

PIPELINE = """name: retry-continues
steps:
  - plan: lead
  - implement: implementer
  - review: reviewer
    verdict: [APPROVE, REQUEST-CHANGES]
"""

DESCRIPTION = "Make app.txt say fixed"


def test_a_retry_continues_the_failed_step_and_the_reviewer_sees_finished_work(
    world: Callable[..., World], fake_model: Callable[..., FakeModel]
) -> None:
    model = fake_model(
        script={
            "lead": [say("Plan: make app.txt say fixed.")],
            "implementer": [
                write_file("app.txt", "fixed\n"),
                call("bash", "c1", command="cat app.txt"),
                call("bash", "c2", command="cat app.txt"),
                say("Wrote app.txt and read it back; the review is still to do."),
                say("Finished"),
            ],
            "reviewer": [say("APPROVE")],
        }
    )
    w = world(model, env={"AGENT_LOOP_MAX_ITERATIONS": "3"})
    w.make_pod(PIPELINE)
    task_id = w.add_task(DESCRIPTION)

    w.docket("run", "--pipeline", str(w.pipeline), "--timeout", "30", check=False)
    assert w.task(task_id)["task"]["status"] == "failed"
    assert len(model.by_role("implementer")) == 4  # three rounds and the report request

    w.docket("task", "retry", task_id, "--pod", w.pod)
    w.docket("run", "--pipeline", str(w.pipeline), "--timeout", "30")

    fourth = model.by_role("implementer")[4]
    assert "stopped before it finished" in fourth.last_user_text
    assert "app.txt" in fourth.last_user_text
    assert "the review is still to do" in fourth.last_user_text
    carrying_the_task = [
        m
        for m in fourth.messages
        if m.get("role") == "user" and DESCRIPTION in str(m.get("content"))
    ]
    assert len(carrying_the_task) == 1
    shown = w.task(task_id)
    task = shown["task"]
    assert task["status"] == "done"
    hops = shown["evidence"]["hops"]
    assert [(h["stepId"], h["ok"]) for h in hops] == [
        ("plan", True),
        ("implement", False),
        ("implement", True),
        ("review", True),
    ]
    assert hops[2]["commit"] is not None and hops[2]["diffStat"]["files"] == 1
    assert hops[3]["commit"] is None and hops[3]["diffStat"] is None
    assert "+fixed" in w.docket("task", "diff", task_id).out
    oracles.assert_log_verifies(w)
