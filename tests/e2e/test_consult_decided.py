"""A pod that decides its own consultations never waits for a person.

With `consultMode decide` a `consult` call answers in the turn with the model's own
recommendation: the task goes straight to done, the inbox stays empty, and the trace and the
audit log record that the pod, not an operator, decided. With the default `park` the same call
still waits. Only the model is faked; the repo, the worktree and the audit log are real.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from tests.support import e2e_oracles as oracles
from tests.support.e2e import World
from tests.support.model_server import FakeModel, call, say, write_file

PIPELINE = """name: decide-alone
steps:
  - implement: implementer
"""

CACHE_QUESTION = {
    "message": "Which cache should the service use?",
    "kind": "decision",
    "options": [
        {"id": "redis", "label": "Redis", "description": "already deployed"},
        {"id": "memcached", "label": "Memcached", "description": "simpler"},
    ],
    "recommendation": {"optionId": "redis", "rationale": "it is already deployed"},
}
DECIDED = "no operator on duty; your recommendation stands: option redis (Redis). Continue."


def _drain(w: World) -> None:
    """One `docket run` over the pod's queue."""
    w.docket("run", "--pipeline", str(w.pipeline), "--timeout", "30")


def _state(w: World, task_id: str) -> str:
    """The task's status word, as `task show` prints it."""
    return str(w.task(task_id)["task"]["status"])


def _waiting_on_you(w: World) -> list[dict[str, Any]]:
    """The inbox rows that wait for a person."""
    rows = w.docket("inbox", "--peek", "--json").json()
    return list(rows["needsYou"])


def test_a_deciding_pod_applies_the_recommendation_and_finishes_without_a_person(
    world: Callable[..., World], fake_model: Callable[..., FakeModel]
) -> None:
    model = fake_model(
        script={
            "implementer": [
                call("consult", "k1", **CACHE_QUESTION),
                write_file("cache.txt", "redis\n"),
                say("Wrote the service against Redis."),
            ]
        }
    )
    w = world(model)
    w.make_pod(PIPELINE)
    w.docket("pod", "set", "consultMode", "decide", "--pod", w.pod)
    head_before = w.head()
    task_id = w.add_task("Add a cache to the service")
    statuses = [_state(w, task_id)]

    _drain(w)
    statuses.append(_state(w, task_id))

    assert statuses == ["pending", "done"]
    first, second, third = model.by_role("implementer")
    assert first.tool_result("k1") is None
    assert second.tool_result("k1") == DECIDED
    consult = next(t for t in third.body["tools"] if t["function"]["name"] == "consult")
    assert "returns at once with your recommendation applied" in consult["function"]["description"]
    asked = [
        e["payload"]
        for e in oracles.trace_events(w, w.pod, task_id)
        if e["event_type"] == "question_asked"
    ]
    assert [(p["mode"], p["decidedOptionId"]) for p in asked] == [("decided", "redis")]
    (decision,) = [
        e["payload"]
        for e in oracles.trace_events(w, w.pod, task_id)
        if e["event_type"] == "escalation_decided"
    ]
    assert (decision["kind"], decision["by"], decision["optionId"]) == (
        "consult",
        "policy",
        "redis",
    )
    assert (decision["policy"], decision["task"]) == ("recommendation", task_id)
    decided = [r for r in oracles.audit_rows(w) if r["action"] == "consult.decided"]
    assert len(decided) == 1
    assert f"task={task_id}" in decided[0]["detail"] and "optionId=redis" in decided[0]["detail"]
    assert CACHE_QUESTION["message"] not in decided[0]["detail"]
    assert _waiting_on_you(w) == []
    assert "waiting_input" not in statuses
    assert all(e["event_type"] != "input_answered" for e in oracles.trace_events(w, w.pod, task_id))
    oracles.assert_checkout_untouched(w, head_before)
    oracles.assert_sentinel_untouched(w)
    oracles.assert_audit_covers_tool_calls(w, w.pod, task_id)
    oracles.assert_transitions_legal(statuses)
    oracles.assert_log_verifies(w)


def test_a_parking_pod_still_waits_for_an_answer(
    world: Callable[..., World], fake_model: Callable[..., FakeModel]
) -> None:
    model = fake_model(script={"implementer": [call("consult", "k1", **CACHE_QUESTION)]})
    w = world(model)
    w.make_pod(PIPELINE)
    w.docket("pod", "set", "consultMode", "park", "--pod", w.pod)
    task_id = w.add_task("Add a cache to the service")

    _drain(w)

    (asked,) = _waiting_on_you(w)
    assert (asked["id"], asked["state"]) == (task_id, "needs_answer")
    assert _state(w, task_id) == "waiting_input"
    assert [r for r in oracles.audit_rows(w) if r["action"] == "consult.decided"] == []
    assert len(model.by_role("implementer")) == 1
    oracles.assert_log_verifies(w)
