"""A lights-out pod refuses to run until it is locked down, and a task's token budget is a ceiling.

The product runs for real as ``python -m docket`` subprocesses over a real git repo; only the
model is faked. The test that fixes the violations skips where no jail backend is available.
"""

from __future__ import annotations

import sys
from collections.abc import Callable

import pytest

from docket.sandbox.landlock import landlock_available
from docket.sandbox.seatbelt import seatbelt_available
from tests.support import e2e_oracles as oracles
from tests.support.e2e import World
from tests.support.model_server import FakeModel, say, write_file

UNGATED = """name: unattended
steps:
  - plan: lead
  - implement: implementer
    verify: "sh checks/verify.sh"
    until: verify
    max: 1
"""

GATED = """name: unattended
steps:
  - plan: lead
  - implement: implementer
    gate: {external: "sh checks/verify.sh"}
"""

NO_JAIL = not (seatbelt_available() if sys.platform == "darwin" else landlock_available())
FIXES = ("isolation", "network", "external-gate")
OVER_BUDGET = 6000


def _team_script() -> dict[str, list]:
    return {
        "lead": [say("Plan: make app.txt say fixed.")],
        "implementer": [write_file("app.txt", "fixed\n"), say("app.txt says fixed.")],
    }


def _failure_reason(w: World, task_id: str) -> str:
    failed = w.docket("inbox", "--json").json()["failed"]
    assert [f["id"] for f in failed] == [task_id]
    return str(failed[0]["reason"])


def test_lights_out_refuses_to_dispatch_and_names_every_violation(
    world: Callable[..., World], fake_model: Callable[..., FakeModel]
) -> None:
    model = fake_model(script=_team_script())
    w = world(model)
    w.make_pod(UNGATED)
    head_before = w.head()
    w.docket("setup", "profile", "lights-out")
    task_id = w.add_task("Make app.txt say fixed")

    run = w.docket("run", "--pipeline", str(w.pipeline), "--timeout", "30", check=False)

    reason = _failure_reason(w, task_id)
    assert run.code == 1 and w.task(task_id)["task"]["status"] == "failed"
    assert reason.startswith("lights-out profile not met")
    for requirement in FIXES:
        assert f"{requirement}:" in reason
    assert "docket setup sandbox on" in reason and "docket setup sandbox network none" in reason
    assert "implementer step 'implement' has no external gate" in reason
    refused = [r for r in oracles.audit_rows(w) if r["action"] == "profile.refused"]
    assert [r["detail"].split("requirements=")[1] for r in refused] == [",".join(FIXES)]
    assert model.requests == []
    assert oracles.trace_skeleton(w, w.pod, task_id) == [
        ("dispatch_refused", "lead", reason),
        ("session_end", "lead", "failed"),
    ]
    oracles.assert_checkout_untouched(w, head_before)
    oracles.assert_transitions_legal(["pending", "failed"])
    oracles.assert_log_verifies(w)


@pytest.mark.skipif(NO_JAIL, reason="no jail backend (Landlock or Seatbelt) on this host")
def test_lights_out_runs_once_its_violations_are_fixed(
    world: Callable[..., World], fake_model: Callable[..., FakeModel]
) -> None:
    model = fake_model(script=_team_script())
    w = world(model)
    w.make_pod(UNGATED)
    head_before = w.head()
    w.docket("setup", "profile", "lights-out")
    task_id = w.add_task("Make app.txt say fixed")
    w.docket("run", "--pipeline", str(w.pipeline), "--timeout", "30", check=False)
    refusal = _failure_reason(w, task_id)
    assert refusal.startswith("lights-out profile not met")

    w.docket("setup", "sandbox", "on")
    w.docket("setup", "sandbox", "network", "none")
    w.pipeline.write_text(GATED, encoding="utf-8")
    w.docket("task", "retry", task_id, "--pod", w.pod)
    w.docket("run", "--pipeline", str(w.pipeline), "--timeout", "30")

    assert w.task(task_id)["task"]["status"] == "done"
    assert "+fixed" in w.docket("task", "diff", task_id).out
    assert oracles.trace_skeleton(w, w.pod, task_id) == [
        ("dispatch_refused", "lead", refusal),
        ("session_end", "lead", "failed"),
        ("hop_started", "lead", "plan"),
        ("hop_finished", "lead", "ok"),
        ("hop_started", "implementer", "implement"),
        ("hop_finished", "implementer", "ok"),
        ("verification", "implementer", "passed"),
        ("session_end", "lead", "done"),
    ]
    oracles.assert_checkout_untouched(w, head_before)
    oracles.assert_sentinel_untouched(w)
    oracles.assert_audit_covers_tool_calls(w, w.pod, task_id)
    oracles.assert_transitions_legal(["pending", "failed", "pending", "done"])
    oracles.assert_log_verifies(w)


def test_a_task_over_its_token_budget_fails_as_budget(
    world: Callable[..., World], fake_model: Callable[..., FakeModel]
) -> None:
    script = _team_script()
    script["lead"] = [say("Plan: make app.txt say fixed. " + "word " * 6000)]
    model = fake_model(script=script)
    w = world(model)
    w.make_pod(UNGATED)
    head_before = w.head()
    task_id = w.add_task("Make app.txt say fixed", "--max-tokens", str(OVER_BUDGET))

    run = w.docket("run", "--pipeline", str(w.pipeline), "--timeout", "30", check=False)

    reason = _failure_reason(w, task_id)
    assert run.code == 1 and w.task(task_id)["task"]["status"] == "failed"
    assert reason == f"task token budget reached (maxTokens={OVER_BUDGET}) before implementer"
    used = w.task(task_id)["evidence"]["hops"][0]["usage"]
    assert used["input"] + used["output"] > OVER_BUDGET
    assert len(model.by_role("lead")) == 1 and model.by_role("implementer") == []
    assert oracles.trace_skeleton(w, w.pod, task_id) == [
        ("hop_started", "lead", "plan"),
        ("hop_finished", "lead", "ok"),
        ("session_end", "lead", "failed"),
    ]
    oracles.assert_checkout_untouched(w, head_before)
    oracles.assert_audit_covers_tool_calls(w, w.pod, task_id)
    oracles.assert_transitions_legal(["pending", "failed"])
    oracles.assert_log_verifies(w)
