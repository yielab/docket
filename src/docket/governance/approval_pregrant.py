"""Single-use pre-grants, and the grants a person has already given a task, read from the records.

A pre-grant is an approval record born ``granted`` for one exact tool call. A parked call's grant
is the same record after the person granted it. Either lets the identical call pass once without
asking again, and ``approve_task`` extends that to every later hop of the task for the same role
(``task_grants``). Nothing is kept on the task: ``granted_calls`` reads the approval store.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from docket.governance.approval import (
    APPROVAL_CHANNELS,
    ApprovalError,
    _approval_path,
    list_records,
)
from docket.governance.audit import audit_log
from docket.kernel import clock as _clock
from docket.kernel import ids as _ids
from docket.kernel.home import current_home
from docket.platform import read_modify_write, write_json

# The context ``source`` of a pre-grant minted from a task-wide grant: the grant stays the source
# of truth, so a minted copy is never read as a grant of its own.
MINTED = "task_grant"
APPROVE_TASK = "approve_task"
TASK_GRANT_CAP = 20


@dataclass(frozen=True)
class GrantedCall:
    """One exact tool call a person approved for a task: the granted record behind it."""

    token: str
    project: str
    role: str
    tool: str
    args_digest: str
    option: str
    channel: str
    actor: str
    created: str
    consumed: bool

    @property
    def task_wide(self) -> bool:
        return self.option == APPROVE_TASK


def granted_calls(task_id: str) -> list[GrantedCall]:
    """The calls approved for *task_id* that a hop may still be asked to pass: pre-grants made
    ahead of the task and parked calls a person granted, oldest first. A pre-grant minted from a
    task-wide grant is not one of them."""
    found: list[GrantedCall] = []
    for data in list_records():
        context = data.get("context")
        context = context if isinstance(context, dict) else {}
        if (
            data.get("state") != "granted"
            or context.get("taskId") != task_id
            or context.get("source") == MINTED
            or not (context.get("kind") == "pregrant" or context.get("parked"))
            or not context.get("tool")
            or not context.get("argsDigest")
        ):
            continue
        found.append(
            GrantedCall(
                token=str(data.get("token", "")),
                project=str(data.get("project", "")),
                role=str(data.get("role", "")),
                tool=str(context["tool"]),
                args_digest=str(context["argsDigest"]),
                option=str(context.get("optionId", "")),
                channel=str(data.get("grantedVia", "")),
                actor=str(data.get("grantedBy", "")),
                created=str(data.get("created", "")),
                consumed=bool(data.get("consumedAt")),
            )
        )
    return sorted(found, key=lambda call: (call.created, call.token))


def pending_pregrants(task_id: str) -> list[GrantedCall]:
    """The calls of *task_id* that can still be passed: granted and not spent."""
    return [call for call in granted_calls(task_id) if not call.consumed]


def task_grants(task_id: str) -> list[GrantedCall]:
    """The ``approve_task`` grants of *task_id*, one per ``(tool, argsDigest, role)``, at most
    ``TASK_GRANT_CAP``: the same call is approved for the rest of the task for that role."""
    seen: set[tuple[str, str, str]] = set()
    grants: list[GrantedCall] = []
    for call in granted_calls(task_id):
        key = (call.tool, call.args_digest, call.role)
        if call.task_wide and key not in seen and len(grants) < TASK_GRANT_CAP:
            seen.add(key)
            grants.append(call)
    return grants


def revoke_task_grants(task_id: str) -> int:
    """End the task-wide grants of *task_id* (it reached a terminal status): each record keeps
    being a spent or unspent single approval, and stops being a grant for later hops. How many."""
    revoked = 0
    for call in granted_calls(task_id):
        if not call.task_wide:
            continue
        path = _approval_path(call.token)

        def _revoke(data: dict[str, Any]) -> dict[str, Any] | None:
            context = data.get("context")
            if not isinstance(context, dict) or context.get("optionId") != APPROVE_TASK:
                return None
            data["context"] = {**context, "optionId": "approve_once"}
            return data

        read_modify_write(path, _revoke)
        revoked += 1
    return revoked


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
    source: str = "",
) -> str:
    """Persist a single-use pre-grant, already ``granted``, for one exact tool call a
    human approved ahead of the turn that will make it -- unlike ``approval_create``,
    this record is born resolved. ``consume_pregrant`` is the only way it is ever spent.
    *source* names what minted it when it is not a person's own pre-grant."""
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
    if source:
        context["source"] = source

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
