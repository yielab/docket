"""A team takes a failing check to done, and a check that never passes ends the task failed.

The whole product runs for real as ``python -m docket`` subprocesses over a real git repo, a
real task worktree and a real audit log; only the model is faked, one scripted reply per turn.
"""

from __future__ import annotations

from collections.abc import Callable

from tests.support import e2e_oracles as oracles
from tests.support.e2e import World
from tests.support.model_server import FakeModel, Reply, Request, call, calls, fail, say

PIPELINE = """name: solo-run
steps:
  - plan: lead
  - implement: implementer
    verify: "sh checks/verify.sh"
    until: verify
    max: 2
  - review: reviewer
    verdict: [APPROVE, REQUEST-CHANGES]
    on: {REQUEST-CHANGES: {goto: implement, max: 1}}
  - test: tester
    verdict: [PASS, FAIL]
"""

REVIEW_NOTE = "REQUEST-CHANGES: record the fix in NOTES.md"


def _write(path: str, content: str) -> Reply:
    return call("write", path=path, content=content)


def _only_if(marker: str, then: Reply) -> Callable[[Request], Reply]:
    """A step that answers *then* only when the request carries *marker*, else fails loudly."""

    def step(request: Request) -> Reply:
        if marker in request.last_user_text:
            return then
        return fail(400, f"fake model: the request does not carry {marker!r}")

    return step


def test_a_team_takes_a_failing_check_to_done_through_a_retry_and_a_rework(
    world: Callable[..., World], fake_model: Callable[..., FakeModel]
) -> None:
    def first_attempt(request: Request) -> Reply:
        return calls(
            [
                ("write", {"path": "app.txt", "content": "still broken\n"}, "c1"),
                ("write", {"path": str(w.sentinel), "content": "overwritten"}, "c2"),
            ]
        )

    model = fake_model(
        script={
            "lead": [say("Plan: make app.txt say fixed.")],
            "implementer": [
                first_attempt,
                say("app.txt now says still broken."),
                _only_if("GATE FAILED", _write("app.txt", "fixed\n")),
                say("app.txt now says fixed."),
                _only_if(REVIEW_NOTE, _write("NOTES.md", "app.txt says fixed\n")),
                say("Recorded the fix in NOTES.md."),
            ],
            "reviewer": [say(REVIEW_NOTE), say("APPROVE")],
            "tester": [say("PASS")],
        }
    )
    w = world(model)
    w.make_pod(PIPELINE)
    head_before = w.head()
    task_id = w.add_task("Make app.txt say fixed")
    statuses = [w.task(task_id)["task"]["status"]]

    w.docket("run", "--pipeline", str(w.pipeline), "--timeout", "30")
    statuses.append(w.task(task_id)["task"]["status"])

    assert oracles.trace_skeleton(w, w.pod, task_id) == [
        ("hop_started", "lead", "plan"),
        ("hop_finished", "lead", "ok"),
        ("hop_started", "implementer", "implement"),
        ("hop_finished", "implementer", "ok"),
        ("route_taken", "implementer", "fail>implement"),
        ("hop_started", "implementer", "implement"),
        ("hop_finished", "implementer", "ok"),
        ("verification", "implementer", "passed"),
        ("hop_started", "reviewer", "review"),
        ("hop_finished", "reviewer", "request-changes"),
        ("rework_started", "reviewer", "cycle 1"),
        ("hop_started", "implementer", "implement"),
        ("hop_finished", "implementer", "ok"),
        ("verification", "implementer", "passed"),
        ("hop_started", "reviewer", "review"),
        ("hop_finished", "reviewer", "approve"),
        ("hop_started", "tester", "test"),
        ("hop_finished", "tester", "pass"),
        ("session_end", "lead", "done"),
    ]
    assert statuses == ["pending", "done"]
    diff = w.docket("task", "diff", task_id).out
    assert "-broken" in diff and "+fixed" in diff and "NOTES.md" in diff
    oracles.assert_checkout_untouched(w, head_before)
    oracles.assert_sentinel_untouched(w)
    oracles.assert_audit_covers_tool_calls(w, w.pod, task_id, refused=1)
    oracles.assert_transitions_legal(statuses)
    oracles.assert_log_verifies(w)


def test_a_check_that_never_passes_fails_the_task_as_gate_failed(
    world: Callable[..., World], fake_model: Callable[..., FakeModel]
) -> None:
    rewrite = [call("write", path="app.txt", content="broken\n"), say("app.txt is unchanged.")]
    model = fake_model(
        script={
            "lead": [say("Plan: make app.txt say fixed.")],
            "implementer": rewrite * 3,
            "reviewer": [say("APPROVE")],
            "tester": [say("PASS")],
        }
    )
    w = world(model)
    w.make_pod(PIPELINE)
    head_before = w.head()
    task_id = w.add_task("Make app.txt say fixed")

    run = w.docket("run", "--pipeline", str(w.pipeline), "--timeout", "30", check=False)

    failed = w.docket("inbox", "--json").json()["failed"]
    assert [f["id"] for f in failed] == [task_id]
    assert "outcome FAIL" in failed[0]["reason"] and "'implement'" in failed[0]["reason"]
    assert run.code == 1
    assert w.task(task_id)["task"]["status"] == "failed"
    assert model.by_role("reviewer") == []
    assert len(model.by_role("implementer")) == 6
    attempt = [
        ("hop_started", "implementer", "implement"),
        ("hop_finished", "implementer", "ok"),
        ("route_taken", "implementer", "fail>implement"),
    ]
    assert oracles.trace_skeleton(w, w.pod, task_id) == [
        ("hop_started", "lead", "plan"),
        ("hop_finished", "lead", "ok"),
        *attempt,
        *attempt,
        *attempt,
        ("session_end", "lead", "failed"),
    ]
    oracles.assert_checkout_untouched(w, head_before)
    oracles.assert_sentinel_untouched(w)
    oracles.assert_audit_covers_tool_calls(w, w.pod, task_id)
    oracles.assert_transitions_legal(["pending", "failed"])
    oracles.assert_log_verifies(w)
