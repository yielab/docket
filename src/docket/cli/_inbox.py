"""The inbox command: everything across every pod that needs a human.

A plain call advances a durable cursor so a repeat call shows only newly finished tasks;
--peek reads without advancing it and --since overrides the stored cursor for one call.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any

import typer

import docket.config as _cfg
from docket import ui
from docket.cli import _contract, _status
from docket.core import approval as _approval
from docket.core import dispatch as _dispatch
from docket.core import inbox as _inbox
from docket.core.operator_contract import ApprovalView, InboxView, TaskView
from docket.edges import store as _store

APPROVED_READY = "approved_ready"

_TASK_STATES = {
    "waiting_approval": ("needs_approval", "docket task approve {id}"),
    "waiting_input": ("needs_answer", "docket task answer {id}"),
    "blocked": ("blocked", "docket task retry {id}"),
    "failed": ("failed", "docket task retry {id}"),
    "done": ("done", "docket task show {id}"),
    "running": ("running", "docket task show {id}"),
}


def _utc_now() -> str:
    return _dt.datetime.now(_dt.UTC).isoformat()


def _read_cursor() -> str | None:
    since = _store.read_json(_cfg.INBOX_CURSOR_FILE).get("since")
    return str(since) if since else None


def _write_cursor(value: str) -> None:
    _store.write_json(_cfg.INBOX_CURSOR_FILE, {"since": value})


def _approved_ready_tasks() -> list[TaskView]:
    """Pending tasks whose approval was granted: nothing is left but ``docket run``."""
    out: list[TaskView] = []
    for project in _status.pod_ids():
        for task in _dispatch.read_tasks(project):
            if task.get("status") == "pending" and (
                task.get("pregrants") or task.get("gateOverridePipelineIndex") is not None
            ):
                out.append(_inbox.task_view(project, task))
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


def _json_view(view: InboxView, ready: list[TaskView]) -> dict[str, Any]:
    body: dict[str, Any] = view.model_dump(by_alias=True, mode="json")
    body["needsYou"] = [_as_dict(i) for i in view.needs_you] + [
        _as_dict(t, ready=True) for t in ready
    ]
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


def _render_item(item: TaskView | ApprovalView, *, ready: bool = False) -> None:
    state, command = _state_and_command(item, ready=ready)
    if isinstance(item, ApprovalView):
        _say(f"  approval {item.token}  pod={item.pod}  role={item.role}")
        if item.action:
            _say(f"    asks: {item.action}")
        _say(f"    approve: {command}")
        _say(f"    deny:    docket task deny {item.token}")
        return
    _say(f"  task {item.id}  pod={item.pod}  {state.replace('_', ' ')}")
    label = item.description or item.reason or ""
    if label:
        _say(f"    {label}")
    if state == "needs_approval":
        action = _held_action(item.approval_token) if item.approval_token else ""
        if action:
            _say(f"    asks: {action}")
        _say(f"    approve: {command}")
        _say(f"    deny:    docket task deny {item.id}")
    elif state == "needs_answer" and item.question is not None:
        _say(f"    Q: {item.question.message}")
        options = getattr(item.question, "options", None) or []
        if options:
            rec = getattr(getattr(item.question, "recommendation", None), "option_id", None)
            rendered = ", ".join(
                f"{o.id} ({o.label})" + (" (recommended)" if o.id == rec else "") for o in options
            )
            _say(f"    options: {rendered}")
        _say(f"    answer: {command}")
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
    view = _inbox.build_inbox(now=_utc_now(), since=since if since is not None else _read_cursor())
    if not peek and since is None and view.next:
        _write_cursor(view.next)
    ready = _approved_ready_tasks()
    if json_out:
        _contract.emit_json(_json_view(view, ready))
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
    if not any(items for _, items in sections):
        ui.dim("Nothing needs you.")
        return
    for title, items in sections:
        if items:
            ui.section(title)
            for item, is_ready in items:
                _render_item(item, ready=is_ready)
