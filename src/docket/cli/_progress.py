"""Foreground dispatch progress and the in-place approval prompt.

``docket run`` is silent while a hop blocks on an in-turn
approval, so an operator watching a TTY has no way to learn it is waiting
or to answer it without a second terminal and the token. This module renders
one stderr line per trace event worth surfacing (see ``render_event``) while
``core.dispatch.dispatch_pod`` runs on a worker thread, and -- when stdin is
also a TTY and the caller did not opt out -- reads an in-place answer from a
second thread. Rendering and answer-parsing are pure; ``dispatch_with_progress``
is the one function that owns the threads.
"""

from __future__ import annotations

import datetime as _dt
import queue as _queue
import sys
import threading
import time as _time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal, TextIO

import docket.config as _cfg
from docket.core import approval as _ap
from docket.core import dispatch as _dispatch
from docket.core import runs as _runs
from docket.core import trace as _trace
from docket.core.task_ref import short_id

_POLL_TIMEOUT_S = 0.2
_RENDERABLE_EVENT_TYPES = frozenset(
    {"session_start", "tool_call", "approval_requested", "approval_required", "session_end"}
)
_HOP_MARKER_KEYS = frozenset({"hop", "agent"})
_PROMPT_LINE = "  [a]pprove  [d]eny  [Enter] keep waiting"


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


def _epoch(ts: str) -> float | None:
    try:
        dt = _dt.datetime.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S")
    except (ValueError, IndexError):
        return None
    return dt.replace(tzinfo=_dt.UTC).timestamp()


def _seconds_remaining(record: dict[str, Any], *, now: float | None = None) -> int:
    """``TOOL_APPROVAL_TIMEOUT`` minus the elapsed wall-clock time since
    *record*'s ``ts``, floored at 0 so a slow render never prints a negative
    countdown."""
    elapsed = 0.0
    parsed = _epoch(str(record.get("ts", "")))
    if parsed is not None:
        elapsed = max(0.0, (now if now is not None else _time.time()) - parsed)
    return max(0, int(_cfg.TOOL_APPROVAL_TIMEOUT - elapsed))


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


def parse_answer(line: str) -> str:
    """Normalise one line of prompt input to ``"a"``, ``"d"``, or ``""`` (keep
    waiting) for anything else, including an empty line."""
    token = line.strip().lower()
    return token if token in ("a", "d") else ""


@dataclass(frozen=True, slots=True)
class PromptOutcome:
    """What happened after applying one prompt answer to a token."""

    action: Literal["granted", "denied", "noop", "waiting"]
    message: str | None = None


def handle_approval_prompt(token: str, answer: str) -> PromptOutcome:
    """Apply *answer* to *token* via the grant/deny + ``resolve_waiting_approval``
    pair ``docket task approve``/``docket task deny`` use. Keeps waiting on an empty or
    unknown answer; reports rather than raises a token resolved elsewhere."""
    if answer == "a":
        try:
            _ap.approval_grant(token, channel="cli")
        except _ap.ApprovalNoop:
            return PromptOutcome("noop", "  (already resolved elsewhere)")
        _dispatch.resolve_waiting_approval(token, "granted")
        return PromptOutcome("granted")
    if answer == "d":
        try:
            _ap.approval_deny(token, channel="cli")
        except _ap.ApprovalNoop:
            return PromptOutcome("noop", "  (already resolved elsewhere)")
        _dispatch.resolve_waiting_approval(token, "denied")
        return PromptOutcome("denied")
    return PromptOutcome("waiting")


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

    worker = threading.Thread(target=_worker, daemon=True)
    if prompt:
        threading.Thread(target=stdin_reader_loop, args=(stdin, answers), daemon=True).start()
    worker.start()

    current_token: str | None = None
    while True:
        try:
            record: dict[str, Any] | None = events.get(timeout=_POLL_TIMEOUT_S)
        except _queue.Empty:
            record = None
        if record is not None:
            line = render_event(record)
            if line is not None:
                out(line)
            if record.get("event_type") == "approval_requested":
                payload = record.get("payload")
                token = payload.get("token", "") if isinstance(payload, dict) else ""
                current_token = str(token) or None
                if prompt and current_token:
                    out(_PROMPT_LINE)
        if prompt and current_token:
            try:
                answer = answers.get_nowait()
            except _queue.Empty:
                answer = ""
            if answer:
                result = handle_approval_prompt(current_token, answer)
                if result.message:
                    out(result.message)
                if result.action != "waiting":
                    current_token = None
        if not worker.is_alive() and events.empty():
            break
    worker.join()
    return outcome[0] if outcome else None
