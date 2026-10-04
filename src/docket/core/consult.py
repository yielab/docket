"""The ``consult`` built-in: a model asks its operator a question with options.

The call is validated through ``QuestionV11`` (operator-v1.1) and then, by approval mode:
``wait`` traces a ``question_asked`` event and blocks until an answer reader delivers an
answer (``submit``) or the wait bound passes; ``refuse``/``park`` trace the event and raise
``ConsultUnavailable``, which ``core/tools.py`` renders as the ``approval_unavailable`` stop.
In pod dispatch (``ctx.consult_park``) a non-refuse consult raises ``ConsultParked`` instead:
the hop ends, the task parks ``waiting_input`` and ``core.answers`` re-enters the same role.
The per-task count lives on the task; dispatch passes the remaining budget to each hop.

Tool-visible failures are ordinary error results, never exceptions, so the model can adapt.
"""

from __future__ import annotations

import contextlib
import datetime as _dt
import json
import queue
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import docket.config as _cfg
from docket.core import trace as _trace
from docket.core.operator_contract import (
    AnswerResultV11,
    QuestionV11,
    new_question_id,
    validate_answer_v11,
)

if TYPE_CHECKING:
    from docket.core.tools import ToolContext

DEFAULT_MAX_CONSULTATIONS = 3
NO_ANSWER = "no answer; decide yourself"
BUDGET_EXHAUSTED = "consultation budget exhausted; decide yourself"
QUESTION_EVENT = "question_asked"
PARK_TOKEN_PREFIX = "consult:"

# What an answer may carry besides ``optionId``: one free-text note.
_REQUESTED_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"note": {"type": "string"}},
    "required": [],
}


@dataclass
class ConsultOutcome:
    """What a consult call produced; ``core/tools.py`` wraps it as its ``ConsultOutcome``."""

    ok: bool
    content: str = ""
    error: str = ""


class ConsultUnavailable(Exception):
    """Nobody can answer this consultation (``refuse``/``park``); the turn ends blocked."""


class ConsultParked(ConsultUnavailable):
    """Pod dispatch parks this consultation's task; the question is read back by id."""

    def __init__(self, question_id: str) -> None:
        self.question_id = question_id
        super().__init__("consultation parked for an operator answer")


@dataclass
class _Waiter:
    question: QuestionV11
    answers: queue.Queue[AnswerResultV11 | None]


_LOCK = threading.Lock()
_WAITING: dict[str, _Waiter] = {}
_READERS = 0
_PARKED: dict[str, QuestionV11] = {}


@contextlib.contextmanager
def answer_reader() -> Iterator[None]:
    """Mark that something (the harness stdin reader) will deliver answers while open, and
    release every waiting consultation when it closes."""
    global _READERS
    with _LOCK:
        _READERS += 1
    try:
        yield
    finally:
        with _LOCK:
            _READERS -= 1
        release_all()


def release_all() -> None:
    """Wake every waiting consultation with no answer (end of the answer stream)."""
    with _LOCK:
        waiters = list(_WAITING.values())
    for waiter in waiters:
        waiter.answers.put(None)


def take_parked(question_id: str) -> QuestionV11 | None:
    """The question a parked consult left for dispatch (removed), or ``None`` if unknown."""
    with _LOCK:
        return _PARKED.pop(question_id, None)


def is_waiting(question_id: str) -> bool:
    with _LOCK:
        return question_id in _WAITING


def submit(question_id: str, action: str, content: dict[str, Any] | None) -> str | None:
    """Deliver an answer to the waiting consultation *question_id*. ``content['optionId']``
    names the chosen option. Returns ``None`` when delivered, else a reason (the consultation
    keeps waiting for a valid answer)."""
    with _LOCK:
        waiter = _WAITING.get(question_id)
    if waiter is None:
        return "no such waiting question"
    body = dict(content) if content else {}
    option_id = body.pop("optionId", None)
    try:
        answer = AnswerResultV11.model_validate(
            {"action": action, "content": body or None, "optionId": option_id}
        )
        validate_answer_v11(waiter.question, answer)
    except ValueError as exc:
        return str(exc)
    waiter.answers.put(answer)
    return None


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
        raise ValueError("options must list at least two options")
    if not isinstance(args.get("recommendation"), dict):
        raise ValueError("a consultation must carry a recommendation {optionId, rationale}")
    kind = args.get("kind")
    if kind not in ("clarification", "decision"):
        raise ValueError("kind must be 'clarification' or 'decision'")
    return QuestionV11.model_validate(
        {
            "id": new_question_id(),
            "taskId": ctx.session_key or ctx.agent_id,
            "pod": ctx.project,
            "step": ctx.role or "consult",
            "message": args.get("message"),
            "requestedSchema": _REQUESTED_SCHEMA,
            "createdAt": _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
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


def _wait(question: QuestionV11, ctx: ToolContext) -> ConsultOutcome:
    waiter = _Waiter(question, queue.Queue())
    with _LOCK:
        _WAITING[question.id] = waiter
    try:
        _trace_question(question, ctx)
        deadline = time.monotonic() + max(0, _cfg.TOOL_APPROVAL_TIMEOUT)
        while True:
            if ctx.cancellation_check is not None and ctx.cancellation_check():
                return ConsultOutcome(False, error="run cancellation requested")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return ConsultOutcome(True, content=NO_ANSWER)
            try:
                answer = waiter.answers.get(timeout=min(0.25, remaining))
            except queue.Empty:
                continue
            if answer is None:
                return ConsultOutcome(True, content=NO_ANSWER)
            return ConsultOutcome(
                True,
                content=json.dumps(
                    {
                        "action": answer.action,
                        "optionId": answer.option_id,
                        "content": answer.content,
                    }
                ),
            )
    finally:
        with _LOCK:
            _WAITING.pop(question.id, None)


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
        with _LOCK:
            _PARKED[question.id] = question
        raise ConsultParked(question.id)
    if ctx.approval_mode != "wait":
        _trace_question(question, ctx)
        raise ConsultUnavailable("a consultation needs an operator answer and none can be given")
    with _LOCK:
        has_reader = _READERS > 0
    if not has_reader:
        return ConsultOutcome(True, content=NO_ANSWER)
    return _wait(question, ctx)
