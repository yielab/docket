"""``docket harness run --answers stdin`` -- the caller's side of a paused approval.

A run in wait mode blocks its turn on each approval it asks for. A caller answers
by writing one ``AnswerLine`` per line to this process's stdin. Every line that
cannot be applied is ignored with one fixed stderr line, and the approval it
would have resolved stays pending until its deadline, which denies it. Nothing
here echoes a line's contents, because a line may carry a credential value.

stdout stays NDJSON only; this module writes nothing to stdout.
"""

from __future__ import annotations

import contextlib
import json
import queue
import re
import sys
import threading
from collections.abc import Iterator

from pydantic import ValidationError

import docket.config as _cfg
from docket.core import approval as _approval
from docket.core import harness
from docket.core.policy import policy_eval_detail

# Approval tokens are minted as ``apr-<uuid4>`` by core/approval.py. An answer's
# token becomes a path under the approvals directory, so anything else is refused
# before it is used.
_APPROVAL_TOKEN = re.compile(r"apr-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")

# A content hit with either of these actions holds the answer, as /delegate does.
_HOLD_ACTIONS = ("block", "require_approval")


def _say(message: str) -> None:
    print(f"docket harness: {message}", file=sys.stderr, flush=True)


def handle_line(
    line: str,
    token: str,
    questions: queue.Queue[harness.AnswerLine | None] | None = None,
    ledger: harness.ApprovalLedger | None = None,
) -> None:
    """Apply one stdin line to the run *token*. Never raises for a bad line. A question answer
    goes to *questions* when a recipe run is waiting for one, else it is ignored. An approval
    decision that this call applies is recorded on *ledger* for the result's ``approvals``."""
    text = line.strip()
    if not text:
        return
    try:
        answer_line = harness.AnswerLine.model_validate_json(text)
    except ValidationError:
        _say("answer line ignored: not a valid answer line")
        return
    if answer_line.token != token:
        _say("answer line ignored: token does not match this run")
        return

    answer = answer_line.answer
    if answer.questionId is not None:
        if questions is None:
            _say("answer line ignored: question answers need --recipe")
        else:
            questions.put(answer_line)
        return
    target = answer.approvalToken or ""
    if not _APPROVAL_TOKEN.fullmatch(target):
        _say("answer line ignored: unknown approval")
        return

    if answer.content is not None:
        hit = policy_eval_detail(
            "lead", "pre_input", json.dumps(answer.content, sort_keys=True), trusted=False
        )
        if hit.action in _HOLD_ACTIONS:
            _say(f"answer line held by policy {hit.policy_id!r}; approval still pending")
            return

    try:
        if answer.action == "accept":
            _approval.approval_grant(target, channel="harness")
        else:
            _approval.approval_deny(target, channel="harness")
    except (_approval.ApprovalNoop, _approval.ApprovalConflict):
        _say("answer ignored: approval already resolved")
    except _approval.ApprovalError:
        _say("answer ignored: unknown approval")
    else:
        if ledger is not None:
            ledger.answered(target, answer.action)


@contextlib.contextmanager
def serve(
    token: str,
    stop: threading.Event,
    questions: queue.Queue[harness.AnswerLine | None] | None = None,
    ledger: harness.ApprovalLedger | None = None,
) -> Iterator[None]:
    """Read answers for run *token* from stdin on a daemon thread until EOF or *stop*. At EOF a
    *questions* queue gets its ``None`` end marker, so a waiting question stops waiting."""

    def _pump() -> None:
        for line in sys.stdin:
            if stop.is_set():
                return
            try:
                handle_line(line, token, questions, ledger)
            except Exception:
                # An answer that cannot be applied leaves its approval pending, and
                # the deadline denies it. Say so without the line's contents.
                _say("answer line ignored: internal error")
        if questions is not None:
            questions.put(None)

    thread = threading.Thread(target=_pump, name="harness-answers", daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()


@contextlib.contextmanager
def guard(
    answers_raw: str | None,
    answer_timeout_raw: str | None,
    token: str,
    questions: queue.Queue[harness.AnswerLine | None] | None = None,
    ledger: harness.ApprovalLedger | None = None,
) -> Iterator[None]:
    """Run the answer reader and the wait bound for ``--answers stdin``; otherwise a no-op."""
    if answers_raw != "stdin":
        yield
        return
    timeout = int(answer_timeout_raw) if answer_timeout_raw is not None else None
    with serve(token, threading.Event(), questions, ledger), wait_budget(timeout):
        yield


@contextlib.contextmanager
def wait_budget(seconds: int | None) -> Iterator[None]:
    """Bound in-turn approval waits to *seconds* inside the block; ``None`` leaves them alone.

    The harness is its own process, so this sets ``config.TOOL_APPROVAL_TIMEOUT`` and restores it."""
    if seconds is None:
        yield
        return
    saved = _cfg.TOOL_APPROVAL_TIMEOUT
    _cfg.TOOL_APPROVAL_TIMEOUT = seconds
    try:
        yield
    finally:
        _cfg.TOOL_APPROVAL_TIMEOUT = saved
