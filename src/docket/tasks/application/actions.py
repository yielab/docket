from __future__ import annotations

import datetime as _dt
import json as _json
from typing import Any

from docket.governance import approval as _ap
from docket.governance import approval_pregrant as _approval_pregrant
from docket.governance import audit as _audit
from docket.kernel import clock as _clock
from docket.kernel.home import current_home
from docket.observability import trace as _trace
from docket.platform import read_modify_write
from docket.tasks.application import corrections as _corrections
from docket.tasks.application import transitions as _transitions
from docket.tasks.application.record import _UnitContext
from docket.tasks.domain import state as _state
from docket.teams import agent_memory as _mem
from docket.teams import pod as _pod
from docket.teams.settings import _pod_settings, pod_task_list_path

TASK_GRANT_CAP = 20


def resolve_waiting_approval(
    token: str, decision: str, *, channel: str = "", actor: str = "", reason: str = ""
) -> bool:
    """:func:`resolve_waiting_approval_detail`'s boolean."""
    return resolve_waiting_approval_detail(
        token, decision, channel=channel, actor=actor, reason=reason
    )[0]


def resolve_waiting_approval_detail(
    token: str, decision: str, *, channel: str = "", actor: str = "", reason: str = ""
) -> tuple[bool, str]:
    """React to a just-applied approval decision by mutating the dispatch task it gated, if
    any -- never mutates the approval record itself, only reacts to a transition
    ``governance/approval.py`` already made. See pod-dispatch.spec.md ("require_approval gate and
    waiting_approval") for the pre-hop gate's grant (-> ``pending`` + gate override) and deny
    (-> ``failed``, ``failureKind: "approval_denied"``) outcomes.

    A **parked** in-turn call (ADR 0016 SS2, ``context["parked"] is True``) carries no
    ``taskId`` -- ``governance/gate.py``'s ``_park`` has no task to name -- so its task is
    found by matching ``approvalToken`` directly instead; a grant appends
    ``{token, tool, argsDigest}`` to the task's ``pregrants`` for ``_compose_hop`` to carry
    into the re-run, and does **not** set ``gateOverridePipelineIndex`` (that field is for
    skipping a pre-hop gate, not for re-running an already-attempted hop -- the resumed hop
    re-runs by ``_replay_pipeline_position``'s own ``hop.parked`` handling instead). A plain
    in-turn ``wait``-mode ask also carries no ``taskId`` (its wait blocks the calling thread
    directly, so there is no task-level state to update here) and is unaffected: not parked
    and no ``taskId`` still no-ops, exactly as before.

    A parked grant whose record chose ``approve_task`` also appends the exact
    ``(tool, argsDigest)`` to the task's ``taskGrants`` (at most ``TASK_GRANT_CAP``);
    ``_compose_hop`` mints a single-use pre-grant from each for every later hop.

    A deny carries the operator's *reason* into the task's ``reason`` as
    ``approval denied: <reason>`` so the inbox and ``task show`` say why; without one the
    text is ``approval denied``.

    Returns ``(updated, note)``: ``False`` as a harmless no-op for an unrelated/already-resolved
    token or a mismatched task; *note* is non-empty only when a task-wide grant was refused."""
    try:
        rec = _ap.approval_get(token)
    except _ap.ApprovalError:
        return False, ""
    context = rec.get("context")
    context = context if isinstance(context, dict) else {}
    parked = bool(context.get("parked"))
    check_changed = context.get("kind") == "check_changed"
    task_id = str(context.get("taskId", ""))
    project = str(rec.get("project", ""))
    if decision == "denied" and reason and project and project != "operator":
        # The denial reason joins the corrections ledger under the task the gate named (dispatch
        # stores it in the record's context); an approval no task carries is keyed empty.
        _corrections.record(
            project,
            "deny_reason",
            task_id=str(rec.get("taskId") or task_id),
            role=str(rec.get("role", "")) or "operator",
            text=reason,
            source=channel or "unknown",
        )
    if not project or (not task_id and not parked):
        return False, ""

    updated = False
    note = ""
    resolved_task_id = task_id

    def _fn(doc: dict[str, Any]) -> dict[str, Any] | None:
        nonlocal updated, resolved_task_id, note
        tasks_raw = doc.get("tasks")
        tasks = tasks_raw if isinstance(tasks_raw, list) else []
        for t in tasks:
            if task_id:
                if t.get("id") != task_id:
                    continue
            elif t.get("approvalToken") != token:
                continue
            if t.get("status") != "waiting_approval" or t.get("approvalToken") != token:
                return None
            resolved_task_id = str(t.get("id", ""))
            pending_index = t.get("pendingApprovalIndex")
            if decision == "granted" and check_changed:
                _transitions.apply_to_task(
                    t, _state.Status.done, now=_clock.iso(), reason="check_changed approved"
                )
            elif decision == "granted":
                _transitions.apply_to_task(t, _state.Status.pending)
                if parked:
                    pregrants_raw = t.get("pregrants")
                    pregrants = list(pregrants_raw) if isinstance(pregrants_raw, list) else []
                    pregrants.append(
                        {
                            "token": token,
                            "tool": str(context.get("tool", "")),
                            "argsDigest": str(context.get("argsDigest", "")),
                        }
                    )
                    t["pregrants"] = pregrants
                    if context.get("optionId") == "approve_task":
                        note = _append_task_grant(
                            t, token, context, str(rec.get("role", "")), channel, actor
                        )
                else:
                    t["gateOverridePipelineIndex"] = pending_index
            else:
                _transitions.apply_to_task(
                    t,
                    _state.Status.failed,
                    now=_clock.iso(),
                    reason=f"approval denied: {reason}" if reason else "approval denied",
                    failure_kind=(
                        _state.FailureKind.check_changed
                        if check_changed
                        else _state.FailureKind.approval_denied
                    ),
                )
            updated = True
            return {"tasks": tasks}
        return None

    doc = read_modify_write(pod_task_list_path(project), _fn)
    if updated:
        _trace.trace_event(
            project,
            f"agent:{project}:{resolved_task_id}",
            "lead",
            "approval_resumed" if decision == "granted" else "approval_task_denied",
            _json.dumps({"task": resolved_task_id, "token": token}),
        )
    if updated and check_changed:
        tasks_after = doc.get("tasks")
        _mem.sync_dispatch_tasks(
            current_home().workspace_dir(_pod.member_id(project, "lead")),
            tasks_after if isinstance(tasks_after, list) else [],
        )
    return updated, note


