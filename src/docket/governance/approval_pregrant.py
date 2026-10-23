from __future__ import annotations

import os
from typing import Any

from docket.governance.approval import APPROVAL_CHANNELS, ApprovalError, _approval_path
from docket.governance.audit import audit_log
from docket.kernel import clock as _clock
from docket.kernel import ids as _ids
from docket.kernel.home import current_home
from docket.platform import read_modify_write, write_json


def create_pregrant(
    project: str,
    role: str,
    tool: str,
    args_digest: str,
    *,
    task_id: str | None = None,
    expires_at: str | None = None,
    channel: str,
    actor: str = "",
) -> str:
    """Persist a single-use pre-grant, already ``granted``, for one exact tool call a
    human approved ahead of the turn that will make it -- unlike ``approval_create``,
    this record is born resolved. ``consume_pregrant`` is the only way it is ever spent."""
    if not project or not role or not tool or not args_digest:
        raise ApprovalError("create_pregrant: missing arguments")
    if channel not in APPROVAL_CHANNELS:
        raise ApprovalError(f"create_pregrant: unknown channel {channel!r}")

    current_home().approvals_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(current_home().approvals_dir, 0o700)

    token = _ids.new_id("apr")
    created = _clock.stamp()
    context: dict[str, Any] = {"kind": "pregrant", "tool": tool, "argsDigest": args_digest}
    if task_id:
        context["taskId"] = task_id

    data: dict[str, Any] = {
        "token": token,
        "project": project,
        "role": role,
        "action": f"pre-grant: {tool} (argsDigest={args_digest})",
        "state": "granted",
        "created": created,
        "context": context,
    }
    if expires_at:
        data["expiresAt"] = expires_at
    write_json(_approval_path(token), data)

    audit_log(
        "approval.pregrant",
        f"token={token} project={project} tool={tool} channel={channel} actor={actor or '?'}",
    )
    return token


def consume_pregrant(token: str) -> bool:
    """Spend one single-use pre-grant. Returns ``True`` only once, for a record still
    ``granted`` and not past its own ``expiresAt``; a second call, or one past expiry,
    is a safe ``False`` no-op. Atomic, so a concurrent caller can never spend it twice."""
    if not token:
        return False
    try:
        path = _approval_path(token)
    except ApprovalError:
        return False  # a token of the wrong form never names a pre-grant
    consumed = False

    def transition(data: dict[str, Any]) -> dict[str, Any] | None:
        nonlocal consumed
        if not path.is_file():
            return None
        if data.get("state") != "granted" or data.get("consumedAt"):
            return None
        expires_at = data.get("expiresAt")
        if expires_at:
            deadline = _clock.parse_epoch(str(expires_at))
            if deadline is not None and _clock.epoch() > deadline:
                return None
        data["consumedAt"] = _clock.stamp()
        consumed = True
        return data

    data = read_modify_write(path, transition)
    if consumed:
        tool = str((data.get("context") or {}).get("tool", ""))
        audit_log("approval.consume", f"token={token} tool={tool}")
    return consumed
