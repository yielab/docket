"""A docket task and its pending escalation as the A2A objects a client reads.

The state is ``a2a_state`` of the task record and the question is the ``EscalationView``; nothing
here is stored. An approval token is not a field of either, so it cannot reach an A2A object."""

from __future__ import annotations

from typing import Any

from docket.kernel.operator_contract import EscalationView, TaskView
from docket.operator import escalation_views, task_view
from docket.tasks.application import queue as _queue
from docket.tasks.application.repository import TaskRepository
from docket.tasks.domain.task import TaskRecord

# The operator-v1.1 extension is declared by the `$id` of its question schema; the data part
# reuses that schema's field names.
EXTENSION_URI = "https://docket.dev/schemas/operator-v1.1/question.schema.json"

_APPROVAL_KINDS = frozenset({"approval", "gate", "check_changed"})
_DECLINE = "decline"
# A task keeps the reason of its last pause after it moves on; only these states are that reason.
_EXPLAINED = frozenset({"blocked", "failed", "cancelled"})


def question_kind(view: EscalationView) -> str:
    """The operator-v1.1 question kind of *view*."""
    if view.kind in _APPROVAL_KINDS:
        return "approval"
    return "decision" if any(o.id != _DECLINE for o in view.options) else "clarification"


def requested_schema(view: EscalationView) -> dict[str, Any]:
    """The MCP elicitation schema of *view*'s answer: its own properties, the option to choose
    (``decline`` is the action of the answer, not an option) and an approval's reason."""
    own = view.requested_schema or {}
    properties: dict[str, Any] = dict(own.get("properties") or {})
    required: list[str] = list(own.get("required") or [])
    choices = [o.id for o in view.options if o.id != _DECLINE]
    if choices:
        properties["optionId"] = {"type": "string", "enum": choices}
        if "optionId" not in required:
            required.append("optionId")
    if view.kind in _APPROVAL_KINDS:
        properties["reason"] = {"type": "string"}
    return {"type": "object", "properties": properties, "required": required}


def escalation_data(view: EscalationView) -> dict[str, Any]:
    """The data part of an escalation message: the MCP elicitation request and the
    operator-v1.1 fields."""
    data: dict[str, Any] = {
        "message": view.prompt,
        "requestedSchema": requested_schema(view),
        "kind": question_kind(view),
        "options": [o.model_dump(by_alias=True, mode="json") for o in view.options],
        "escalationId": view.id,
        "escalationKind": view.kind,
        "expiresAt": view.expires_at,
        "onExpiry": view.on_expiry,
        "policy": view.policy,
    }
    if view.recommendation is not None:
        data["recommendation"] = view.recommendation.model_dump(by_alias=True, mode="json")
    return data


def _message(message_id: str, pod: str, task: str, parts: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "kind": "message",
        "role": "agent",
        "messageId": message_id,
        "taskId": task,
        "contextId": pod,
        "parts": parts,
    }


def escalation_message(view: EscalationView) -> dict[str, Any]:
    """The status message of a task parked on *view*: its prompt and the elicitation data."""
    parts: list[dict[str, Any]] = [
        {"kind": "text", "text": view.prompt},
        {"kind": "data", "data": escalation_data(view)},
    ]
    return {**_message(view.id, view.pod, view.task, parts), "extensions": [EXTENSION_URI]}


def task_object(
    view: TaskView, pending: EscalationView | None, *, external_ref: str | None = None
) -> dict[str, Any]:
    """The A2A ``Task`` of *view*; *pending* is the escalation it waits on, when it has one."""
    status: dict[str, Any] = {"state": view.a2a_state, "timestamp": view.updated_at}
    if pending is not None:
        status["message"] = escalation_message(pending)
    elif view.reason and view.status in _EXPLAINED:
        text = {"kind": "text", "text": view.reason}
        status["message"] = _message(f"{view.id}-status", view.pod, view.id, [text])
    docket: dict[str, Any] = {"pod": view.pod, "status": view.status}
    if external_ref:
        docket["externalRef"] = external_ref
    return {
        "kind": "task",
        "id": view.id,
        "contextId": view.pod,
        "status": status,
        "metadata": {"docket": docket},
    }


def find_task(task_id: str) -> tuple[str, TaskRecord] | None:
    """The pod and record of *task_id*, looked up in every provisioned pod."""
    for pod in _queue.dispatchable_pods():
        record = TaskRepository.for_pod(pod).get(task_id)
        if record is not None:
            return pod, record
    return None


def pending_escalations(pod: str, task_id: str) -> list[EscalationView]:
    """The escalations *task_id* still waits on, oldest first."""
    return [v for v in escalation_views(pod=pod, task=task_id) if v.state == "pending"]


def task_result(pod: str, record: TaskRecord) -> dict[str, Any]:
    """The A2A ``Task`` of *record* as it reads now, with the escalation it waits on."""
    view = task_view(pod, record.model_dump(by_alias=True, mode="json"))
    pending = None
    if view.a2a_state == "INPUT_REQUIRED":
        waiting = pending_escalations(pod, record.id)
        pending = waiting[-1] if waiting else None
    return task_object(view, pending, external_ref=record.external_ref)
