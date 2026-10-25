"""The inbox command: everything across every pod that needs a human.

A plain call advances a durable cursor so a repeat call shows only newly finished tasks;
--peek reads without advancing it and --since overrides the stored cursor for one call.
"""

from __future__ import annotations

from typing import Any

import typer

from docket.governance import approval as _approval
from docket.interfaces.cli.commands import contract as _contract
from docket.interfaces.cli.commands import status as _status
from docket.interfaces.cli.render import ui
from docket.interfaces.cli.render.escalation import answer_command, options_line
from docket.kernel import clock as _clock
from docket.kernel.home import current_home
from docket.kernel.operator_contract import ApprovalView, EscalationView, InboxView, TaskView
from docket.operator import (
    MemoryItem,
    build_inbox,
    pending_memory,
    question_escalation,
    render_escalation,
    task_view,
)
from docket.operator.render import render_options
from docket.platform import read_json, write_json
from docket.tasks.application.repository import TaskRepository

# The operator's own terminal sees everything the pause carries.
_LEVEL = "full"
APPROVED_READY = "approved_ready"
NEEDS_MEMORY = "needs_memory_approval"

_TASK_STATES = {
    "waiting_approval": ("needs_approval", "docket task approve {id}"),
    "waiting_input": ("needs_answer", "docket task answer {id}"),
    "blocked": ("blocked", "docket task retry {id}"),
    "failed": ("failed", "docket task retry {id}"),
    "done": ("done", "docket task show {id}"),
    "running": ("running", "docket task show {id}"),
}


def _read_cursor() -> str | None:
    since = read_json(current_home().inbox_cursor_file).get("since")
    return str(since) if since else None


def _write_cursor(value: str) -> None:
    write_json(current_home().inbox_cursor_file, {"since": value})


def _approved_ready_tasks() -> list[TaskView]:
    """Pending tasks whose approval was granted: nothing is left but ``docket run``."""
    out: list[TaskView] = []
    for project in _status.pod_ids():
        for record in TaskRepository.for_pod(project).list():
            if record.approved_ready:
                out.append(task_view(project, record.model_dump(by_alias=True, mode="json")))
    return out


def _state_and_command(item: TaskView | ApprovalView, *, ready: bool = False) -> tuple[str, str]:
    """The item's state word and the one command that moves it forward."""
    if isinstance(item, ApprovalView):
        return "needs_approval", f"docket task approve {item.token}"
    if ready:
        return APPROVED_READY, f"docket run --pod {item.pod}"
    state, command = _TASK_STATES.get(item.status, (item.status, "docket task show {id}"))
    return state, command.format(id=item.id)


def _as_dict(item: TaskView | ApprovalView, *, ready: bool = False) -> dict[str, Any]:
    state, command = _state_and_command(item, ready=ready)
    row = item.model_dump(by_alias=True, mode="json")
    row.update(state=state, command=command)
    return row


def _memory_command(item: MemoryItem) -> str:
    return f"docket pod memory approve {item.id} --pod {item.pod}"


def _memory_dict(item: MemoryItem) -> dict[str, Any]:
    return {
        "kind": "memory",
        "pod": item.pod,
        "id": item.id,
        "entryKind": item.kind,
        "subject": item.subject,
        "note": item.note,
        "reason": item.reason,
        "task": item.task,
        "state": NEEDS_MEMORY,
        "command": _memory_command(item),
    }


def _escalation_command(escalation: EscalationView) -> str:
    """The one command that answers *escalation* from a terminal."""
    if escalation.kind in ("consult", "input"):
        return f"docket task answer {escalation.task}"
    return f"docket task answer {escalation.id} --option approve_once"


def _json_view(view: InboxView, ready: list[TaskView], memory: list[MemoryItem]) -> dict[str, Any]:
    body: dict[str, Any] = view.model_dump(by_alias=True, mode="json")
    for row, escalation in zip(body["escalations"], view.escalations, strict=True):
        row["command"] = _escalation_command(escalation)
    body["needsYou"] = (
        [_as_dict(i) for i in view.needs_you]
        + [_as_dict(t, ready=True) for t in ready]
        + [_memory_dict(m) for m in memory]
    )
    for key, items in (
        ("failed", view.failed),
        ("doneSince", view.done_since),
        ("running", view.running),
    ):
        body[key] = [_as_dict(i) for i in items]
    return body


