"""docket approve — grant a pending HITL approval by token.

  docket approve <token>    Grant a pending HITL approval
  docket approve            List pending approvals

``run_approve(token, reason)`` returns the process exit code.

A grant is followed by ``core/dispatch.py``'s ``resolve_waiting_approval`` —
if *token* gated a dispatch task (``waiting_approval``, this exact token), that
task moves back to ``pending`` with the exact hop it stopped on handed to the
next dispatch run. A no-op for any other approval (or an already-resolved one).
"""

from __future__ import annotations

import getpass

import docket.config as _cfg
from docket import ui
from docket.core import approval as _ap
from docket.core import dispatch as _dispatch


def _help() -> int:
    ui.header("docket approve")
    ui.console.print()
    ui.console.print("  docket approve <token> [--reason TEXT]    Grant a pending HITL approval")
    ui.console.print(
        "  docket approve <token> --option approve_task   ...and the same call for the task"
    )
    ui.console.print("  docket approve                            List pending approvals")
    ui.console.print()
    ui.console.print(f"  Approvals are stored at: {_cfg.APPROVALS_DIR}")
    ui.console.print()
    return 0


def _list() -> int:
    ui.header("Pending Approvals")
    ui.console.print()
    if not _cfg.APPROVALS_DIR.is_dir():
        ui.dim("  No approvals directory found.")
        ui.console.print()
        return 0

    pending = _ap.list_pending()
    if not pending:
        ui.dim("  No pending approvals.")
        ui.console.print()
        return 0

    for d in pending:
        tok = d.get("token", "?")
        project = d.get("project", "?")
        role = d.get("role", "?")
        action = str(d.get("action") or "")[:60]
        created = str(d.get("created", "?"))[:19]
        ui.console.print(f"  {tok}")
        ui.console.print(f"    project={project}  role={role}  created={created}")
        ui.console.print(f"    action: {action}")
        ui.console.print()
    ui.console.print()
    return 0


def run_approve(token: str | None = None, reason: str = "", option: str = "") -> int:
    """Grant *token* (pending → granted), or list pending when token is omitted. *option*
    ``approve_task`` also grants the same call for the rest of its task."""
    if not token:
        return _list()
    if token in ("-h", "--help"):
        return _help()

    if option not in ("", "approve_once", "approve_task"):
        ui.error(f"Unknown option {option!r}: use approve_once or approve_task")
        return 1

    # Only include actor when there's a reason to record
    actor = ""
    if reason:
        try:
            actor = getpass.getuser()
        except Exception:
            actor = ""

    try:
        if option == "approve_task":
            _ap.approval_set_option(token, option)
        _ap.approval_grant(token, channel="cli", actor=actor, reason=reason)
    except _ap.ApprovalNoop as noop:
        ui.warn(noop.message)
        _dispatch.resolve_waiting_approval(token, "granted")
        return 0
    except _ap.ApprovalError as err:
        ui.error(str(err))
        return 1

    _, note = _dispatch.resolve_waiting_approval_detail(
        token, "granted", channel="cli", actor=actor
    )
    ui.success(f"Approval granted: {token}")
    if note:
        ui.warn(note)
    ui.dim("  The waiting action may now proceed.")
    return 0
