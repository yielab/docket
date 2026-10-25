"""A reviewer's verdict is read from the last line of its final message, however it is dressed.

The whole product runs for real as ``python -m docket`` subprocesses; only the model is faked. A
marker wrapped in markdown still counts, a reply with no marker is asked for once more, and a
reply that still has none fails the task as it always did.
"""

from __future__ import annotations

from collections.abc import Callable

from tests.support import e2e_oracles as oracles
from tests.support.e2e import World
from tests.support.model_server import FakeModel, say

PIPELINE = """name: verdict-contract
steps:
  - plan: lead
  - implement: implementer
  - review: reviewer
    verdict: [APPROVE, REQUEST-CHANGES]
"""

REASK = "Your reply had no verdict line. Reply with exactly one line: APPROVE or REQUEST-CHANGES."


def _run(world: World, model: FakeModel) -> str:
    world.make_pod(PIPELINE)
    task_id = world.add_task("Review the change")
    world.docket("run", "--pipeline", str(world.pipeline), "--timeout", "30", check=False)
    return task_id


def _events(world: World, task_id: str, kind: str) -> list[dict[str, object]]:
    return [e for e in oracles.trace_events(world, world.pod, task_id) if e["event_type"] == kind]


def test_a_marker_wrapped_in_markdown_still_approves(
    world: Callable[..., World], fake_model: Callable[..., FakeModel]
) -> None:
    model = fake_model(
        script={
            "lead": [say("Plan: nothing to change.")],
            "implementer": [say("Nothing to change.")],
            "reviewer": [say("The change is correct and tested.\n\n**APPROVE**")],
        }
    )
    w = world(model)
    task_id = _run(w, model)

    assert w.task(task_id)["task"]["status"] == "done"
    assert len(model.by_role("reviewer")) == 1
    assert _events(w, task_id, "verdict_reasked") == []
    assert ("hop_finished", "reviewer", "approve") in oracles.trace_skeleton(w, w.pod, task_id)


def test_a_reply_without_a_verdict_is_asked_once_more_and_the_answer_counts(
    world: Callable[..., World], fake_model: Callable[..., FakeModel]
) -> None:
    model = fake_model(
        script={
            "lead": [say("Plan: nothing to change.")],
            "implementer": [say("Nothing to change.")],
            "reviewer": [say("The change is correct and tested."), say("APPROVE")],
        }
    )
    w = world(model)
    task_id = _run(w, model)

    assert w.task(task_id)["task"]["status"] == "done"
    reviewer = model.by_role("reviewer")
    assert len(reviewer) == 2
    assert reviewer[1].last_user_text == REASK
    assert len(_events(w, task_id, "verdict_reasked")) == 1
    assert _events(w, task_id, "reviewer_verdict_unparseable") == []
    assert ("hop_finished", "reviewer", "approve") in oracles.trace_skeleton(w, w.pod, task_id)


def test_a_reply_that_still_has_no_verdict_fails_after_the_single_re_ask(
    world: Callable[..., World], fake_model: Callable[..., FakeModel]
) -> None:
    model = fake_model(
        script={
            "lead": [say("Plan: nothing to change.")],
            "implementer": [say("Nothing to change.")],
            "reviewer": [say("Seems fine."), say("Yes, fine.")],
        }
    )
    w = world(model)
    task_id = _run(w, model)

    assert w.task(task_id)["task"]["status"] == "failed"
    assert len(model.by_role("reviewer")) == 2
    assert len(_events(w, task_id, "verdict_reasked")) == 1
    assert len(_events(w, task_id, "reviewer_verdict_unparseable")) == 1
    assert "unparseable" in w.docket("inbox", "--json").json()["failed"][0]["reason"]