def _append_task_grant(
    task: dict[str, Any],
    token: str,
    context: dict[str, Any],
    role: str,
    channel: str,
    actor: str,
) -> str:
    """Record the ``approve_task`` grant for *role* on *task* unless it is already there or the
    task is at ``TASK_GRANT_CAP``; returns a refusal note, ``""`` otherwise."""
    tool = str(context.get("tool", ""))
    digest = str(context.get("argsDigest", ""))
    if not tool or not digest or not role:
        return ""
    raw = task.get("taskGrants")
    grants = [g for g in raw if isinstance(g, dict)] if isinstance(raw, list) else []
    if any(
        g.get("tool") == tool and g.get("argsDigest") == digest and g.get("role") == role
        for g in grants
    ):
        return ""
    channel = channel if channel in _ap.APPROVAL_CHANNELS else "unknown"
    if len(grants) >= TASK_GRANT_CAP:
        _audit.audit_log(
            "approval.task_grant_refused",
            f"token={token} tool={tool} cap={TASK_GRANT_CAP} channel={channel}",
        )
        return (
            f"This task already has {TASK_GRANT_CAP} task-wide grants; this call was approved "
            "once only."
        )
    grants.append(
        {
            "tool": tool,
            "argsDigest": digest,
            "role": role,
            "token": token,
            "grantedAt": _clock.iso(),
            "actor": actor,
            "channel": channel,
        }
    )
    task["taskGrants"] = grants
    _audit.audit_log(
        "approval.task_grant",
        f"token={token} tool={tool} channel={channel} actor={actor or '?'}",
    )
    return ""


def _mint_task_grant_pregrants(ctx: _UnitContext, role: str) -> list[dict[str, str]]:
    """One fresh single-use pre-grant per task-wide grant made for *role*, bound to this project
    and role: a grant never reaches a hop of another role."""
    raw = ctx.task.get("taskGrants")
    if not isinstance(raw, list) or not raw:
        return []
    deadline = _clock.now() + _dt.timedelta(hours=_pod_settings(ctx.project).approval_expiry_hours)
    minted: list[dict[str, str]] = []
    for grant in raw[:TASK_GRANT_CAP]:
        if not isinstance(grant, dict) or grant.get("role") != role:
            continue
        tool = str(grant.get("tool", ""))
        digest = str(grant.get("argsDigest", ""))
        channel = str(grant.get("channel", ""))
        try:
            pre = _approval_pregrant.create_pregrant(
                ctx.project,
                role,
                tool,
                digest,
                task_id=ctx.task_id,
                expires_at=deadline.isoformat(),
                channel=channel if channel in _ap.APPROVAL_CHANNELS else "cli",
                actor=str(grant.get("actor") or "approve_task"),
            )
        except _ap.ApprovalError:
            continue
        minted.append({"token": pre, "tool": tool, "argsDigest": digest})
    return minted
