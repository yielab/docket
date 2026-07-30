"""docket deny — deny a pending HITL approval by token (T5.3 port of deny.sh).

  docket deny <token>    Deny a pending HITL approval

``run_deny(token)`` returns the process exit code.

G-1: a deny is followed by ``core/dispatch.py``'s ``resolve_waiting_approval`` —
if *token* gated a dispatch task (``waiting_approval``, this exact token), that
task fails terminally right away (``failureKind: "approval_denied"``). A no-op
for any other approval (or an already-resolved one).
"""

from __future__ import annotations

from docket import ui
from docket.core import approval as _ap
from docket.core import dispatch as _dispatch


def _help() -> int:
    ui.header("docket deny")
    ui.console.print()
    ui.console.print("  docket deny <token>    Deny a pending HITL approval")
    ui.console.print()
    ui.console.print("  List pending: docket approve")
    ui.console.print()
    return 0


def run_deny(token: str | None = None) -> int:
    """Deny *token* (pending → denied). Empty/help token prints usage."""
    if not token or token in ("-h", "--help"):
        return _help()

    try:
        _ap.approval_deny(token, channel="cli")
    except _ap.ApprovalNoop as noop:
        ui.warn(noop.message)
        _dispatch.resolve_waiting_approval(token, "denied")
        return 0
    except _ap.ApprovalError as err:
        ui.error(str(err))
        return 1

    _dispatch.resolve_waiting_approval(token, "denied")
    ui.success(f"Approval denied: {token}")
    ui.dim("  The waiting action has been blocked.")
    return 0
