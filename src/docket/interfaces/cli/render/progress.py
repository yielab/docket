"""Foreground dispatch progress and the in-place prompt.

``docket run`` is silent while a hop blocks on an in-turn approval or consult, so an operator
watching a TTY has no way to learn it is waiting or to answer it without a second terminal and an
escalation id. This module renders one stderr line per trace event worth surfacing (see
``render_event``) while ``hops.application.sweep.dispatch_pod`` runs on a worker thread, and --
when stdin is also a TTY and the caller did not opt out -- reads an in-place answer from a second
thread and resolves the escalation with it. Rendering and answer-parsing are pure;
``dispatch_with_progress`` is the one function that owns the threads.
"""

from __future__ import annotations

import queue as _queue
import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal, TextIO

from docket.governance import approval as _ap
from docket.interfaces.cli.render.escalation import answer_command
from docket.kernel import clock as _clock
from docket.kernel import text as _text
from docket.kernel import threads as _threads
from docket.kernel.operator_contract import EscalationView
from docket.observability import trace as _trace
from docket.operator import escalation_view, ids_line, render_escalation
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
    {"session_start", "tool_call", "escalation_asked", "session_end"}
)
_HOP_MARKER_KEYS = frozenset({"hop", "agent"})
_PROMPT_MAX = 300
_PROMPT_LINE = "  [a]pprove  [d]eny  [Enter] keep waiting"
_ALREADY = "  (already resolved elsewhere)"
_APPROVAL_KINDS = frozenset({"approval", "gate", "check_changed"})


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
    """True when an ``escalation_asked`` event should also prompt in place:
    rendering must be on, ``--no-prompt`` absent, and stdin a real TTY --
    stderr being a TTY never implies stdin is."""
    return render and not no_prompt_flag and stdin_isatty()


