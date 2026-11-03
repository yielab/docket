"""A hop that runs out of rounds is a budget outcome, and the work it wrote is kept on the branch.

The Implementer writes `app.txt` and keeps asking for tools until its three rounds are spent. The
task settles `failed` with `failureKind: budget`, the hop says which bound ran out and where the
limit came from, and `docket task diff` shows the file the hop wrote.
"""

from __future__ import annotations

from collections.abc import Callable

from tests.support.e2e import World
from tests.support.model_server import FakeModel, call, say, write_file

PIPELINE = """name: budget-keeps-the-work
steps:
  - plan: lead
  - implement: implementer
"""

DESCRIPTION = "Make app.txt say fixed"


def test_a_hop_out_of_rounds_is_a_budget_outcome_and_its_file_is_in_the_diff(
    world: Callable[..., World], fake_model: Callable[..., FakeModel]
) -> None:
    model = fake_model(
        script={
            "lead": [say("Plan: make app.txt say fixed.")],
            "implementer": [
                write_file("app.txt", "fixed\n"),
                call("bash", "c1", command="cat app.txt"),
                call("bash", "c2", command="cat app.txt"),
                say("Done"),
            ],
        }
    )
    w = world(model, env={"AGENT_LOOP_MAX_ITERATIONS": "3"})
    w.make_pod(PIPELINE)
    task_id = w.add_task(DESCRIPTION)

    w.docket("run", "--pipeline", str(w.pipeline), "--timeout", "30", check=False)

    task = w.stored_task(task_id)
    assert task["status"] == "failed"
    assert task["failureKind"] == "budget"
    hop = next(h for h in task["hops"] if h["stepId"] == "implement")
    assert hop["ok"] is False
    assert hop["attempts"] == 1
    assert hop["budget"] == {
        "bound": "rounds",
        "limit": 3,
        "used": 3,
        "source": "default",
        "raise": "AGENT_LOOP_MAX_ITERATIONS",
        "treeChanged": True,
    }
    assert hop["error"].endswith("(source: default; raise AGENT_LOOP_MAX_ITERATIONS)")
    assert hop["artifact"]["files_changed"] == ["app.txt"]
    assert "+fixed" in w.docket("task", "diff", task_id).out
