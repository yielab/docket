"""The ``consult`` built-in: a model asks its operator a question with options.

The call is validated through ``QuestionV11`` (operator-v1.1) and then, by approval mode:
``wait`` has nobody to ask and answers "no answer; decide yourself"; ``refuse``/``park`` trace
the event and raise ``ConsultUnavailable``, which ``agent/tools/registry.py`` renders as the
``approval_unavailable`` stop. In pod dispatch (``ctx.consult_park``) the pod setting
``consultMode`` picks the rest: ``decide`` applies the model's own recommendation in the turn
(traced ``escalation_decided``, audited); under ``wait`` the call blocks
on an approval record beside its escalation until a person resolves it (``waits_in_turn``);
otherwise a non-refuse consult raises ``ConsultParked`` and the task parks ``waiting_input``.
Tool-visible failures are ordinary error results, never exceptions, so the model can adapt.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from docket.governance import approval as _approval
from docket.governance import audit as _audit
from docket.governance import gate as _gate
from docket.governance.secrets import redact as _redact
from docket.kernel import clock as _clock
from docket.kernel.errors import InvalidInput, Refused
from docket.kernel.gate import HandlerParked, HandlerUnavailable
from docket.kernel.operator_contract import (
    AnswerResultV11,
    Escalation,
    Option,
    QuestionV11,
    new_question_id,
)
from docket.platform import PARK_TOKEN_PREFIX, is_question_id, read_escalation, write_parked
from docket.tasks.application import escalations as _escalations

if TYPE_CHECKING:
    from docket.agent.tools.registry import ToolContext

NO_ANSWER = "no answer; decide yourself"
BUDGET_EXHAUSTED = "consultation budget exhausted; decide yourself"
DECIDED = "no operator on duty; your recommendation stands: option {id} ({label}). Continue."
DECIDED_AUDIT = "consult.decided"

# What an answer may carry besides ``optionId``: one free-text note.
_REQUESTED_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"note": {"type": "string"}},
    "required": [],
}


@dataclass
class ConsultOutcome:
    """What a consult call produced; ``agent/tools/registry.py`` wraps it as its ``ConsultOutcome``."""

    ok: bool
    content: str = ""
    error: str = ""


class ConsultUnavailable(Refused, HandlerUnavailable):
    """Nobody can answer this consultation (``refuse``/``park``); the turn ends blocked."""


def park_token(question: QuestionV11) -> str:
    """Persist the parked question (``platform/store.py``, 0600) and return ``consult:<id>``. The
    token never carries question text, so no error string or trace field holds it unredacted."""
    if not is_question_id(question.id):
        raise ConsultUnavailable(f"cannot park question id {question.id!r}")
    write_parked(question)
    return PARK_TOKEN_PREFIX + question.id


class ConsultParked(ConsultUnavailable, HandlerParked):
    """Pod dispatch parks this consultation's task; ``token`` names the persisted question."""

    def __init__(self, question: QuestionV11) -> None:
        self.question = question
        self.token = park_token(question)
        super().__init__("consultation parked for an operator answer")


def answer_text(
    question_id: str,
    options: Iterable[Option],
    answer: AnswerResultV11,
    content: dict[str, Any] | None,
) -> str:
    """What the resumed role reads: the operator's answer to its parked consultation."""
    head = f"Operator answered your consultation {question_id}:"
    if answer.action != "accept":
        return f"{head} declined. Decide yourself."
    label = next((o.label for o in options if o.id == answer.option_id), "")
    note = " ".join(str(v) for v in (content or {}).values())
    return f"{head} option {answer.option_id} ({label}) {note}".rstrip()


def build_question(args: dict[str, Any], ctx: ToolContext) -> QuestionV11:
    """The ``QuestionV11`` for a consult call's *args*. Raises ``ValueError`` naming the
    problem; a consultation always carries at least two options and a recommendation."""
    options = args.get("options")
    if not isinstance(options, list) or len(options) < 2:
        raise InvalidInput("options must list at least two options")
    if not isinstance(args.get("recommendation"), dict):
        raise InvalidInput("a consultation must carry a recommendation {optionId, rationale}")
    kind = args.get("kind")
    if kind not in ("clarification", "decision"):
        raise InvalidInput("kind must be 'clarification' or 'decision'")
    return QuestionV11.model_validate(
        {
            "id": new_question_id(),
            "taskId": ctx.task_id or ctx.session_key or ctx.agent_id,
            "pod": ctx.project,
            "step": ctx.role or "consult",
            "message": args.get("message"),
            "requestedSchema": _REQUESTED_SCHEMA,
            "createdAt": _clock.stamp(),
            "kind": kind,
            "options": options,
            "recommendation": args.get("recommendation"),
        }
    )


