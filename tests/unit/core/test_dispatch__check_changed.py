"""The pieces of the changed-check park: commands that count as checks, results, group failures."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from docket.core import dispatch as _dispatch
from docket.core import orchestrator as _orch
from docket.core import pipeline as _pipeline

SUBJECT = "docket.core.dispatch"


def _unit(step_id: str, **extra: Any) -> _orch.PlannedUnit:
    fields: dict[str, Any] = {
        "step_id": step_id,
        "role": "implementer",
        "agent": None,
        "archetype": None,
        "member_id": "demo-implementer",
        "gate": None,
        "retries": None,
        "timeout": None,
    }
    return _orch.PlannedUnit(**{**fields, **extra})


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("short", "short"),
        ("x" * 72, "x" * 72),
        ("word " * 20, ("word " * 14).rstrip()),
        ("a" * 80, "a" * 72),
        (("b" * 71) + " tail words", "b" * 71),
        (("c" * 60) + " " + ("d" * 40), "c" * 60),
    ],
)
def test_a_commit_subject_is_cut_at_a_word_boundary(text: str, expected: str) -> None:
    assert _dispatch._cut_at_word(text, 72) == expected


def test_every_command_a_task_runs_as_a_check_is_collected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_dispatch, "pod_full_roster", lambda project: {"implementer": "i"})
    monkeypatch.setattr(_dispatch._fleet, "meta_get", lambda *a, **k: "make verify")
    steps = (
        _unit("build", gate=_pipeline.MechanicalGate(command="bash scripts/check.sh")),
        _orch.PlannedGroup(
            step_id="par",
            children=(
                _unit("a", gate=_pipeline.ExternalGate(command="./verify.sh")),
                _unit("b", run="node lint.js"),
                _unit("c", gate=_pipeline.VerdictGate(pattern="x", passValues=["x"])),
            ),
        ),
    )
    task = {"gate": {"command": "python gate.py"}}

    assert _dispatch._checked_commands("demo", task, steps) == [
        "make verify",
        "bash scripts/check.sh",
        "./verify.sh",
        "node lint.js",
        "python gate.py",
    ]


def test_a_stale_check_changed_is_cleared_by_a_result_that_does_not_set_it() -> None:
    task: dict[str, Any] = {"id": "t", "checkChanged": ["package.json"]}
    _dispatch._apply_result(task, _dispatch.TaskResult(task_id="t", status="done"))
    assert "checkChanged" not in task
    parked = _dispatch.TaskResult(
        task_id="t", status="waiting_approval", approval_token="apr-1", check_changed=["a"]
    )
    _dispatch._apply_result(task, parked)
    assert task["checkChanged"] == ["a"] and task["approvalToken"] == "apr-1"


def test_a_group_keeps_the_failure_kind_of_the_child_that_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake(ctx: Any, child: Any, **_k: Any) -> _dispatch._UnitOutcome:
        if child.step_id == "b":
            return _dispatch._UnitOutcome(kind="failed", reason="spent", failure_kind="budget")
        return _dispatch._UnitOutcome(kind="advance")

    monkeypatch.setattr(_dispatch, "_execute_unit", fake)
    group = _orch.PlannedGroup(step_id="par", children=(_unit("a"), _unit("b")))

    outcome = _dispatch._run_group_node(SimpleNamespace(), group, [], 0)

    assert (outcome.kind, outcome.reason, outcome.failure_kind) == ("failed", "spent", "budget")
