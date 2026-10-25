"""A running service starts the team from a webhook and from a schedule, with no one adding a task.

``docket start --dispatch`` is driven over HTTP: a webhook carries its variables into the
pipeline, and a pod's schedule fires on the first sweep. The product runs for real; only the
model is faked, one scripted reply per turn.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from tests.support import e2e_oracles as oracles
from tests.support.e2e import Service, World
from tests.support.model_server import FakeModel, say, write_file

PIPELINE = """name: ticket-triage
variables:
  TICKET:
    required: true
steps:
  - plan: lead
    instructions: "Triage ticket ${TICKET} and plan the change."
  - implement: implementer
  - review: reviewer
    verdict: [APPROVE, REQUEST-CHANGES]
  - test: tester
    verdict: [PASS, FAIL]
"""

NIGHTLY = """name: nightly-sweep
steps:
  - plan: lead
  - implement: implementer
"""

TEAM = {
    "lead": [say("Plan: make app.txt say fixed.")],
    "implementer": [write_file("app.txt", "fixed\n"), say("app.txt says fixed.")],
    "reviewer": [say("APPROVE")],
    "tester": [say("PASS")],
}


def _provision_the_pod(w: World, pipeline: str) -> None:
    w.make_pod(pipeline)
    w.docket("pod", "set", "pipeline", str(w.pipeline))


def _the_run(w: World, svc: Service, run_id: str, state: str) -> dict[str, Any]:
    def found() -> bool:
        status, run = svc.get(f"/runs/{run_id}")
        return status == 200 and run["state"] == state

    w.wait_for(found, 30, f"run {run_id} to be {state}")
    _, run = svc.get(f"/runs/{run_id}")
    assert isinstance(run, dict)
    return run


def test_a_webhook_runs_the_pipeline_with_its_variables(
    world: Callable[..., World], fake_model: Callable[..., FakeModel]
) -> None:
    model = fake_model(script=TEAM)
    w = world(model)
    _provision_the_pod(w, PIPELINE)
    head_before = w.head()
    task_id = w.add_task("Make app.txt say fixed")

    with w.service(dispatch=False) as svc:
        status, missing = svc.post(f"/dispatch/{w.pod}", {})
        assert status == 400 and "TICKET" in missing["error"]
        status, dispatched = svc.post(f"/dispatch/{w.pod}", {"TICKET": "E2E-42"})
        assert (status, dispatched["status"]) == (200, "dispatched")
        run = _the_run(w, svc, dispatched["run"], "succeeded")
        _, listed = svc.get(f"/runs?project={w.pod}")

    assert (run["source"], run["variables"], run["taskIds"]) == (
        "webhook",
        {"TICKET": "E2E-42"},
        [task_id],
    )
    assert [r["id"] for r in listed["runs"]] == [dispatched["run"]]
    lead_asked = model.by_role("lead")[0].last_user_text
    assert "Triage ticket E2E-42 and plan the change." in lead_asked
    assert w.task(task_id)["task"]["status"] == "done"
    oracles.assert_checkout_untouched(w, head_before)
    oracles.assert_audit_covers_tool_calls(w, w.pod, task_id)
    oracles.assert_log_verifies(w)


def test_a_schedule_fires_on_the_first_sweep(
    world: Callable[..., World], fake_model: Callable[..., FakeModel]
) -> None:
    model = fake_model(script={})
    w = world(model)
    _provision_the_pod(w, NIGHTLY)
    w.docket("pod", "set", "schedule", "@every 1h")

    with w.service(interval=1) as svc:

        def scheduled() -> list[dict[str, Any]]:
            _, listed = svc.get(f"/runs?project={w.pod}")
            return [r for r in listed["runs"] if r["source"] == "schedule"]

        w.wait_for(lambda: scheduled() and scheduled()[0]["state"] != "running", 30, "the schedule")
        runs = scheduled()

    assert [(r["project"], r["state"], r["error"], r["taskIds"]) for r in runs] == [
        (w.pod, "succeeded", "", [])
    ]
    assert model.requests == []
    oracles.assert_log_verifies(w)
