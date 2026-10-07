"""``docket inbox`` — one derived view of everything across every pod that needs a human.

Renders `core.inbox.build_inbox`'s four sections. A plain call advances a durable cursor
(`config.INBOX_CURSOR_FILE`, through `edges/store.py`) so a repeat call shows only newly-terminal
tasks; `--peek` reads without advancing it and `--since <iso>` overrides the stored cursor for
one call without touching it either.
"""

from __future__ import annotations

import datetime as _dt
import json

import typer

import docket.config as _cfg
from docket import ui
from docket.core import approval as _approval
from docket.core import inbox as _inbox
from docket.core.operator_contract import ApprovalView, TaskView
from docket.edges import store as _store


def _flag(args: list[str], name: str) -> str | None:
    """Return the value after ``--name`` (or ``--name=value``), else None."""
    for i, a in enumerate(args):
        if a == name and i + 1 < len(args):
            return args[i + 1]
        if a.startswith(name + "="):
            return a.split("=", 1)[1]
    return None


def _utc_now() -> str:
    return _dt.datetime.now(_dt.UTC).isoformat()


def _read_cursor() -> str | None:
    data = _store.read_json(_cfg.INBOX_CURSOR_FILE)
    since = data.get("since")
    return str(since) if since else None


def _write_cursor(value: str) -> None:
    _store.write_json(_cfg.INBOX_CURSOR_FILE, {"since": value})


def _render_task(view: TaskView) -> None:
    ui.console.print(f"  [{view.a2a_state}] task {view.id}  pod={view.pod}  status={view.status}")
    label = view.description or view.reason or ""
    if label:
        ui.dim(f"    {label[:120]}")
    if view.approval_token and view.status == "waiting_approval":
        _render_held_approval(view.approval_token)
        return
    question = view.question
    if question is None or view.status != "waiting_input":
        return
    ui.console.print(f"    Q: {question.message[:160]}")
    options = getattr(question, "options", None) or []
    if options:
        recommended = getattr(getattr(question, "recommendation", None), "option_id", None)
        rendered = ", ".join(
            f"{o.id} ({o.label})" + (" (recommended)" if o.id == recommended else "")
            for o in options
        )
        ui.dim(f"    options: {rendered}")
    ui.dim(f"    answer: docket chat {view.id}")


def _render_held_approval(token: str) -> None:
    """The action a task's folded approval asks about, and how to answer it."""
    try:
        record = _approval.approval_get(token)
    except _approval.ApprovalError:
        return
    action = str(record.get("action") or "")
    if action:
        ui.console.print(f"    asks: {action[:160]}")
    ui.dim(f"    approve: docket approve {token}   deny: docket deny {token}")


def _render_approval(view: ApprovalView) -> None:
    ui.console.print(
        f"  [{view.a2a_state}] approval {view.token}  pod={view.pod}  role={view.role}"
    )
    if view.action:
        ui.dim(f"    {view.action[:120]}")


def run_inbox(args: list[str]) -> int:
    """List everything that needs the operator, across every pod, plus recent context."""
    json_out = "--json" in args
    peek = "--peek" in args
    explicit_since = _flag(args, "--since")
    since = explicit_since if explicit_since is not None else _read_cursor()

    view = _inbox.build_inbox(now=_utc_now(), since=since)

    if not peek and explicit_since is None and view.next:
        _write_cursor(view.next)

    if json_out:
        print(json.dumps(view.model_dump(by_alias=True, mode="json"), indent=2))
        return 0

    ui.header("Inbox")
    ui.console.print()
    sections: list[tuple[str, list[TaskView | ApprovalView]]] = [
        ("Needs you", list(view.needs_you)),
        ("Failed", list(view.failed)),
        ("Done", list(view.done_since)),
        ("Running", list(view.running)),
    ]
    if not any(items for _, items in sections):
        ui.dim("  Nothing needs you.")
        ui.console.print()
        return 0
    for title, items in sections:
        if not items:
            continue
        ui.console.print(f"{title}:")
        for item in items:
            if isinstance(item, ApprovalView):
                _render_approval(item)
            else:
                _render_task(item)
        ui.console.print()
    return 0


def cmd_inbox(ctx: typer.Context) -> None:
    """List everything across every pod that needs you: waiting/blocked tasks and pending
    approvals, plus failed/done/running context.

    `docket inbox [--json] [--since <iso>] [--peek]`. A plain call advances a durable cursor so a
    repeat call's `Done` section only shows newly-terminal tasks; `--peek` reads without
    advancing it, and `--since <iso>` overrides the stored cursor for one call without touching
    it either. `--json` emits the same shape `docket serve`'s `GET /inbox` returns."""
    from docket.cli._inbox import run_inbox

    raise typer.Exit(run_inbox(list(ctx.args)))
