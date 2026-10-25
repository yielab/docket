"""Foreground dispatch progress and the in-place approval prompt.

``docket run`` is silent while a hop blocks on an in-turn
approval or consult, so an operator watching a TTY has no way to learn it is waiting
or to answer it without a second terminal and the token. This module renders
one stderr line per trace event worth surfacing (see ``render_event``) while
``hops.application.sweep.dispatch_pod`` runs on a worker thread, and -- when stdin is
also a TTY and the caller did not opt out -- reads an in-place answer from a
second thread. Rendering and answer-parsing are pure; ``dispatch_with_progress``
is the one function that owns the threads.
"""

from __future__ import annotations

import queue as _queue
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal, TextIO

from docket.governance import approval as _ap
from docket.interfaces.cli.render.escalation import answer_command
from docket.kernel import clock as _clock
from docket.kernel import text as _text
from docket.kernel import threads as _threads
from docket.kernel.home import current_home
from docket.kernel.operator_contract import EscalationView
from docket.observability import trace as _trace
from docket.operator import escalation_views, ids_line, render_escalation
from docket.platform import read_escalation
from docket.tasks.application import escalations as _escalations
from docket.tasks.application import runs as _runs
from docket.tasks.domain.refs import short_id
from docket.tasks.domain.resolution import (
    EscalationInvalid,
    EscalationNotFound,
    EscalationNotPending,
)

_POLL_TIMEOUT_S = 0.2
_RENDERABLE_EVENT_TYPES = frozenset(
    {"session_start", "tool_call", "approval_requested", "approval_required", "session_end"}
)
_HOP_MARKER_KEYS = frozenset({"hop", "agent"})
# A question's trace event comes before, or just after, the record of the pause it opens; the
# record is what carries the options, so the line waits for it for a few seconds.
_QUESTION_EVENTS = frozenset({"question_asked", "input_requested"})
_QUESTION_WAIT_S = 5.0
_PROMPT_MAX = 300
_PROMPT_LINE = "  [a]pprove  [d]eny  [Enter] keep waiting"
_ALREADY = "  (already resolved elsewhere)"
# A consult requests its approval before it opens the escalation that approval belongs to, so a
# very fast answer waits (in steps of 50 ms, up to a second) for the record to exist.
_RECORD_POLLS = 20


def should_render(
    *,
    progress_flag: bool,
    stderr_isatty: Callable[[], bool] = lambda: sys.stderr.isatty(),
) -> bool:
    """True when the foreground progress view should render: an explicit
    ``--progress`` forces it, else stderr must be a real TTY."""
    return progress_flag or stderr_isatty()


def should_prompt(
    *,
    no_prompt_flag: bool,
    render: bool,
    stdin_isatty: Callable[[], bool] = lambda: sys.stdin.isatty(),
) -> bool:
    """True when an ``approval_requested`` event should also prompt in place:
    rendering must be on, ``--no-prompt`` absent, and stdin a real TTY --
    stderr being a TTY never implies stdin is."""
    return render and not no_prompt_flag and stdin_isatty()


def _seconds_remaining(record: dict[str, Any], *, now: float | None = None) -> int:
    """``TOOL_APPROVAL_TIMEOUT`` minus the elapsed wall-clock time since
    *record*'s ``ts``, floored at 0 so a slow render never prints a negative
    countdown."""
    elapsed = 0.0
    parsed = _clock.parse_epoch(record.get("ts"))
    if parsed is not None:
        elapsed = max(0.0, (now if now is not None else _clock.epoch()) - parsed)
    return max(0, int(current_home().tool_approval_timeout - elapsed))


def _session_label(record: dict[str, Any], role: str) -> str:
    """The short id of the task a dispatch session id (``agent:<project>:<task-id>``)
    names, else *role*."""
    parts = str(record.get("session_id", "")).split(":")
    if len(parts) == 3 and parts[0] == "agent" and parts[2]:
        return short_id(parts[2])
    return role


def _is_hop_marker(payload: dict[str, Any]) -> bool:
    return set(payload) == _HOP_MARKER_KEYS


def render_event(record: dict[str, Any], *, now: float | None = None) -> str | None:
    """The one stderr line for *record*, or None for an event the foreground
    view does not render."""
    event_type = str(record.get("event_type", ""))
    if event_type not in _RENDERABLE_EVENT_TYPES:
        return None
    role = str(record.get("agent_role", "?"))
    payload_raw = record.get("payload")
    payload: dict[str, Any] = payload_raw if isinstance(payload_raw, dict) else {}
    if event_type == "tool_call":
        return f"  ▶ {payload['hop']} …" if _is_hop_marker(payload) else None
    if event_type == "session_start":
        return f"▶ {_session_label(record, role)} …"
    if event_type == "session_end":
        status = str(payload.get("status", "?"))
        return f"■ {_session_label(record, role)} finished — status={status}"
    token = str(payload.get("token", "?"))
    if event_type == "approval_required":
        return f"⏸ {role} hop needs approval · token {token} · docket task approve {token}"
    action = str(payload.get("action", ""))
    remaining = _seconds_remaining(record, now=now)
    return (
        f"⏸ {role} wants: {action} · token {token} · denies in {remaining}s · "
        f"docket task approve {token}"
    )


