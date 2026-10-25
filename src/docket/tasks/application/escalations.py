"""Open the escalation record for a pause: the one place a pause becomes a durable record.

Every way a task stops for a person calls an opener here, at the moment the pause is created. The
record is written by the store and its id is appended to the task; the older fields the task
carries (``approvalToken``, ``question``) are still written by the lifecycle from the same values
and equal what ``legacy`` names, so no surface that reads them notices. Opening also writes
``escalation_asked`` (``kernel/escalation_events.py``), the start of the wait a span measures.

``governance`` sits below this context, so the tool gate reaches ``approval_opened`` through its
port (``governance.ports``), bound once per entry.
"""

from __future__ import annotations

import datetime as _dt

from docket.governance import approval as _approval
from docket.governance.secrets import redact as _redact
from docket.kernel import clock as _clock
from docket.kernel import escalation_events as _events
from docket.kernel.operator_contract import (
    Escalation,
    EscalationExpiry,
    EscalationKind,
    Option,
    Question,
    QuestionV11,
    Resolution,
    new_escalation_id,
)
from docket.platform import write_escalation
from docket.tasks.application.repository import TaskRepository
from docket.tasks.domain.task import TaskRecord
from docket.teams.settings import load_pod_settings

__all__ = ["approval_opened", "attach", "decided_consult", "open_for_approval", "open_for_question"]

_DECLINE = Option(id="decline", label="Decline", description="Refuse without choosing an option.")
_APPROVE_ONCE = "approve_once"
_DENY = "deny"

# A pause that nobody answers is denied when a call or a hop awaited it, and blocks the task when
# a question did (the two expiry sweeps).
_EXPIRY: dict[EscalationKind, EscalationExpiry] = {
    "approval": "deny",
    "gate": "deny",
    "check_changed": "deny",
    "consult": "block",
    "input": "block",
}


def attach(task: TaskRecord, escalation: Escalation) -> bool:
    """Append *escalation*'s id to *task*; ``False`` when it is already listed."""
    if escalation.id in task.escalations:
        return False
    task.escalations.append(escalation.id)
    return True


def _store(escalation: Escalation) -> Escalation:
    """Write *escalation* and list it on its task when the pod's queue holds that task."""
    stored = write_escalation(escalation)
    if stored.task:
        repository = TaskRepository.for_pod(stored.pod)
        if repository.get(stored.task) is not None:
            repository.update(stored.task, lambda record: attach(record, stored))
    _events.emit(_events.ASKED, stored)
    return stored


def _approval_options(kind: EscalationKind) -> list[Option]:
    options = [Option.model_validate(o) for o in _approval.approval_options()]
    if kind == "approval":
        return options
    return [o for o in options if o.id in (_APPROVE_ONCE, _DENY)]


def open_for_approval(
    token: str,
    *,
    kind: EscalationKind,
    task_id: str,
    caused_by: str,
    step: str = "",
) -> Escalation:
    """Open the escalation of the approval record *token* (``approval``, ``gate`` or
    ``check_changed``). The prompt, role, pod and deadline are the record's own."""
    record = _approval.approval_get(token)
    return _store(
        Escalation(
            id=new_escalation_id(),
            task=task_id,
            pod=str(record.get("project", "")),
            step=step,
            role=str(record.get("role", "")),
            kind=kind,
            caused_by=caused_by,
            prompt=_redact(str(record.get("action", ""))),
            options=_approval_options(kind),
            asked_at=_clock.iso(),
            expires_at=record.get("expiresAt"),
            on_expiry=_EXPIRY[kind],
            legacy={"token": token},
        )
    )


def approval_opened(token: str, *, task_id: str, caused_by: str) -> None:
    """The tool gate created approval *token* for a call: open its ``approval`` escalation."""
    open_for_approval(token, kind="approval", task_id=task_id, caused_by=caused_by)


def _question_expiry(question: Question) -> str | None:
    """The deadline the lifecycle will stamp on a question that has none: the pod's input expiry."""
    if question.expires_at:
        return question.expires_at
    hours = load_pod_settings(question.pod).input_expiry_hours
    return (_clock.now() + _dt.timedelta(hours=hours)).isoformat()


def open_for_question(
    question: Question,
    *,
    kind: EscalationKind,
    role: str,
    caused_by: str,
) -> Escalation:
    """Open the escalation of a parked question (``consult`` or ``input``). A consult offers the
    question's own options then ``decline``; an input step offers ``decline`` and the schema."""
    v11 = question if isinstance(question, QuestionV11) else None
    return _store(
        Escalation(
            id=new_escalation_id(),
            task=question.task_id,
            pod=question.pod,
            step=question.step,
            role=role,
            kind=kind,
            caused_by=caused_by,
            prompt=_redact(question.message),
            options=[*(v11.options if v11 else []), _DECLINE],
            recommendation=v11.recommendation if v11 else None,
            requested_schema=dict(question.requested_schema),
            asked_at=_clock.iso(),
            expires_at=_question_expiry(question),
            on_expiry=_EXPIRY[kind],
            legacy={"questionId": question.id},
        )
    )


def decided_consult(
    question: QuestionV11, *, role: str, option_id: str, session_id: str = ""
) -> Escalation:
    """Trace that the pod applied the model's recommendation and return the escalation describing
    it. The pause never parks, so nothing is stored or listed on the task: only
    ``escalation_decided`` is written, under a fresh id."""
    decided = Escalation(
        id=new_escalation_id(),
        task=question.task_id,
        pod=question.pod,
        step=question.step,
        role=role,
        kind="consult",
        caused_by=question.step,
        prompt=_redact(question.message),
        options=list(question.options),
        recommendation=question.recommendation,
        asked_at=question.created_at,
        on_expiry=_EXPIRY["consult"],
        policy="recommendation",
        state="decided",
        resolution=Resolution(option_id=option_id, by="policy", channel="policy", at=_clock.iso()),
        legacy={"questionId": question.id},
    )
    _events.emit(_events.DECIDED, decided, option_id=option_id, session_id=session_id)
    return decided
