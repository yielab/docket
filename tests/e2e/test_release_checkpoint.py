"""A pipeline step that needs a person pauses the run before it, and approval resumes right there.

A five-step team fixes one file under a mechanical check and a reviewer verdict, then reaches a
release step that declares its own approval. ``docket run`` stops before that step, the operator
approves from the inbox, and the next ``docket run`` resumes at exactly that step. Only the model
is faked; the repository, task worktree, sessions, runs and audit log are real.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from tests.support import e2e_oracles as oracles
from tests.support.e2e import World
from tests.support.model_server import FakeModel, say, write_file

PIPELINE = """name: release-checkpoint
steps:
  - plan: lead
  - implement: implementer
    verify: "sh checks/verify.sh"
  - review: reviewer
    verdict: [APPROVE, REQUEST-CHANGES]
  - release-check: tester
    approval: "Approve the release checkpoint."
  - final-check: tester
    verdict: [PASS, FAIL]
"""

STEPS = ["plan", "implement", "review", "release-check", "final-check"]
PARKED = [
    ("hop_started", "lead", "plan"),
    ("hop_finished", "lead", "ok"),
    ("hop_started", "implementer", "implement"),
    ("hop_finished", "implementer", "ok"),
    ("verification", "implementer", "passed"),
    ("hop_started", "reviewer", "review"),
    ("hop_finished", "reviewer", "approve"),
    ("approval_required", "tester", ""),
    ("session_end", "lead", "waiting_approval"),
]
RESUMED = [
    ("approval_resumed", "lead", ""),
    ("hop_started", "tester", "release-check"),
    ("hop_finished", "tester", "ok"),
    ("hop_started", "tester", "final-check"),
    ("hop_finished", "tester", "pass"),
    ("session_end", "lead", "done"),
]


def test_a_release_step_with_its_own_approval_pauses_and_resumes_at_that_step(
    world: Callable[..., World], fake_model: Callable[..., FakeModel]
) -> None:
    model = fake_model(
        script={
            "lead": [say("Lead prepared the plan.")],
            "implementer": [
                write_file("app.txt", "fixed\n"),
                say("Implemented the artifact."),
            ],
            "reviewer": [say("APPROVE\nThe artifact is sound.")],
            "tester": [say("Release checklist completed."), say("PASS\nThe artifact is valid.")],
        }
    )
    w = world(model)
    w.make_pod(PIPELINE)
    head_before = w.head()
    task_id = w.add_task("Make app.txt say fixed")
    statuses = [w.task(task_id)["task"]["status"]]

    w.docket("run", "--pipeline", str(w.pipeline), "--timeout", "30")
    statuses.append(w.task(task_id)["task"]["status"])

    (parked,) = w.docket("inbox", "--peek", "--json").json()["needsYou"]
    assert (parked["id"], parked["state"]) == (task_id, "needs_approval")
    assert [h["stepId"] for h in w.task(task_id)["evidence"]["hops"]] == STEPS[:3]
    assert len(model.by_role("tester")) == 0
    assert oracles.trace_skeleton(w, w.pod, task_id) == PARKED

    w.docket("task", "approve", parked["approvalToken"], "--pod", w.pod)
    w.docket("run", "--pipeline", str(w.pipeline), "--timeout", "30")
    shown = w.task(task_id)
    statuses.append(shown["task"]["status"])

    assert statuses == ["pending", "waiting_approval", "done"]
    assert oracles.trace_skeleton(w, w.pod, task_id) == [*PARKED, *RESUMED]
    hops = shown["evidence"]["hops"]
    assert [h["stepId"] for h in hops] == STEPS
    assert [h["verdict"] for h in hops] == [None, None, "approve", None, "pass"]
    assert hops[1]["verify"] is not None
    assert all(h["usage"]["input"] > 0 for h in hops)
    assert sorted(r["state"] for r in shown["runs"]) == ["succeeded", "waiting_approval"]
    artifact = Path(shown["task"]["worktree"]["path"]) / "app.txt"
    assert artifact.read_bytes() == b"fixed\n"

    lead, implementer, reviewer, tester = (
        model.by_role(role) for role in ("lead", "implementer", "reviewer", "tester")
    )
    assert [len(r) for r in (lead, implementer, reviewer, tester)] == [1, 2, 1, 2]
    assert "write" in implementer[0].tools
    assert "Lead prepared the plan." in implementer[0].last_user_text
    wrote = implementer[1].tool_result("call-1")
    assert wrote is not None and "wrote app.txt: 6 bytes" in wrote
    assert "Implemented the artifact." in reviewer[0].last_user_text
    assert "APPROVE" in tester[0].last_user_text
    assert "Release checklist completed." in tester[1].last_user_text
    oracles.assert_checkout_untouched(w, head_before)
    oracles.assert_sentinel_untouched(w)
    oracles.assert_audit_covers_tool_calls(w, w.pod, task_id)
    oracles.assert_transitions_legal(statuses)
    oracles.assert_log_verifies(w)
