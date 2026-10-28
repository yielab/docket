"""A task's autonomy level decides what a pause does when nobody is there.

The product runs for real as ``python -m docket`` subprocesses over a real git repo; only the model
is faked. A lights-out pod needs the jail, so the tests that run one skip where none is available.
The measured shape is a model that runs a command that needs approval on an unattended pod: at L5
the task must fail ``needs_human`` in one run instead of waiting for a person who is not there.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from typing import Any

import pytest

from docket.sandbox.landlock import landlock_available
from docket.sandbox.seatbelt import seatbelt_available
from tests.support import e2e_oracles as oracles
from tests.support.e2e import World
from tests.support.model_server import FakeModel, call, say, write_file

GATED = """name: levels
steps:
  - plan: lead
  - implement: implementer
    gate: {external: "sh checks/verify.sh"}
"""

ASKS = """name: asks
steps:
  - plan: lead
  - ask:
      input:
        from: plan
  - implement: implementer
"""

NO_JAIL = not (seatbelt_available() if sys.platform == "darwin" else landlock_available())
needs_jail = pytest.mark.skipif(NO_JAIL, reason="no jail backend (Landlock or Seatbelt) here")

# Inside the jail the allowlist stands down, so the command that still asks is a high-risk class.
ASKED_COMMAND = "git push origin main"
CACHE_QUESTION = {
    "message": "Which cache should the service use?",
    "kind": "decision",
    "options": [
        {"id": "redis", "label": "Redis", "description": "already deployed"},
        {"id": "memcached", "label": "Memcached", "description": "simpler"},
    ],
    "recommendation": {"optionId": "redis", "rationale": "it is already deployed"},
}


def _lights_out_pod(w: World, pipeline: str = GATED, *, jailed: bool = True) -> None:
    """A pod that meets every lights-out requirement (the consult one holds by default)."""
    w.make_pod(pipeline)
    w.docket("setup", "profile", "lights-out")
    if jailed:
        w.docket("setup", "sandbox", "on")
        w.docket("setup", "sandbox", "network", "none")


def _status_of(w: World, task_id: str) -> str:
    return str(w.task(task_id)["task"]["status"])


def _run(w: World) -> int:
    return w.docket("run", "--pipeline", str(w.pipeline), "--timeout", "30", check=False).code


def _events(w: World, task_id: str, event_type: str) -> list[dict[str, Any]]:
    return [
        e["payload"]
        for e in oracles.trace_events(w, w.pod, task_id)
        if e["event_type"] == event_type
    ]


def _the_task(w: World, task_id: str) -> dict[str, Any]:
    """The task's record as the pod's queue file holds it."""
    queue = w.home / "state" / "workspaces" / "projects" / f"{w.pod}-lead" / "TASK_LIST.json"
    records = json.loads(queue.read_text(encoding="utf-8"))
    tasks = records["tasks"] if isinstance(records, dict) else records
    return next(t for t in tasks if t["id"] == task_id)


@needs_jail
def test_an_l5_task_that_needs_approval_fails_needs_human_in_one_run(
    world: Callable[..., World], fake_model: Callable[..., FakeModel]
) -> None:
    model = fake_model(
        script={
            "lead": [say("Plan: make app.txt say fixed.")],
            "implementer": [call("bash", "k1", command=ASKED_COMMAND), say("never reached")],
        }
    )
    w = world(model)
    _lights_out_pod(w)
    head_before = w.head()
    task_id = w.add_task("Make app.txt say fixed", "--autonomy", "L5")
    statuses = [_status_of(w, task_id)]

    code = _run(w)
    statuses.append(_status_of(w, task_id))

    assert code == 1 and statuses == ["pending", "failed"]
    shown = _the_task(w, task_id)
    assert (shown["status"], shown["failureKind"], shown["autonomy"]) == (
        "failed",
        "needs_human",
        "L5",
    )
    assert len(model.by_role("implementer")) == 1
    inbox = w.docket("inbox", "--peek", "--json").json()
    assert inbox["needsYou"] == []
    assert [f["id"] for f in inbox["failed"]] == [task_id]
    (denied,) = _events(w, task_id, "escalation_decided")
    assert (denied["kind"], denied["policy"], denied["level"], denied["by"]) == (
        "approval",
        "deny",
        "L5",
        "policy",
    )
    assert denied["optionId"] == "deny"
    assert _events(w, task_id, "escalation_asked") == []
    assert _events(w, task_id, "approval_required") == []
    (told,) = inbox["decided"]
    assert (told["task"], told["state"], told["level"]) == (task_id, "decided", "L5")
    shown_text = w.docket("task", "show", task_id, "--pod", w.pod).out
    assert "Decided without you" in shown_text and "deny" in shown_text
    oracles.assert_checkout_untouched(w, head_before)
    oracles.assert_audit_covers_tool_calls(w, w.pod, task_id)
    oracles.assert_transitions_legal(statuses)
    oracles.assert_log_verifies(w)


@needs_jail
def test_an_l3_task_on_a_lights_out_pod_parks_for_the_same_command(
    world: Callable[..., World], fake_model: Callable[..., FakeModel]
) -> None:
    model = fake_model(
        script={
            "lead": [say("Plan: make app.txt say fixed.")],
            "implementer": [call("bash", "k1", command=ASKED_COMMAND), say("never reached")],
        }
    )
    w = world(model)
    _lights_out_pod(w)
    task_id = w.add_task("Make app.txt say fixed", "--autonomy", "L3")

    _run(w)

    assert _status_of(w, task_id) == "waiting_approval"
    waiting = w.docket("inbox", "--peek", "--json").json()["needsYou"]
    assert [item["id"] for item in waiting] == [task_id]
    assert _events(w, task_id, "escalation_decided") == []
    (asked,) = _events(w, task_id, "escalation_asked")
    assert (asked["kind"], asked["level"], asked["policy"]) == ("approval", "L3", "person")
    assert _the_task(w, task_id).get("failureKind") is None
    oracles.assert_log_verifies(w)


@needs_jail
def test_an_l4_consult_is_answered_by_the_pod_and_the_task_finishes(
    world: Callable[..., World], fake_model: Callable[..., FakeModel]
) -> None:
    model = fake_model(
        script={
            "lead": [say("Plan: make app.txt say fixed.")],
            "implementer": [
                call("consult", "k1", **CACHE_QUESTION),
                write_file("app.txt", "fixed\n"),
                say("app.txt says fixed."),
            ],
        }
    )
    w = world(model)
    _lights_out_pod(w)
    task_id = w.add_task("Make app.txt say fixed")
    statuses = [_status_of(w, task_id)]

    code = _run(w)
    statuses.append(_status_of(w, task_id))

    assert code == 0 and statuses == ["pending", "done"]
    (decided,) = _events(w, task_id, "escalation_decided")
    assert (decided["kind"], decided["policy"], decided["level"], decided["optionId"]) == (
        "consult",
        "recommendation",
        "L4",
        "redis",
    )
    assert w.docket("inbox", "--peek", "--json").json()["needsYou"] == []
    assert _the_task(w, task_id)["status"] == "done"
    oracles.assert_transitions_legal(statuses)
    oracles.assert_log_verifies(w)


def test_a_level_above_the_ceiling_is_refused_by_the_api_and_the_cli(
    world: Callable[..., World], fake_model: Callable[..., FakeModel]
) -> None:
    w = world(fake_model(script={}))
    w.make_pod(GATED)

    with w.service(dispatch=False) as svc:
        status, refused = svc.post(f"/tasks/{w.pod}", {"description": "x", "autonomy": "L5"})
        assert status == 422 and "L3" in refused["error"], refused
        status, narrowed = svc.post(f"/tasks/{w.pod}", {"description": "x", "autonomy": "L3"})
        assert status == 201, narrowed
        status, malformed = svc.post(f"/tasks/{w.pod}", {"description": "y", "autonomy": "L9"})
        assert status == 400, malformed
        w.docket("setup", "profile", "lights-out")
        status, admitted = svc.post(f"/tasks/{w.pod}", {"description": "z", "autonomy": "L5"})
        assert status == 201, admitted
    w.docket("setup", "profile", "attended")
    cli = w.docket("task", "add", "w", "--autonomy", "L5", "--pod", w.pod, check=False)
    assert cli.code == 1 and "ceiling L3" in cli.out + cli.err
    listed = w.docket("task", "list", "--pod", w.pod, "--json").json()["tasks"]
    assert sorted(t["description"] for t in listed) == ["x", "z"]


def test_an_input_step_is_refused_before_any_hop_for_a_task_at_l4(
    world: Callable[..., World], fake_model: Callable[..., FakeModel]
) -> None:
    model = fake_model(script={"lead": [say("Plan.")]})
    w = world(model)
    _lights_out_pod(w, ASKS, jailed=False)
    head_before = w.head()
    task_id = w.add_task("Make app.txt say fixed", "--autonomy", "L4")

    code = _run(w)

    assert code == 1 and _status_of(w, task_id) == "failed"
    shown = _the_task(w, task_id)
    assert shown["failureKind"] == "pipeline"
    assert "'ask'" in shown["reason"] and "L4" in shown["reason"] and "L3" in shown["reason"]
    assert model.requests == []
    oracles.assert_checkout_untouched(w, head_before)
    oracles.assert_log_verifies(w)
