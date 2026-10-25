"""An A2A client drives a task over ``POST /a2a``: it is sent, parks, is answered and completes.

The service runs as ``docket start --dispatch`` and every step is a JSON-RPC call, the way an A2A
client such as a project board makes it. The product runs for real: the pod, the sweep, the task
worktree, the approval queue, the audit log. Only the model is faked, one scripted reply per turn.
"""

from __future__ import annotations

from collections.abc import Callable

from tests.support import e2e_oracles as oracles
from tests.support.a2a import CONSULT, A2AClient, agent_card
from tests.support.e2e import World
from tests.support.model_server import FakeModel, call, say, write_file

PIPELINE = "name: board-task\nsteps:\n  - implement: implementer\n"
ASKED_COMMAND = "rm -rf build"
CONSULT_TRACE = [
    ("hop_started", "implementer", "implement"),
    ("hop_finished", "implementer", "fail"),
    ("session_end", "lead", "waiting_input"),
    ("input_answered", "lead", "implement"),
    ("hop_started", "implementer", "implement"),
    ("hop_finished", "implementer", "ok"),
    ("verification", "implementer", "skipped"),
    ("session_end", "lead", "done"),
]


def test_a_task_sent_over_a2a_parks_on_a_consult_is_answered_and_completes(
    world: Callable[..., World], fake_model: Callable[..., FakeModel]
) -> None:
    replies = [
        call("consult", "k1", **CONSULT),
        write_file("cache.txt", "memcached\n"),
        say("done"),
    ]
    w = world(fake_model(script={"implementer": replies}))
    w.make_pod(PIPELINE)
    w.docket("pod", "set", "pipeline", str(w.pipeline))
    head_before = w.head()

    with w.service() as svc:
        assert agent_card(svc, None)[0] == 401
        status, card = agent_card(svc, svc.token)
        assert status == 200 and [s["id"] for s in card["skills"]] == [w.pod]
        client = A2AClient(svc)
        task = client.send_text("Add a cache to the service", "board-7-first")
        task_id = task["id"]
        assert task["status"]["state"] == "SUBMITTED"
        assert client.send_text("Add a cache to the service", "board-7-first")["id"] == task_id

        parked = client.wait_state(w, task_id, "INPUT_REQUIRED")
        data = parked["status"]["message"]["parts"][1]["data"]
        assert data["escalationKind"] == "consult" and data["recommendation"]["optionId"] == "redis"

        answered = client.answer(task_id, "board-7-answer", "accept", optionId="memcached")
        assert "error" not in answered, answered
        done = client.wait_state(w, task_id, "COMPLETED")
        statuses = ["pending", "waiting_input", done["metadata"]["docket"]["status"]]

        _, page = svc.get(f"/escalations?task={task_id}")
        (view,) = page["escalations"]
        assert view["state"] == "resolved" and view["resolution"]["optionId"] == "memcached"
        twice = client.answer(task_id, "board-7-again", "accept", optionId="memcached")
        assert twice["error"]["code"] == -32004

    assert oracles.trace_skeleton(w, w.pod, task_id) == CONSULT_TRACE
    oracles.assert_checkout_untouched(w, head_before)
    oracles.assert_sentinel_untouched(w)
    oracles.assert_audit_covers_tool_calls(w, w.pod, task_id)
    oracles.assert_transitions_legal(statuses)
    oracles.assert_log_verifies(w)


def test_a_denied_command_parks_as_an_approval_the_client_accepts_with_an_option(
    world: Callable[..., World], fake_model: Callable[..., FakeModel]
) -> None:
    asked = call("bash", command=ASKED_COMMAND)
    w = world(fake_model(script={"implementer": [asked, asked, say("cleaned")]}))
    w.make_pod(PIPELINE)
    w.docket("pod", "set", "pipeline", str(w.pipeline))
    gate = w.docket("pod", "check", ASKED_COMMAND, "--role", "implementer").out
    assert "Result: ask" in gate, gate

    with w.service() as svc:
        client = A2AClient(svc)
        task_id = client.send_text("Remove the build directory", "board-8")["id"]
        parked = client.wait_state(w, task_id, "INPUT_REQUIRED")
        message = parked["status"]["message"]
        data = message["parts"][1]["data"]
        assert (data["kind"], data["escalationKind"]) == ("approval", "approval")
        assert ASKED_COMMAND in message["parts"][0]["text"]
        assert "apr-" not in str(parked)

        wrong = client.answer(task_id, "board-8-wrong", "accept", optionId="maybe")
        assert wrong["error"]["code"] == -32602
        assert client.state(task_id) == "INPUT_REQUIRED"
        accepted = client.answer(task_id, "board-8-yes", "accept", optionId="approve_once")
        assert "error" not in accepted, accepted
        client.wait_state(w, task_id, "COMPLETED")

    oracles.assert_audit_covers_tool_calls(w, w.pod, task_id, refused=1)
    oracles.assert_log_verifies(w)


def test_declining_over_a2a_denies_an_approval_and_ends_the_task(
    world: Callable[..., World], fake_model: Callable[..., FakeModel]
) -> None:
    asked = call("bash", command=ASKED_COMMAND)
    w = world(fake_model(script={"implementer": [asked, say("could not clean")]}))
    w.make_pod(PIPELINE)
    w.docket("pod", "set", "pipeline", str(w.pipeline))

    with w.service() as svc:
        client = A2AClient(svc)
        task_id = client.send_text("Remove the build directory", "board-9")["id"]
        client.wait_state(w, task_id, "INPUT_REQUIRED")

        declined = client.answer(task_id, "board-9-no", "decline", reason="not today")
        assert "error" not in declined, declined
        w.wait_for(lambda: client.state(task_id) in ("COMPLETED", "FAILED"), 30, "the task to end")
        _, page = svc.get(f"/escalations?task={task_id}")

    (view,) = page["escalations"]
    assert view["resolution"]["optionId"] == "deny" and view["resolution"]["channel"] == "a2a"
