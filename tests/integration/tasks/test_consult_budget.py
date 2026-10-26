"""A task's consultations are counted whoever answers them and wherever they wait.

Every `consult` escalation listed on a task spends one of its `maxConsultationsPerTask`: a parked
one, one a person answers in the turn, and one the pod decides alone. The next hop of the task is
told what is left. Real pods, tasks and escalation records.
"""

from __future__ import annotations

import types
from typing import Any

import pytest
from tests.support import escalations as _support_escalations
from tests.support.escalations import consult_escalation, input_escalation
from tests.support.tasks import stored_task

from docket.agent import ports as _rd
from docket.hops.gates import pre_hop as _pre_hop
from docket.kernel.operator_contract import QuestionV11
from docket.tasks.application import escalations as _esc
from docket.tasks.application import queue as _queue

SUBJECT = "docket.tasks.application.escalations"

PROJECT = "demo"

demo_pod = _support_escalations.demo_pod
pytestmark = pytest.mark.usefixtures("demo_pod")


def _question(task_id: str, qid: str) -> QuestionV11:
    return QuestionV11.model_validate(
        {
            "id": qid,
            "taskId": task_id,
            "pod": PROJECT,
            "step": "implementer",
            "message": "Which store?",
            "requestedSchema": {"type": "object", "properties": {"note": {"type": "string"}}},
            "createdAt": "2026-10-25T10:00:00Z",
            "kind": "decision",
            "options": [
                {"id": "redis", "label": "Redis", "description": "fast"},
                {"id": "sqlite", "label": "SQLite", "description": "simple"},
            ],
            "recommendation": {"optionId": "sqlite", "rationale": "no new service"},
        }
    )


def _hop_env(task_id: str) -> dict[str, str] | None:
    ctx: Any = types.SimpleNamespace(task=stored_task(PROJECT, task_id), project=PROJECT)
    return _pre_hop._consult_budget_env(ctx, None)


def test_a_parked_consult_spends_one() -> None:
    escalation = consult_escalation()

    assert stored_task(PROJECT, escalation.task).consultations == 1


def test_a_consult_the_pod_decides_alone_spends_one_too() -> None:
    task = _queue.enqueue_task_once(PROJECT, "pick a store", channel="cli")[0]

    _esc.decided_consult(
        _question(task.id, "q-decided0001"), role="implementer", option_id="sqlite"
    )

    assert stored_task(PROJECT, task.id).consultations == 1


def test_a_consult_a_person_answers_in_the_turn_spends_one_too() -> None:
    task = _queue.enqueue_task_once(PROJECT, "pick a store", channel="cli")[0]

    _esc.open_for_question(
        _question(task.id, "q-inturn00001"), kind="consult", role="implementer", caused_by="c1"
    )

    assert stored_task(PROJECT, task.id).consultations == 1


def test_an_input_step_is_not_a_consultation() -> None:
    escalation = input_escalation()

    assert stored_task(PROJECT, escalation.task).consultations == 0


def test_the_next_hop_is_told_what_the_whole_task_has_left() -> None:
    task = _queue.enqueue_task_once(PROJECT, "pick a store", channel="cli")[0]
    assert _hop_env(task.id) is None
    for n in range(2):
        _esc.decided_consult(
            _question(task.id, f"q-decided000{n}"), role="implementer", option_id="sqlite"
        )

    env = _hop_env(task.id)

    assert env == {_rd.DOCKET_MAX_CONSULTATIONS: "1"}