def question_line(view: EscalationView) -> str:
    """The one stderr line for a task parked on a question: who asks what, which options, and the
    command that answers it. The operator's own terminal gets everything the pause carries."""
    rendered = render_escalation(view, "full")
    prompt = _text.ellipsize(_text.one_line(rendered.prompt or ""), _PROMPT_MAX)
    parts = [f"⏸ {view.role or view.step} asks: {rendered.title}: {prompt}"]
    if rendered.options:
        parts.append(f"options {ids_line(rendered.options)}")
    parts.append(answer_command(view.task, rendered.options))
    return " · ".join(parts)


def _waits_in_turn(escalation_id: str) -> bool:
    """Whether the question waits in a turn on an approval record, which this view asks itself
    when that record is requested, instead of announcing it as a parked task's question."""
    stored = read_escalation(escalation_id)
    return stored is not None and bool(stored.legacy.get("token"))


def _announce_questions(baseline: int, announced: set[str]) -> list[str]:
    """The lines for questions parked since *baseline* that were not announced yet."""
    lines = []
    for view in escalation_views(since_seq=baseline):
        if (
            view.kind in ("consult", "input")
            and view.state == "pending"
            and view.id not in announced
            and not _waits_in_turn(view.id)
        ):
            announced.add(view.id)
            lines.append(question_line(view))
    return lines


def parse_answer(line: str) -> str:
    """Normalise one line of prompt input to ``"a"``, ``"d"``, an option number (``"1"``, ``"2"``...)
    or ``""`` (keep waiting) for anything else, including an empty line."""
    token = line.strip().lower()
    if token in ("a", "d") or (token.isascii() and token.isdigit() and int(token) > 0):
        return token
    return ""


@dataclass(frozen=True, slots=True)
class PromptOutcome:
    """What happened after applying one prompt answer to a token."""

    action: Literal["granted", "denied", "noop", "waiting"]
    message: str | None = None


def _refused(err: Exception) -> PromptOutcome:
    """The answer lost to a decision already made, a pause that ended or a record that is gone:
    say so."""
    if isinstance(err, EscalationNotPending) and err.already_so:
        return PromptOutcome("noop", _ALREADY)
    return PromptOutcome("noop", f"  ({err})")


def _resolve_token(token: str, option: str) -> PromptOutcome | None:
    """Resolve the escalation of *token* with *option* as ``docket task approve``/``deny`` do;
    ``None`` when it went through, else why not."""
    try:
        _escalations.resolve_approval_token(token, option, channel="cli", actor="")
    except (EscalationNotPending, EscalationNotFound, EscalationInvalid) as err:
        return _refused(err)
    return None


def handle_approval_prompt(token: str, answer: str) -> PromptOutcome:
    """Apply *answer* to *token* as ``docket task approve``/``deny`` do, through ``resolve`` so the
    record settles too. Keeps waiting on an empty or unknown answer; reports, never raises, a
    token already decided or with no record."""
    if answer not in ("a", "d"):
        return PromptOutcome("waiting")
    refused = _resolve_token(token, "approve_once" if answer == "a" else "deny")
    if refused is not None:
        return refused
    return PromptOutcome("granted" if answer == "a" else "denied")


def _approval_pending(token: str) -> bool:
    try:
        return _ap.approval_get(token).get("state") == "pending"
    except _ap.ApprovalError:
        return False


def handle_question_prompt(token: str, option_ids: list[str], answer: str) -> PromptOutcome:
    """Answer the consult waiting on *token*: a number picks that option of *option_ids*, ``d``
    declines. Keeps waiting on anything else; reports, never raises, a pause already settled."""
    if answer == "d":
        option = "decline"
    elif answer.isdigit() and 1 <= int(answer) <= len(option_ids):
        option = option_ids[int(answer) - 1]
    elif answer.isdigit():
        return PromptOutcome("waiting", f"  (no option {answer}; choose 1-{len(option_ids)} or d)")
    else:
        return PromptOutcome("waiting")
    for _ in range(_RECORD_POLLS):
        if _escalations.waiting_for_token(token) or not _approval_pending(token):
            break
        time.sleep(0.05)
    refused = _resolve_token(token, option)
    if refused is not None:
        return refused
    return PromptOutcome("denied" if option == "decline" else "granted")


