"""docket approve — grant a pending HITL approval by token (T5.3 port of approve.sh).

  docket approve <token>    Grant a pending HITL approval
  docket approve            List pending approvals

``run_approve(token)`` returns the process exit code.
"""

from __future__ import annotations

import docket.config as _cfg
from docket import ui
from docket.core import approval as _ap


def _help() -> int:
    ui.header("docket approve")
    ui.console.print()
    ui.console.print("  docket approve <token>    Grant a pending HITL approval")
    ui.console.print("  docket approve            List pending approvals")
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


def run_approve(token: str | None = None) -> int:
    """Grant *token* (pending → granted), or list pending when token is omitted."""
    if not token:
        return _list()
    if token in ("-h", "--help"):
        return _help()

    try:
        _ap.approval_grant(token, channel="cli")
    except _ap.ApprovalNoop as noop:
        ui.warn(noop.message)
        return 0
    except _ap.ApprovalError as err:
        ui.error(str(err))
        return 1

    ui.success(f"Approval granted: {token}")
    ui.dim("  The waiting action may now proceed.")
    return 0
