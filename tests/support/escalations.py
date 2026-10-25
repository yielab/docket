"""Paused tasks with their escalation, for tests of the surfaces that settle one.

The pause is seeded by the same openers the sites call, over a real pod, real tasks and real
approval records, so what a surface settles is what a run would have left.
"""

from __future__ import annotations

from typing import Any

import pytest

from docket.governance import approval as _ap
from docket.interfaces.cli.commands import pod as _pod
from docket.kernel.operator_contract import Escalation, EscalationKind, QuestionV11
from docket.platform import list_escalations
from docket.tasks.application import escalations as _esc
from docket.tasks.application import queue as _queue
from tests.support.pods import build_pod, seed_parked_task
from tests.support.tasks import update_task

PROJECT = "demo"
DIGEST = "d" * 16


@pytest.fixture()
def demo_pod() -> None:
    """The pod `demo` with a Lead and an Implementer, for a test that seeds a pause in it."""
    build_pod(PROJECT, _pod.pod.DEFAULT_POD_ROLES, codebase=f"/src/{PROJECT}")


def approval_escalation(kind: EscalationKind = "gate", **context: Any) -> Escalation:
    """A task parked on an approval of *kind* (`approval`, `gate` or `check_changed`)."""
    task = _queue.enqueue_task_once(PROJECT, "tidy the build", channel="cli")[0]
    ctx: dict[str, Any] = {"taskId": task.id, **context}
    if kind == "check_changed":
        ctx["kind"] = "check_changed"
    token = _ap.approval_create(
        PROJECT, "implementer", "tool call 'bash': rm -rf build", context=ctx
    )
    update_task(
        PROJECT, task.id, status="waiting_approval", approval_token=token, pending_approval_index=1
    )
    return _esc.open_for_approval(
        token,
        kind=kind,
        task_id=task.id,
        caused_by="" if kind == "check_changed" else "call-1",
    )


def parked_approval() -> Escalation:
    """A task parked on one in-turn `bash` call, as the tool gate parks it."""
    return approval_escalation(
        "approval", parked=True, tool="bash", argsDigest=DIGEST, project=PROJECT, role="implementer"
    )


def consult_escalation() -> Escalation:
    """A task parked on a consult offering `redis` and `sqlite`."""
    task = _queue.enqueue_task_once(PROJECT, "pick a store", channel="cli")[0]
    question = QuestionV11.model_validate(
        {
            "id": "q-1",
            "taskId": task.id,
            "pod": PROJECT,
            "step": "implementer",
            "message": "Which store should the cache use?",
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
    update_task(PROJECT, task.id, status="waiting_input", question=question)
    return _esc.open_for_question(
        question, kind="consult", role="implementer", caused_by="implementer"
    )


def input_escalation() -> Escalation:
    """A task parked on an `input` step of its pipeline, by a real dispatch."""
    seed_parked_task(PROJECT)
    (record,) = list_escalations()
    assert record.kind == "input"
    return record