def _held_action(token: str) -> str:
    try:
        return str(_approval.approval_get(token).get("action") or "")
    except _approval.ApprovalError:
        return ""


def _say(text: str) -> None:
    ui.console.print(text, markup=False)


def _block(prefix: str, text: str) -> str:
    """`prefix` before the first line; every later line aligned under the text after it."""
    return prefix + text.replace("\n", "\n" + " " * len(prefix))


def _render_memory(item: MemoryItem) -> None:
    _say(f"  memory {item.id}  pod={item.pod}  {item.kind}")
    _say(_block("    ", f"{item.subject}: {item.note}"))
    if item.reason:
        _say(_block("    why held: ", item.reason))
    _say(f"    approve: {_memory_command(item)}")
    _say(f'    refuse:  docket pod memory refuse {item.id} --pod {item.pod} --reason "<why>"')


def _render_question(item: TaskView, escalations: list[EscalationView]) -> None:
    assert item.question is not None
    escalation = question_escalation(escalations, item.pod, item.id)
    if escalation is not None:
        rendered = render_escalation(escalation, _LEVEL)
        message, options = rendered.prompt or "", rendered.options
    else:
        # A question parked before escalations were kept has no record; it reads from the task.
        stored = getattr(item.question, "options", None) or []
        recommendation = getattr(item.question, "recommendation", None)
        options = render_options(
            stored, recommendation.option_id if recommendation else None, labels=True
        )
        message = item.question.message
    _say(_block("    Q: ", message))
    if options:
        _say(f"    options: {options_line(options)}")
    _say(f"    answer: {answer_command(item.id, options)}")


def _render_item(
    item: TaskView | ApprovalView,
    *,
    ready: bool = False,
    escalations: list[EscalationView] | None = None,
) -> None:
    state, command = _state_and_command(item, ready=ready)
    if isinstance(item, ApprovalView):
        _say(f"  approval {item.token}  pod={item.pod}  role={item.role}")
        if item.action:
            _say(_block("    asks: ", item.action))
        _say(f"    approve: {command}")
        _say(f"    deny:    docket task deny {item.token}")
        return
    _say(f"  task {item.id}  pod={item.pod}  {state.replace('_', ' ')}")
    label = item.description or item.reason or ""
    if label:
        _say(_block("    ", label))
    if state == "needs_approval":
        action = _held_action(item.approval_token) if item.approval_token else ""
        if action:
            _say(_block("    asks: ", action))
        _say(f"    approve: {command}")
        _say(f"    deny:    docket task deny {item.id}")
    elif state == "needs_answer" and item.question is not None:
        _render_question(item, escalations or [])
    else:
        _say(f"    next: {command}")


def cmd_inbox(
    json_out: bool = typer.Option(False, "--json", help="Emit JSON"),
    since: str | None = typer.Option(
        None, "--since", help="Show tasks finished after this ISO time; leaves the cursor alone"
    ),
    peek: bool = typer.Option(False, "--peek", help="Read without advancing the cursor"),
) -> None:
    """List what needs you across every pod: approvals, questions, failures, finished work.

    Every item carries the exact docket command that moves it forward. A plain call advances
    a cursor so a repeat call shows only newly finished tasks; --peek and --since do not.

    Example: docket inbox --peek
    """
    view = build_inbox(now=_clock.iso(), since=since if since is not None else _read_cursor())
    if not peek and since is None and view.next:
        _write_cursor(view.next)
    ready = _approved_ready_tasks()
    memory = pending_memory()
    if json_out:
        _contract.emit_json(_json_view(view, ready, memory))
        return
    ui.header("Inbox")
    sections: list[tuple[str, list[tuple[TaskView | ApprovalView, bool]]]] = [
        (
            "Needs you",
            [(i, False) for i in view.needs_you] + [(t, True) for t in ready],
        ),
        ("Failed", [(i, False) for i in view.failed]),
        ("Done", [(i, False) for i in view.done_since]),
        ("Running", [(i, False) for i in view.running]),
    ]
    if not memory and not any(items for _, items in sections):
        ui.dim("Nothing needs you.")
        return
    for title, items in sections:
        if items or (memory and title == "Needs you"):
            ui.section(title)
            for item, is_ready in items:
                _render_item(item, ready=is_ready, escalations=view.escalations)
            if title == "Needs you":
                for entry in memory:
                    _render_memory(entry)
