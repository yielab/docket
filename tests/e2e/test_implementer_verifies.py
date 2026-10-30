"""The Implementer is told how it will be judged and can run that judge before it finishes.

The step's verify command is named in the Implementer's first request, a `verify` tool runs
exactly that command in the task worktree, and the mechanical gate still decides after the hop.
"""

from __future__ import annotations

from collections.abc import Callable

from tests.support import e2e_oracles as oracles
from tests.support.e2e import World
from tests.support.model_server import FakeModel, call, say, write_file

PIPELINE = """name: implementer-verifies
steps:
  - plan: lead
  - implement: implementer
    verify: "sh checks/verify.sh"
  - review: reviewer
    verdict: [APPROVE, REQUEST-CHANGES]
"""

NO_VERIFY = """name: no-verify
steps:
  - plan: lead
  - implement: implementer
  - review: reviewer
    verdict: [APPROVE, REQUEST-CHANGES]
"""

SENTENCE = (
    "Your work is accepted only if `sh checks/verify.sh` exits 0. Run it with the `verify` tool "
    "and fix what it reports before you finish."
)


def test_the_implementer_runs_the_check_fixes_what_it_reports_and_the_gate_still_decides(
    world: Callable[..., World], fake_model: Callable[..., FakeModel]
) -> None:
    model = fake_model(
        script={
            "lead": [say("Plan: make app.txt say fixed.")],
            "implementer": [
                call("verify", "v1"),
                write_file("app.txt", "fixed\n"),
                call("verify", "v2"),
                say("Ran the check: it passes."),
            ],
            "reviewer": [say("APPROVE")],
        }
    )
    w = world(model)
    w.make_pod(PIPELINE)
    head_before = w.head()
    task_id = w.add_task("Make app.txt say fixed")

    w.docket("run", "--pipeline", str(w.pipeline), "--timeout", "30")

    first, _, third, fourth = model.by_role("implementer")
    assert SENTENCE in first.last_user_text
    assert "verify" in first.tools
    assert "verify" not in model.by_role("reviewer")[0].tools
    assert third.tool_result("v1") == "exit 1"
    assert fourth.tool_result("v2") == "exit 0"
    events = oracles.trace_events(w, w.pod, task_id)
    calls_made = [e["payload"].get("tool") for e in events if e["event_type"] == "tool_call"]
    assert [t for t in calls_made if t == "verify"] == ["verify", "verify"]
    results = [
        e["payload"]
        for e in events
        if e["event_type"] == "tool_result" and e["payload"].get("tool") == "verify"
    ]
    assert [(r["decision"], r["executed"], r["ok"]) for r in results] == [("allow", True, True)] * 2
    assert oracles.trace_skeleton(w, w.pod, task_id) == [
        ("hop_started", "lead", "plan"),
        ("hop_finished", "lead", "ok"),
        ("hop_started", "implementer", "implement"),
        ("hop_finished", "implementer", "ok"),
        ("verification", "implementer", "passed"),
        ("hop_started", "reviewer", "review"),
        ("hop_finished", "reviewer", "approve"),
        ("session_end", "lead", "done"),
    ]
    assert w.task(task_id)["task"]["status"] == "done"
    oracles.assert_checkout_untouched(w, head_before)
    oracles.assert_audit_covers_tool_calls(w, w.pod, task_id)
    oracles.assert_log_verifies(w)


def test_the_gate_still_fails_a_model_that_claims_it_verified(
    world: Callable[..., World], fake_model: Callable[..., FakeModel]
) -> None:
    model = fake_model(
        script={
            "lead": [say("Plan: make app.txt say fixed.")],
            "implementer": [call("verify", "v1"), say("Verified, all good.")],
            "reviewer": [say("APPROVE")],
        }
    )
    w = world(model)
    w.make_pod(PIPELINE)
    task_id = w.add_task("Make app.txt say fixed")

    run = w.docket("run", "--pipeline", str(w.pipeline), "--timeout", "30", check=False)

    assert run.code == 1
    assert model.by_role("implementer")[1].tool_result("v1") == "exit 1"
    assert w.task(task_id)["task"]["status"] == "failed"
    assert model.by_role("reviewer") == []


def test_a_step_without_a_verify_command_offers_no_verify_tool_and_no_sentence(
    world: Callable[..., World], fake_model: Callable[..., FakeModel]
) -> None:
    model = fake_model(
        script={
            "lead": [say("Plan: nothing to check.")],
            "implementer": [say("Done.")],
            "reviewer": [say("APPROVE")],
        }
    )
    w = world(model)
    w.make_pod(NO_VERIFY)
    w.add_task("Do nothing in particular")

    w.docket("run", "--pipeline", str(w.pipeline), "--timeout", "30")

    (only,) = model.by_role("implementer")
    assert "verify" not in only.tools
    assert "accepted only if" not in only.last_user_text