def consult_options(record: dict[str, Any]) -> list[tuple[str, str]] | None:
    """The ``(id, label)`` options of the consult an ``approval_requested`` *record* opens, or
    ``None`` for any other event or an approval that is not a consult's."""
    if record.get("event_type") != "approval_requested":
        return None
    payload = record.get("payload")
    token = str(payload.get("token", "")) if isinstance(payload, dict) else ""
    try:
        context = _ap.approval_get(token).get("context")
    except _ap.ApprovalError:
        return None
    if not isinstance(context, dict) or context.get("kind") != "consult":
        return None
    return [(str(o["id"]), str(o.get("label", ""))) for o in context.get("options", [])]


def consult_lines(record: dict[str, Any], options: list[tuple[str, str]]) -> list[str]:
    """The question a waiting consult asks and the line that answers it in place."""
    payload = record.get("payload")
    action = str(payload.get("action", "")) if isinstance(payload, dict) else ""
    role = str(record.get("agent_role", "?"))
    numbered = "  ".join(
        f"[{i}] {oid}" + (f" ({label})" if label and label != oid else "")
        for i, (oid, label) in enumerate(options, 1)
    )
    ask = f"⏸ {role} asks: {_text.ellipsize(_text.one_line(action), _PROMPT_MAX)}"
    ids = ", ".join(oid for oid, _ in options)
    return [f"{ask} · options {ids}", f"  {numbered}  [d]ecline  [Enter] keep waiting"]


def stdin_reader_loop(stdin: TextIO, answers: _queue.Queue[str]) -> None:
    """Block on ``stdin.readline()`` until EOF, pushing each parsed answer onto
    *answers*. The prompt-reading thread's body; touches no approval state
    itself, so it stays testable with a plain ``io.StringIO``."""
    while True:
        line = stdin.readline()
        if not line:
            return
        answer = parse_answer(line)
        if answer:
            answers.put_nowait(answer)


def dispatch_with_progress(
    run_id: str,
    fn: Callable[[], list[Any]],
    *,
    prompt: bool,
    stderr: TextIO | None = None,
    stdin: TextIO | None = None,
    println: Callable[[str], None] | None = None,
) -> list[Any] | None:
    """Run *fn* (``_runs.execute``'s callable) on a worker thread, rendering one
    stderr line per trace event and, when *prompt* is set, answering
    ``approval_requested`` in place. Returns what ``_runs.execute`` would have."""
    # Resolved here, not as a default-argument value: a default binds once, at
    # module import, and would miss a caller's later `sys.stdin`/`sys.stderr`.
    stderr = stderr if stderr is not None else sys.stderr
    stdin = stdin if stdin is not None else sys.stdin
    out = println or (lambda line: print(line, file=stderr))
    events: _queue.Queue[dict[str, Any]] = _queue.Queue()
    answers: _queue.Queue[str] = _queue.Queue()
    outcome: list[list[Any] | None] = []

    def _sink(record: dict[str, Any]) -> None:
        events.put_nowait(record)

    def _worker() -> None:
        with _trace.subscribe(_sink):
            outcome.append(_runs.execute(run_id, fn))

    # Questions already parked are old news; only those that appear during this run are announced.
    baseline = max((v.seq for v in escalation_views()), default=0)
    worker = _threads.new_thread(_worker)
    if prompt:
        _threads.start_thread(stdin_reader_loop, (stdin, answers))
    worker.start()

    current_token: str | None = None
    current_options: list[str] | None = None
    announced: set[str] = set()
    watch_questions_until = 0.0
    while True:
        try:
            record: dict[str, Any] | None = events.get(timeout=_POLL_TIMEOUT_S)
        except _queue.Empty:
            record = None
        if record is not None:
            asked = consult_options(record)
            line = render_event(record) if asked is None else None
            if line is not None:
                out(line)
            if record.get("event_type") in _QUESTION_EVENTS:
                watch_questions_until = _clock.monotonic() + _QUESTION_WAIT_S
            if record.get("event_type") == "approval_requested":
                payload = record.get("payload")
                token = payload.get("token", "") if isinstance(payload, dict) else ""
                current_token = str(token) or None
                current_options = None if asked is None else [oid for oid, _ in asked]
                if asked is not None:
                    ask, choices = consult_lines(record, asked)
                    out(ask)
                    if prompt and current_token:
                        out(choices)
                elif prompt and current_token:
                    out(_PROMPT_LINE)
        if watch_questions_until:
            for line in _announce_questions(baseline, announced):
                out(line)
            if _clock.monotonic() >= watch_questions_until:
                watch_questions_until = 0.0
        if prompt and current_token:
            try:
                answer = answers.get_nowait()
            except _queue.Empty:
                answer = ""
            if answer:
                result = (
                    handle_approval_prompt(current_token, answer)
                    if current_options is None
                    else handle_question_prompt(current_token, current_options, answer)
                )
                if result.message:
                    out(result.message)
                if result.action != "waiting":
                    current_token = None
        if not worker.is_alive() and events.empty():
            break
    worker.join()
    return outcome[0] if outcome else None
