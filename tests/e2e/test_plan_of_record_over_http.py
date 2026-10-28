"""An external plan of record drives a task over HTTP: it is posted, gated, approved and served.

The service runs as ``docket start --dispatch`` and every step is an HTTP call, the way a plan of
record such as a project board makes it. The product runs for real: the pod, its review, the
sweep, the task worktree, the approval queue, the audit log. Only the model is faked, one
scripted reply per turn.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from docket.teams.prompts import shipped_prompt
from tests.support import e2e_oracles as oracles
from tests.support.e2e import Service, World
from tests.support.model_server import FakeModel, Reply, call, say, write_file

PIPELINE = """name: board-task
steps:
  - plan: lead
  - implement: implementer
    verify: "sh checks/verify.sh"
    until: verify
    max: 1
  - review: reviewer
    verdict: [APPROVE, REQUEST-CHANGES]
  - test: tester
    verdict: [PASS, FAIL]
"""

BOARD_TOKEN = {"DOCKET_SERVE_TOKEN": "board-token-kept-across-restarts"}
ROLES = ("lead", "implementer", "reviewer", "tester")
ASKED_COMMAND = "rm -rf build"
SINCE = "2000-01-01T00:00:00Z"


PARKED_THEN_DONE = [
    ("hop_started", "lead", "plan"),
    ("hop_finished", "lead", "ok"),
    ("hop_started", "implementer", "implement"),
    ("hop_finished", "implementer", "fail"),
    ("approval_required", "implementer", ""),
    ("session_end", "lead", "waiting_approval"),
    ("approval_resumed", "lead", ""),
    ("hop_started", "implementer", "implement"),
    ("hop_finished", "implementer", "ok"),
    ("verification", "implementer", "passed"),
    ("hop_started", "reviewer", "review"),
    ("hop_finished", "reviewer", "approve"),
    ("hop_started", "tester", "test"),
    ("hop_finished", "tester", "pass"),
    ("session_end", "lead", "done"),
]


def _team_script() -> dict[str, list[Reply]]:
    asked = call("bash", command=ASKED_COMMAND)
    return {
        "lead": [say("Plan: make app.txt say fixed.")],
        "implementer": [asked, asked, write_file("app.txt", "fixed\n"), say("app.txt says fixed.")],
        "reviewer": [say("APPROVE")],
        "tester": [say("PASS")],
    }


def _commit_the_team_into_the_repo(w: World) -> str:
    """Provision the pod, bind the pipeline, keep the team in ``.docket/`` and return the head."""
    w.make_pod(PIPELINE)
    w.docket("pod", "set", "pipeline", str(w.pipeline))
    gate = w.docket("pod", "check", ASKED_COMMAND, "--role", "implementer").out
    assert "Result: ask" in gate, gate
    w.docket("pod", "export")
    w.git("add", "-A")
    w.git("commit", "-q", "-m", "keep the team in the repository")
    return w.head()


def _post_the_task(w: World, svc: Service) -> str:
    body = {
        "description": "Make app.txt say fixed",
        "externalRef": "BOARD-7",
        "idempotencyKey": "board-7-first",
        "baseRef": "main",
    }
    status, created = svc.post(f"/tasks/{w.pod}", body)
    assert (status, created["created"], created["status"]) == (201, True, "pending"), created
    return str(created["task"])


def _task_status(w: World, svc: Service, task_id: str) -> str:
    status, shown = svc.get(f"/tasks/{w.pod}/{task_id}")
    return str(shown["status"]) if status == 200 else ""


def _wait_for_status(w: World, svc: Service, task_id: str, wanted: str) -> dict[str, Any]:
    w.wait_for(lambda: _task_status(w, svc, task_id) == wanted, 30, f"the task to be {wanted}")
    _, shown = svc.get(f"/tasks/{w.pod}/{task_id}")
    assert isinstance(shown, dict)
    return shown


def _served_trace(w: World, svc: Service, task_id: str) -> list[dict[str, Any]]:
    """The task's events as ``GET /traces/<pod>`` serves them, once its session ended done."""

    def events() -> list[dict[str, Any]]:
        _, page = svc.get(f"/traces/{w.pod}?since={SINCE}")
        return [e for e in map(json.loads, page["events"]) if task_id in e["session_id"]]

    ended = ("session_end", "lead", "done")
    w.wait_for(lambda: ended in oracles.skeleton_of(events()), 30, "the served trace to end")
    return events()


