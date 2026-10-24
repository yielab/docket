"""The ``consult`` built-in: a model asks its operator a question with options.

The call is validated through ``QuestionV11`` (operator-v1.1) and then, by approval mode:
``wait`` has nobody to ask and answers "no answer; decide yourself"; ``refuse``/``park`` trace
the event and raise ``ConsultUnavailable``, which ``agent/tools/registry.py`` renders as the
``approval_unavailable`` stop.
In pod dispatch (``ctx.consult_park``) a non-refuse consult raises ``ConsultParked`` instead:
the hop ends, the task parks ``waiting_input`` and ``tasks.application.answers`` re-enters the same role.
The per-task count lives on the task; dispatch passes the remaining budget to each hop.

Tool-visible failures are ordinary error results, never exceptions, so the model can adapt.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from docket.kernel import clock as _clock
from docket.kernel.errors import InvalidInput, Refused
from docket.kernel.gate import HandlerParked, HandlerUnavailable
from docket.kernel.operator_contract import AnswerResultV11, QuestionV11, new_question_id
from docket.observability import trace as _trace
from docket.platform import PARK_TOKEN_PREFIX, is_question_id, write_parked

if TYPE_CHECKING:
    from docket.agent.tools.registry import ToolContext

NO_ANSWER = "no answer; decide yourself"
BUDGET_EXHAUSTED = "consultation budget exhausted; decide yourself"
QUESTION_EVENT = "question_asked"

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
    question: QuestionV11, answer: AnswerResultV11, content: dict[str, Any] | None
) -> str:
    """What the resumed role reads: the operator's answer to its parked consultation."""
    head = f"Operator answered your consultation {question.id}:"
    if answer.action != "accept":
        return f"{head} declined. Decide yourself."
    label = next((o.label for o in question.options if o.id == answer.option_id), "")
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


def _trace_question(question: QuestionV11, ctx: ToolContext) -> None:
    payload = {
        "questionId": question.id,
        "kind": question.kind,
        "mode": ctx.approval_mode,
        "question": question.model_dump(by_alias=True, mode="json"),
    }
    _trace.trace_event(
        ctx.project or ctx.agent_id,
        ctx.session_key,
        ctx.role,
        QUESTION_EVENT,
        json.dumps(payload),
    )


def run(args: dict[str, Any], ctx: ToolContext) -> ConsultOutcome:
    """Handler for the ``consult`` built-in."""
    if ctx.consult_count >= ctx.max_consultations:
        return ConsultOutcome(False, error=BUDGET_EXHAUSTED)
    try:
        question = build_question(args, ctx)
    except ValueError as exc:
        return ConsultOutcome(False, error=f"invalid consultation: {exc}")
    ctx.consult_count += 1
    if ctx.consult_park and ctx.approval_mode != "refuse":
        _trace_question(question, ctx)
        raise ConsultParked(question)
    if ctx.approval_mode != "wait":
        _trace_question(question, ctx)
        raise ConsultUnavailable("a consultation needs an operator answer and none can be given")
    return ConsultOutcome(True, content=NO_ANSWER)
