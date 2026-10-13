"""``docket exec --answers stdin`` -- the caller's side of a paused approval.

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
import os
import queue
import select
import sys
import threading
from collections.abc import Iterator

from pydantic import ValidationError

from docket.core import approval as _approval
from docket.core import consult as _consult
from docket.core import harness
from docket.core.policy import policy_eval_detail

# Approval tokens are minted as ``apr-<uuid4>`` by core/approval.py, which owns the form.
_APPROVAL_TOKEN = _approval.APPROVAL_TOKEN_RE

# A content hit with either of these actions holds the answer, as /delegate does.
_HOLD_ACTIONS = ("block", "require_approval")

_POLL_S = 0.1
_EOF = "\0eof"


def _say(message: str) -> None:
    print(f"docket exec: {message}", file=sys.stderr, flush=True)


def handle_line(
    line: str,
    token: str,
    questions: queue.Queue[harness.AnswerLine | None] | None = None,
    ledger: harness.ApprovalLedger | None = None,
    version: str = harness.HARNESS_CONTRACT_V11,
) -> None:
    """Apply one stdin line to the run *token*. Never raises for a bad line. A question answer
    goes to *questions* when a recipe run is waiting for one, else it is ignored. An approval
    decision that this call applies is recorded on *ledger* for the result's ``approvals``.
    The line must be stamped with the run's contract *version*."""
    text = line.strip()
    if not text:
        return
    line_model = (
        harness.AnswerLineV12 if version == harness.HARNESS_CONTRACT_V12 else harness.AnswerLine
    )
    try:
        answer_line = line_model.model_validate_json(text)
    except ValidationError:
        _say("answer line ignored: not a valid answer line")
        return
    if answer_line.token != token:
        _say("answer line ignored: token does not match this run")
        return

    answer = answer_line.answer
    if answer.questionId is not None:
        if _consult.is_waiting(answer.questionId):
            _deliver_consult(answer)
        elif questions is None or not isinstance(answer_line, harness.AnswerLine):
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

    # Extract reason from content if it's a string
    reason = ""
    if answer.content is not None and isinstance(answer.content.get("reason"), str):
        reason = answer.content["reason"]

    option_id = ""
    if answer.content is not None and "optionId" in answer.content:
        raw_option = answer.content["optionId"]
        option_id = raw_option if isinstance(raw_option, str) else ""
        if option_id not in _approval.APPROVAL_OPTION_IDS:
            _say("answer line ignored: unknown option")
            return
        if (option_id == "deny") != (answer.action != "accept"):
            _say("answer line ignored: option does not match action")
            return

    # Only pass actor when there's a reason to record
    actor = "harness" if reason else ""

    try:
        if option_id == "approve_task":
            _approval.approval_set_option(target, option_id)
        if answer.action == "accept":
            _approval.approval_grant(target, channel="harness", actor=actor, reason=reason)
        else:
            _approval.approval_deny(target, channel="harness", actor=actor, reason=reason)
    except (_approval.ApprovalNoop, _approval.ApprovalConflict):
        _say("answer ignored: approval already resolved")
    except _approval.ApprovalError:
        _say("answer ignored: unknown approval")
    else:
        if ledger is not None:
            ledger.answered(target, answer.action)


def _deliver_consult(answer: harness.Answer) -> None:
    """Route a ``questionId`` answer to the waiting ``consult`` call. Its content is screened
    like an approval's; a held or invalid answer leaves the call waiting."""
    assert answer.questionId is not None
    if answer.content is not None:
        hit = policy_eval_detail(
            "lead", "pre_input", json.dumps(answer.content, sort_keys=True), trusted=False
        )
        if hit.action in _HOLD_ACTIONS:
            _say(f"answer line held by policy {hit.policy_id!r}; question still pending")
            return
    if _consult.submit(answer.questionId, answer.action, answer.content) is not None:
        _say("answer line ignored: not a valid answer to this question")


@contextlib.contextmanager
def serve(
    token: str,
    stop: threading.Event,
    questions: queue.Queue[harness.AnswerLine | None] | None = None,
    ledger: harness.ApprovalLedger | None = None,
    version: str = harness.HARNESS_CONTRACT_V11,
) -> Iterator[None]:
    """Read answers for run *token* from stdin on a thread, joined on exit, until EOF or *stop*. At EOF a
    *questions* queue gets its ``None`` end marker and the approval answer stream is closed
    (``core.approval.close_answer_stream``): nobody will answer, so nothing waits on them."""

    def _lines() -> Iterator[str]:
        fd = sys.stdin.fileno()
        pending = b""
        while not stop.is_set():
            ready, _, _ = select.select([fd], [], [], _POLL_S)
            if not ready:
                continue
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            pending += chunk
            *whole, pending = pending.split(b"\n")
            for raw in whole:
                yield raw.decode("utf-8", "replace")
        else:
            return
        if pending:
            yield pending.decode("utf-8", "replace")
        yield _EOF

    def _pump() -> None:
        for line in _lines():
            if stop.is_set():
                return
            if line is _EOF:
                break
            try:
                handle_line(line, token, questions, ledger, version)
            except Exception:
                # An answer that cannot be applied leaves its approval pending, and
                # the deadline denies it. Say so without the line's contents.
                _say("answer line ignored: internal error")
        else:
            return
        if questions is not None:
            questions.put(None)
        _consult.release_all()
        if not stop.is_set():
            # End of stdin: the caller is gone or done. An approval waiting now, or asked
            # for later, has nobody to answer it -- the ledger learns the moment first so
            # the denial that follows is reported ``unanswered``, not ``timed_out``.
            if ledger is not None:
                ledger.stream_closed()
            _approval.close_answer_stream()
            _say("answer stream closed; a gated call is now refused")

    _approval.open_answer_stream()
    thread = threading.Thread(target=_pump, name="harness-answers", daemon=True)
    thread.start()
    try:
        with _consult.answer_reader():
            yield
    finally:
        stop.set()
        thread.join()
        _approval.open_answer_stream()


@contextlib.contextmanager
def guard(
    answers_raw: str | None,
    token: str,
    questions: queue.Queue[harness.AnswerLine | None] | None = None,
    ledger: harness.ApprovalLedger | None = None,
    version: str = harness.HARNESS_CONTRACT_V11,
) -> Iterator[None]:
    """Run the answer reader for ``--answers stdin``; otherwise a no-op."""
    if answers_raw != "stdin":
        yield
        return
    with serve(token, threading.Event(), questions, ledger, version):
        yield