def test_a_task_posted_over_http_runs_the_team_and_serves_its_diff(
    world: Callable[..., World], fake_model: Callable[..., FakeModel]
) -> None:
    model = fake_model(script=_team_script())
    w = world(model)
    head_before = _commit_the_team_into_the_repo(w)

    with w.service() as svc:
        status, served = svc.get("/status.json")
        assert status == 200 and int(served["apiVersion"]) >= 6

        status, pod = svc.post("/pods", {"name": w.pod, "ensure": True, "location": str(w.repo)})
        assert (status, pod["created"]) == (200, False)
        status, planned = svc.post(f"/pods/{w.pod}/apply", {"dryRun": True})
        assert (status, planned["dryRun"]) == (200, True)
        status, review = svc.post(f"/pods/{w.pod}/apply", {})
        assert status == 409 and review["runs"] == [
            {"kind": "verify", "name": "implement", "runs": "sh checks/verify.sh"}
        ]
        status, applied = svc.post(f"/pods/{w.pod}/apply", {"accept": review["reviewCode"]})
        assert (status, applied["dryRun"]) == (200, False)

        task_id = _post_the_task(w, svc)
        parked = _wait_for_status(w, svc, task_id, "waiting_approval")
        escalation = parked["escalations"][-1]
        assert escalation.startswith("esc-") and parked["externalRef"] == "BOARD-7"
        assert [h["role"] for h in parked["hops"]] == ["lead", "implementer"]

        status, granted = svc.post(f"/escalations/{escalation}", {"optionId": "approve_once"})
        assert (status, granted["state"]) == (200, "resolved")
        status, dispatched = svc.post(f"/dispatch/{w.pod}")
        assert (status, dispatched["status"]) == (200, "dispatched")
        done = _wait_for_status(w, svc, task_id, "done")
        implementer = next(h for h in done["hops"] if h["role"] == "implementer")
        layers = {entry["layer"]: entry for entry in implementer["promptManifest"]["layers"]}
        assert layers["hop"]["sha256"] == shipped_prompt("hop", "implementer").sha256
        assert layers["identity"]["sha256"] == shipped_prompt("identity", "implementer").sha256
        statuses = ["pending", "waiting_approval", done["status"]]

        status, diff = svc.get(f"/tasks/{w.pod}/{task_id}/diff")
        assert status == 200 and "-broken" in diff["patch"] and "+fixed" in diff["patch"]
        served_trace = _served_trace(w, svc, task_id)

        status, again = svc.post(
            f"/tasks/{w.pod}", {"description": "x", "idempotencyKey": "board-7-first"}
        )
        assert (status, again["created"], again["task"]) == (200, False, task_id)

    assert oracles.skeleton_of(served_trace) == PARKED_THEN_DONE
    assert oracles.trace_skeleton(w, w.pod, task_id) == PARKED_THEN_DONE
    oracles.assert_checkout_untouched(w, head_before)
    oracles.assert_sentinel_untouched(w)
    oracles.assert_audit_covers_tool_calls(w, w.pod, task_id, refused=1)
    oracles.assert_transitions_legal(statuses)
    oracles.assert_log_verifies(w)


def test_a_parked_task_survives_a_service_restart_and_resumes_from_disk(
    world: Callable[..., World], fake_model: Callable[..., FakeModel]
) -> None:
    model = fake_model(script=_team_script())
    w = world(model, env=BOARD_TOKEN)
    head_before = _commit_the_team_into_the_repo(w)

    with w.service() as first:
        task_id = _post_the_task(w, first)
        parked = _wait_for_status(w, first, task_id, "waiting_approval")
    heard_before = {role: len(model.by_role(role)) for role in ROLES}

    with w.service() as second:
        again = _wait_for_status(w, second, task_id, "waiting_approval")
        assert again["escalations"] == parked["escalations"]
        assert again["hops"] == parked["hops"]
        status, granted = second.post(
            f"/escalations/{parked['escalations'][-1]}", {"optionId": "approve_once"}
        )
        assert (status, granted["state"]) == (200, "resolved")
        second.post(f"/dispatch/{w.pod}")
        _wait_for_status(w, second, task_id, "done")

    assert heard_before == {"lead": 1, "implementer": 1, "reviewer": 0, "tester": 0}
    heard_after = {role: len(model.by_role(role)) for role in ROLES}
    assert heard_after == {"lead": 1, "implementer": 4, "reviewer": 1, "tester": 1}
    assert oracles.trace_skeleton(w, w.pod, task_id) == PARKED_THEN_DONE
    oracles.assert_checkout_untouched(w, head_before)
    oracles.assert_audit_covers_tool_calls(w, w.pod, task_id, refused=1)
    oracles.assert_transitions_legal(["pending", "waiting_approval", "done"])
    oracles.assert_log_verifies(w)


def test_a_task_that_asks_for_wider_permissions_is_refused(
    world: Callable[..., World], fake_model: Callable[..., FakeModel]
) -> None:
    model = fake_model(script={})
    w = world(model)
    _commit_the_team_into_the_repo(w)
    allow_bash = {
        "kind": "policy",
        "name": "let-bash",
        "appliesTo": ["*"],
        "when": {"tool": "bash"},
    }
    wider = {
        "description": "Run anything",
        "restrictions": {"policies": [{**allow_bash, "then": "allow"}]},
    }
    narrower = {
        "description": "Run less",
        "restrictions": {"policies": [{**allow_bash, "then": "block"}]},
    }

    with w.service(dispatch=False) as svc:
        _, before = svc.get(f"/tasks/{w.pod}")
        status, refused = svc.post(f"/tasks/{w.pod}", wider)
        _, after = svc.get(f"/tasks/{w.pod}")
        status_narrower, created = svc.post(f"/tasks/{w.pod}", narrower)

    assert before == {"tasks": []}
    assert status == 422 and refused["ok"] is False and "block" in refused["error"]
    assert after == before
    assert (status_narrower, created["created"]) == (201, True)
    enqueued = [r for r in oracles.audit_rows(w) if r["action"] == "task.enqueue"]
    assert [created["task"] in r["detail"] for r in enqueued] == [True]
    assert model.requests == []