# Polls (of 50 ms) a wait for the resolved record that follows the grant waking it: `resolve`
# grants the approval first and writes the record straight after.
_SETTLE_POLLS = 40
_WAIT_ENDED_WITHOUT_ANSWER = ("approval_timeout", "run_cancelled")


def waits_in_turn(ctx: ToolContext) -> bool:
    """Whether a consult here blocks for a person at the terminal: a dispatch hop under
    ``approvalMode`` ``wait`` whose pod does not decide alone."""
    return ctx.consult_park and ctx.approval_mode == "wait" and not ctx.consult_decides


def _settled(escalation_id: str) -> Escalation | None:
    """The record *escalation_id* once it leaves ``pending``, else the last read of it."""
    record = read_escalation(escalation_id)
    for _ in range(_SETTLE_POLLS):
        if record is None or record.state != "pending":
            break
        _approval.pause(0.05)
        record = read_escalation(escalation_id)
    return record


def _wait_for_person(question: QuestionV11, ctx: ToolContext) -> ConsultOutcome:
    """Block on an approval record opened beside the question's escalation (the way a gated call
    waits) and return what the person answered; a timeout or a cancellation is ``NO_ANSWER``."""
    token = _approval.approval_create(
        ctx.project or "operator",
        ctx.role or "consult",
        question.message,
        context={
            "kind": "consult",
            "questionId": question.id,
            "task": ctx.task_id,
            "options": [{"id": o.id, "label": _redact(o.label)} for o in question.options],
        },
    )
    escalation = _escalations.open_for_question(
        question, kind="consult", role=ctx.role, caused_by=question.step, token=token
    )
    decision = _gate.wait_for_answer(token, ctx)
    if decision.denial_kind in _WAIT_ENDED_WITHOUT_ANSWER:
        return ConsultOutcome(True, content=NO_ANSWER)
    settled = _settled(escalation.id)
    resolution = settled.resolution if settled is not None else None
    if resolution is None:
        return ConsultOutcome(True, content=NO_ANSWER)
    declined = resolution.option_id == "decline"
    answer = AnswerResultV11(
        action="decline" if declined else "accept",
        content=resolution.content,
        option_id=None if declined else resolution.option_id,
    )
    return ConsultOutcome(
        True, content=answer_text(escalation.id, question.options, answer, resolution.content)
    )


def _decide(question: QuestionV11, ctx: ToolContext) -> ConsultOutcome:
    """Apply the model's own recommendation: trace and audit it, return it as the tool result.
    The audit row names the ids, never the question text or the options."""
    recommendation = question.recommendation
    if recommendation is None:
        return ConsultOutcome(False, error="invalid consultation: no recommendation to apply")
    option_id = recommendation.option_id
    label = next((o.label for o in question.options if o.id == option_id), option_id)
    decided = _escalations.decided_consult(
        question,
        role=ctx.role,
        option_id=option_id,
        session_id=ctx.trace_session_key or ctx.session_key,
    )
    _audit.audit_log(
        DECIDED_AUDIT,
        f"project={ctx.project} task={ctx.task_id} role={ctx.role} "
        f"escalation={decided.id} optionId={option_id}",
    )
    return ConsultOutcome(True, content=DECIDED.format(id=option_id, label=label))


def run(args: dict[str, Any], ctx: ToolContext) -> ConsultOutcome:
    """Handler for the ``consult`` built-in."""
    if ctx.consult_count >= ctx.max_consultations:
        return ConsultOutcome(False, error=BUDGET_EXHAUSTED)
    try:
        question = build_question(args, ctx)
    except ValueError as exc:
        return ConsultOutcome(False, error=f"invalid consultation: {exc}")
    ctx.consult_count += 1
    if ctx.consult_decides:
        return _decide(question, ctx)
    if waits_in_turn(ctx):
        return _wait_for_person(question, ctx)
    if ctx.consult_park and ctx.approval_mode != "refuse":
        raise ConsultParked(question)
    if ctx.approval_mode != "wait":
        raise ConsultUnavailable("a consultation needs an operator answer and none can be given")
    return ConsultOutcome(True, content=NO_ANSWER)
