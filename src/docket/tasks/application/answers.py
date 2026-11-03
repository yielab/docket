"""What a person told a task, read from the escalations it lists.

A task keeps no copy of an answer. ``answers_of`` is every resolved question as the entry a hop's
prompt renders; ``consult_note`` is the answer to a parked consultation, or the reply to a
conversation's ``turn``, the re-run hop of its step ends its message with, until a hop of that step
has been persisted (``consult_note_delivered`` stamps the record ``applied_at``). Every function
takes the task record and reads the store.
"""

from __future__ import annotations

from docket.kernel.operator_contract import AnswerResultV11, Escalation
from docket.platform import mark_escalation_applied, read_escalation
from docket.tasks.application import consult as _consult
from docket.tasks.domain.parts import Answer
from docket.tasks.domain.task import TaskRecord

__all__ = ["answers_of", "consult_note", "consult_note_delivered"]

_DECLINE = "decline"
_NOTED_KINDS = ("consult", "turn")
_REPLY = "reply"


def _listed(task: TaskRecord) -> list[Escalation]:
    found = (read_escalation(escalation_id) for escalation_id in task.escalations)
    return [e for e in found if e is not None]


def answers_of(task: TaskRecord) -> list[Answer]:
    """The answers given to *task*'s ``consult`` and ``input`` escalations, oldest first."""
    answers: list[Answer] = []
    for e in _listed(task):
        resolution = e.resolution
        if e.kind not in ("consult", "input") or e.state != "resolved" or resolution is None:
            continue
        declined = resolution.option_id == _DECLINE
        answers.append(
            Answer(
                question_id=e.id,
                step=e.step,
                message=e.prompt,
                action="decline" if declined else "accept",
                content=resolution.content,
                channel=resolution.channel,
                actor=resolution.by,
                answered_at=resolution.at,
                kind="decision" if e.recommendation is not None else "clarification",
                created_at=e.asked_at,
                option_id=None if declined else resolution.option_id,
            )
        )
    return answers


def _undelivered(task: TaskRecord, step_id: str) -> list[Escalation]:
    return [
        e
        for e in _listed(task)
        if e.kind in _NOTED_KINDS
        and e.state == "resolved"
        and e.step == step_id
        and e.resolution is not None
        and e.resolution.applied_at is None
    ]


def _answer_line(e: Escalation) -> str:
    """The text of the operator's answer to the resolved ``consult`` *e*."""
    resolution = e.resolution
    assert resolution is not None
    declined = resolution.option_id == _DECLINE
    answer = AnswerResultV11(
        action="decline" if declined else "accept",
        content=resolution.content,
        option_id=None if declined else resolution.option_id,
    )
    return _consult.answer_text(e.id, e.options, answer, resolution.content, e.part)


def _call_still_waits(task: TaskRecord, step_id: str) -> bool:
    """Whether a question of a ``consult`` call at *step_id* is still pending: its answers are
    heard together, so none is heard before the last."""
    return any(
        e.kind == "consult" and e.state == "pending" and e.step == step_id for e in _listed(task)
    )


def consult_note(task: TaskRecord, step_id: str) -> str:
    """The operator's answers to *step_id*'s parked consultation (one per question, in question
    order), or the reply to its conversation's last turn, as a trailing message block (empty when
    the step has none waiting to be heard, or while a question of the call is still pending)."""
    waiting = _undelivered(task, step_id)
    if not waiting:
        return ""
    e = waiting[-1]
    resolution = e.resolution
    assert resolution is not None
    if e.kind == "turn":
        text = str((resolution.content or {}).get("text", ""))
        return f"\n\nThe operator replied:\n{text}\n" if resolution.option_id == _REPLY else ""
    if _call_still_waits(task, step_id):
        return ""
    consults = sorted(
        (w for w in waiting if w.kind == "consult"), key=lambda w: w.part.index if w.part else 0
    )
    return "\n\n" + "\n".join(_answer_line(w) for w in consults) + "\n"


def consult_note_delivered(task: TaskRecord, step_id: str, at: str) -> None:
    """A hop of *step_id* was persisted: the answers it was given are heard, so a later hop of the
    step (a rework) is not told them again."""
    for e in _undelivered(task, step_id):
        mark_escalation_applied(e.id, at)