def _remaining_label(payload: dict[str, Any], *, now: float | None = None) -> str:
    """How long until the pause *payload* describes expires: seconds under an hour, else hours;
    ``""`` when it carries no deadline."""
    deadline = _clock.parse_epoch(payload.get("expiresAt"))
    if deadline is None:
        return ""
    left = max(0, int(deadline - (now if now is not None else _clock.epoch())))
    return f"{left}s" if left < 3600 else f"{left // 3600}h"


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
    view does not render (a question's own line is ``question_line``, printed with its options)."""
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
    kind = str(payload.get("kind", ""))
    if kind not in _APPROVAL_KINDS:
        return None
    escalation = str(payload.get("escalation", "?"))
    prompt = _text.ellipsize(_text.one_line(str(payload.get("prompt", ""))), _PROMPT_MAX)
    left = _remaining_label(payload, now=now)
    wants = (
        f"⏸ {role} wants: {prompt}" if kind == "approval" else f"⏸ {role} needs approval: {prompt}"
    )
    return (
        f"{wants} · {escalation}"
        + (f" · denies in {left}" if left else "")
        + f" · docket task answer {escalation} --option approve_once"
    )


def question_line(view: EscalationView) -> str:
    """The one stderr line for a pause that asks a question: who asks what, which options, and the
    command that answers it. The operator's own terminal gets everything the pause carries."""
    rendered = render_escalation(view, "full")
    prompt = _text.ellipsize(_text.one_line(rendered.prompt or ""), _PROMPT_MAX)
    parts = [f"⏸ {view.role or view.step} asks: {rendered.title}: {prompt}"]
    if rendered.options:
        parts.append(f"options {ids_line(rendered.options)}")
    parts.append(answer_command(view.task or view.id, rendered.options))
    return " · ".join(parts)


def parse_answer(line: str) -> str:
    """Normalise one line of prompt input to ``"a"``, ``"d"``, an option number (``"1"``, ``"2"``...)
    or ``""`` (keep waiting) for anything else, including an empty line."""
    token = line.strip().lower()
    if token in ("a", "d") or (token.isascii() and token.isdigit() and int(token) > 0):
        return token
    return ""


@dataclass(frozen=True, slots=True)
class PromptOutcome:
    """What happened after applying one prompt answer to an escalation."""

    action: Literal["granted", "denied", "noop", "waiting"]
    message: str | None = None


def _refused(err: Exception) -> PromptOutcome:
    """The answer lost to a decision already made, a pause that ended or a record that is gone:
    say so."""
    if isinstance(err, EscalationNotPending) and err.already_so:
        return PromptOutcome("noop", _ALREADY)
    return PromptOutcome("noop", f"  ({err})")


def _resolve(escalation_id: str, option: str) -> PromptOutcome | None:
    """Resolve *escalation_id* with *option* as `docket task answer` does; ``None`` when it went
    through, else why not."""
    try:
        _escalations.resolve(escalation_id, option, None, by="", channel="cli")
    except (EscalationNotPending, EscalationNotFound, EscalationInvalid) as err:
        return _refused(err)
    return None


def handle_approval_prompt(escalation_id: str, answer: str) -> PromptOutcome:
    """Apply *answer* to the approval *escalation_id* as `docket task answer` does. Keeps waiting
    on an empty or unknown answer; reports, never raises, a pause already decided or gone."""
    if answer not in ("a", "d"):
        return PromptOutcome("waiting")
    refused = _resolve(escalation_id, "approve_once" if answer == "a" else "deny")
    if refused is not None:
        return refused
    return PromptOutcome("granted" if answer == "a" else "denied")


def handle_question_prompt(escalation_id: str, option_ids: list[str], answer: str) -> PromptOutcome:
    """Answer the consult waiting on *escalation_id*: a number picks that option of *option_ids*,
    ``d`` declines. Keeps waiting on anything else; reports, never raises, a pause already
    settled."""
    if answer == "d":
        option = "decline"
    elif answer.isdigit() and 1 <= int(answer) <= len(option_ids):
        option = option_ids[int(answer) - 1]
    elif answer.isdigit():
        return PromptOutcome("waiting", f"  (no option {answer}; choose 1-{len(option_ids)} or d)")
    else:
        return PromptOutcome("waiting")
    refused = _resolve(escalation_id, option)
    if refused is not None:
        return refused
    return PromptOutcome("denied" if option == "decline" else "granted")


def consult_lines(view: EscalationView) -> list[str]:
    """The question a consult waiting in the turn asks and the line that answers it in place."""
    options = [o for o in view.options if o.id != "decline"]
    numbered = "  ".join(
        f"[{i}] {o.id}" + (f" ({o.label})" if o.label and o.label != o.id else "")
        for i, o in enumerate(options, 1)
    )
    ask = f"⏸ {view.role or '?'} asks: {_text.ellipsize(_text.one_line(view.prompt), _PROMPT_MAX)}"
    ids = ", ".join(o.id for o in options)
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


def _on_asked(
    record: dict[str, Any], *, prompt: bool, out: Callable[[str], None]
) -> tuple[str | None, list[str] | None]:
    """Print what an ``escalation_asked`` *record* asks. Returns the escalation the prompt now
    answers and, for a consult waiting in the turn, its option ids (``None`` for an approval)."""
    payload_raw = record.get("payload")
    payload: dict[str, Any] = payload_raw if isinstance(payload_raw, dict) else {}
    escalation_id = str(payload.get("escalation", ""))
    kind = str(payload.get("kind", ""))
    stored = read_escalation(escalation_id)
    if kind in _APPROVAL_KINDS:
        line = render_event(record)
        if line is not None:
            out(line)
        if prompt:
            out(_PROMPT_LINE)
        return (escalation_id, None) if prompt and stored is not None else (None, None)
    if stored is None:
        return None, None
    view = escalation_view(stored)
    # A consult blocking a running turn is answered in place; a parked question is announced.
    if _ap.approval_of(escalation_id):
        ask, choices = consult_lines(view)
        out(ask)
        if prompt:
            out(choices)
        options = [o.id for o in view.options if o.id != "decline"]
        return (escalation_id, options) if prompt else (None, None)
    out(question_line(view))
    return None, None


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
    ``escalation_asked`` in place. Returns what ``_runs.execute`` would have."""
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

    worker = _threads.new_thread(_worker)
    if prompt:
        _threads.start_thread(stdin_reader_loop, (stdin, answers))
    worker.start()

    current: str | None = None
    current_options: list[str] | None = None
    while True:
        try:
            record: dict[str, Any] | None = events.get(timeout=_POLL_TIMEOUT_S)
        except _queue.Empty:
            record = None
        if record is not None:
            if record.get("event_type") == "escalation_asked":
                current, current_options = _on_asked(record, prompt=prompt, out=out)
            else:
                line = render_event(record)
                if line is not None:
                    out(line)
        if prompt and current:
            try:
                answer = answers.get_nowait()
            except _queue.Empty:
                answer = ""
            if answer:
                result = (
                    handle_approval_prompt(current, answer)
                    if current_options is None
                    else handle_question_prompt(current, current_options, answer)
                )
                if result.message:
                    out(result.message)
                if result.action != "waiting":
                    current = None
        if not worker.is_alive() and events.empty():
            break
    worker.join()
    return outcome[0] if outcome else None
