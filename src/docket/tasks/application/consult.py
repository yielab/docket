"""The ``consult`` built-in: a model asks its operator one to five questions, each with options.

Each question is validated through ``QuestionV11`` (operator-v1.1) and opens its own escalation,
numbered by ``part``. The call is then handled by approval mode: ``wait`` has nobody to ask and
answers "no answer; decide yourself"; ``refuse``/``park`` trace the event and raise
``ConsultUnavailable``, which ``agent/tools/registry.py`` renders as the ``approval_unavailable``
stop. In pod dispatch (``ctx.consult_park``) the pod setting ``consultMode`` picks the rest:
``decide`` applies each recommendation in the turn (traced ``escalation_decided``, audited);
under ``wait`` the call blocks on approval records beside the escalations until a person resolves
them (``waits_in_turn``); otherwise a non-refuse consult raises ``ConsultParked`` and the task
parks ``waiting_input`` until every question is answered. Tool-visible failures are results.
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
    QuestionPart,
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
MAX_QUESTIONS = 5

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


def part_label(part: QuestionPart | None) -> str:
    """``question 2 of 3`` for a question of a call that asked several; empty for a lone one."""
    return f"question {part.index} of {part.count}" if part and part.count > 1 else ""


def answer_text(
    question_id: str,
    options: Iterable[Option],
    answer: AnswerResultV11,
    content: dict[str, Any] | None,
    part: QuestionPart | None = None,
) -> str:
    """What the resumed role reads: the operator's answer to its parked consultation."""
    label = part_label(part)
    head = f"Operator answered your consultation {question_id}{f' ({label})' if label else ''}:"
    if answer.action != "accept":
        return f"{head} declined. Decide yourself."
    label = next((o.label for o in options if o.id == answer.option_id), "")
    note = " ".join(str(v) for v in (content or {}).values())
    return f"{head} option {answer.option_id} ({label}) {note}".rstrip()


def _build_question(raw: Any, ctx: ToolContext, part: QuestionPart) -> QuestionV11:
    """The ``QuestionV11`` for one entry of ``questions``. Raises ``ValueError`` naming the problem;
    a consultation always carries at least two options and a recommendation."""
    if not isinstance(raw, dict):
        raise InvalidInput("a question must be an object")
    options = raw.get("options")
    if not isinstance(options, list) or len(options) < 2:
        raise InvalidInput("options must list at least two options")
    if not isinstance(raw.get("recommendation"), dict):
        raise InvalidInput("a consultation must carry a recommendation {optionId, rationale}")
    kind = raw.get("kind")
    if kind not in ("clarification", "decision"):
        raise InvalidInput("kind must be 'clarification' or 'decision'")
    return QuestionV11.model_validate(
        {
            "id": new_question_id(),
            "taskId": ctx.task_id or ctx.session_key or ctx.agent_id,
            "pod": ctx.project,
            "step": ctx.role or "consult",
            "message": raw.get("message"),
            "requestedSchema": _REQUESTED_SCHEMA,
            "createdAt": _clock.stamp(),
            "kind": kind,
            "options": options,
            "recommendation": raw.get("recommendation"),
            "part": part.model_dump(),
        }
    )


def build_questions(args: dict[str, Any], ctx: ToolContext) -> list[QuestionV11]:
    """The questions of a consult call's *args*, in order, each with its ``part``. Raises
    ``ValueError`` naming the problem (and the question, when the call asked several); one invalid
    question rejects the call."""
    raw = args.get("questions")
    if not isinstance(raw, list) or not 1 <= len(raw) <= MAX_QUESTIONS:
        raise InvalidInput(f"questions must list one to {MAX_QUESTIONS} questions")
    built: list[QuestionV11] = []
    for index, entry in enumerate(raw, 1):
        try:
            built.append(_build_question(entry, ctx, QuestionPart(index=index, count=len(raw))))
        except ValueError as exc:
            raise InvalidInput(f"question {index}: {exc}" if len(raw) > 1 else str(exc)) from exc
    return built


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


def _open_waiting(question: QuestionV11, ctx: ToolContext) -> Escalation:
    """Open *question*'s escalation with an approval record beside it, the way a gated call waits."""
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
    return _escalations.open_for_question(
        question, kind="consult", role=ctx.role, caused_by=question.step, token=token
    )


def _answer_of(escalation: Escalation, ctx: ToolContext) -> tuple[str, bool]:
    """Block on the approval record behind *escalation* and return what the person answered and
    whether the run was cancelled meanwhile; a timeout or a cancellation is ``NO_ANSWER``."""
    decision = _gate.wait_for_answer(_approval.approval_of(escalation.id), ctx)
    if decision.denial_kind in _WAIT_ENDED_WITHOUT_ANSWER:
        return NO_ANSWER, decision.denial_kind == "run_cancelled"
    settled = _settled(escalation.id)
    resolution = settled.resolution if settled is not None else None
    if resolution is None:
        return NO_ANSWER, False
    declined = resolution.option_id == "decline"
    answer = AnswerResultV11(
        action="decline" if declined else "accept",
        content=resolution.content,
        option_id=None if declined else resolution.option_id,
    )
    text = answer_text(
        escalation.id, escalation.options, answer, resolution.content, escalation.part
    )
    return text, False


def _wait_for_person(questions: list[QuestionV11], ctx: ToolContext) -> ConsultOutcome:
    """Open every question's escalation, then block for the person's answers in question order.
    A cancellation ends the wait: the questions after it are ``NO_ANSWER``."""
    opened = [_open_waiting(question, ctx) for question in questions]
    answers: list[str] = []
    cancelled = False
    for escalation in opened:
        if cancelled:
            answers.append(NO_ANSWER)
            continue
        text, cancelled = _answer_of(escalation, ctx)
        answers.append(text)
    return ConsultOutcome(True, content=_joined(answers))


def _joined(lines: list[str]) -> str:
    """One line per question, in question order; a lone question is its line."""
    return lines[0] if len(lines) == 1 else "\n".join(lines)


def _decide(question: QuestionV11, ctx: ToolContext) -> str:
    """Apply the model's own recommendation: trace and audit it, return the line the tool result
    carries. The audit row names the ids, never the question text or the options."""
    recommendation = question.recommendation
    assert recommendation is not None  # _build_question refuses a question without one
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
    return DECIDED.format(id=option_id, label=label)


def _park(questions: list[QuestionV11], ctx: ToolContext) -> ConsultParked:
    """Open the escalations of every question but the last and return the parking stop for the
    last: the hop opens that one when it parks the task, so the call's escalations are listed on
    the task in question order."""
    for question in questions[:-1]:
        question.step = ctx.step_id or question.step
        _escalations.open_for_question(
            question, kind="consult", role=ctx.role, caused_by=question.step
        )
    return ConsultParked(questions[-1])


def run(args: dict[str, Any], ctx: ToolContext) -> ConsultOutcome:
    """Handler for the ``consult`` built-in."""
    if ctx.consult_count >= ctx.max_consultations:
        return ConsultOutcome(False, error=BUDGET_EXHAUSTED)
    try:
        questions = build_questions(args, ctx)
    except ValueError as exc:
        return ConsultOutcome(False, error=f"invalid consultation: {exc}")
    if ctx.consult_count + len(questions) > ctx.max_consultations:
        return ConsultOutcome(False, error=BUDGET_EXHAUSTED)
    ctx.consult_count += len(questions)
    if ctx.consult_decides:
        lines = [_decide(question, ctx) for question in questions]
        if len(lines) > 1:
            lines = [f"Question {i} of {len(lines)}: {line}" for i, line in enumerate(lines, 1)]
        return ConsultOutcome(True, content=_joined(lines))
    if waits_in_turn(ctx):
        return _wait_for_person(questions, ctx)
    if ctx.consult_park and ctx.approval_mode != "refuse":
        raise _park(questions, ctx)
    if ctx.approval_mode != "wait":
        raise ConsultUnavailable("a consultation needs an operator answer and none can be given")
    return ConsultOutcome(True, content=NO_ANSWER)
