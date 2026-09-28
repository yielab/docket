"""Forecast what could pause a task before it is even dispatched, and record a single-use
pre-grant for an expected risky action ahead of time (ADR 0016 SS10).

`forecast` is a pure derivation over a pod's already-effective policies, security classifier,
pipeline gates, `requireApprovalRoles`, `approvalMode` and notifying channels. `record_pregrant`
calls `core.approval.create_pregrant` exactly as the in-turn park path does, then appends the
grant to the task's own `pregrants` list -- the same shape a live park already produces.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from typing import Any, Literal

from docket.core import approval as _approval
from docket.core import channel as _channel
from docket.core import dispatch as _dispatch
from docket.core import fleet as _fleet
from docket.core import operator_contract as _oc
from docket.core import pipeline as _pipeline
from docket.core import pod as _pod
from docket.core import policy as _policy
from docket.core import security as _security
from docket.edges import store as _store

# The kinds that can actually pause a task on a human answer -- everything else
# ("mode", "high_risk_class", "channel") is context shown alongside, not counted
# toward "nothing will ask" (see `forecast`'s docstring, item 3 in the spec).
ASK_KINDS: frozenset[str] = frozenset({"policy", "pipeline_gate", "role_gate"})

NOTHING_WILL_ASK = "Nothing in this pod will ask you."


class InterruptionsError(ValueError):
    """A pre-grant could not be recorded: the named task is not in this pod's own queue."""


@dataclass(frozen=True)
class Interruption:
    """One thing that could pause a task and wait on a human, or context about how it would
    be handled: a guardrail policy, a high-risk command class, a pipeline gate, the pod's own
    require_approval roles, its resolved approvalMode, or a channel that would notify."""

    kind: str
    description: str
    detail: str = ""


def _policy_pattern(doc: dict[str, Any]) -> str:
    match = doc.get("match")
    if isinstance(match, dict) and match.get("pattern"):
        return str(match["pattern"])
    when = doc.get("when")
    if isinstance(when, dict) and when.get("matches"):
        return str(when["matches"])
    return "(structured predicate)"


def _iter_leaf_steps(steps: list[_pipeline.Step]) -> list[_pipeline.Step]:
    """Every unit step, one level into a `parallel` group -- pipelines nest no deeper."""
    leaves: list[_pipeline.Step] = []
    for step in steps:
        if step.parallel:
            leaves.extend(step.parallel)
        else:
            leaves.append(step)
    return leaves


def _require_approval_roles(project: str) -> list[str]:
    lead_id = _pod.member_id(project, "lead")
    raw = _fleet.meta_get(lead_id, "requireApprovalRoles", "")
    return sorted({r.strip().lower() for r in raw.split(",") if r.strip()})


def _approval_expiry_hours(project: str) -> int:
    try:
        return _pod.PodSettings.load_for(project).approval_expiry_hours
    except _pod.PodSettingsError:
        return 24


def forecast(
    project: str, *, caller_default: Literal["wait", "park"] = "wait"
) -> list[Interruption]:
    """Everything in *project*'s own effective configuration that could stop a task and wait
    on a human, plus the context for how it would be handled -- no live dispatch, no guess."""
    items: list[Interruption] = []

    for path in _policy.policy_files(project):
        try:
            doc = _policy.read_policy(path)
        except Exception:
            continue
        if doc.get("hook") != "pre_tool_call" or doc.get("action") != "require_approval":
            continue
        policy_id = str(doc.get("id", path.name))
        items.append(
            Interruption(
                kind="policy",
                description=f"policy '{policy_id}' asks on: {_policy_pattern(doc)}",
                detail=policy_id,
            )
        )

    for cls in _security.HIGH_RISK_PATTERNS:
        items.append(
            Interruption(
                kind="high_risk_class",
                description=f"high-risk class '{cls.name}': {cls.description}",
                detail=cls.name,
            )
        )

    pipeline = _dispatch.effective_pipeline(project, None)
    for step in _iter_leaf_steps(pipeline.steps):
        if isinstance(step.gate, _pipeline.ApprovalGate):
            items.append(
                Interruption(
                    kind="pipeline_gate",
                    description=f"step '{step.id}' has an approval gate",
                    detail=step.id,
                )
            )
        if step.input is not None:
            items.append(
                Interruption(
                    kind="pipeline_gate",
                    description=f"step '{step.id}' asks the operator (from {step.input.from_})",
                    detail=step.id,
                )
            )

    for role in _require_approval_roles(project):
        items.append(
            Interruption(
                kind="role_gate",
                description=f"role '{role}' always asks (requireApprovalRoles)",
                detail=role,
            )
        )

    mode = _dispatch.pod_approval_mode(project, caller_default=caller_default)
    expiry_hours = _approval_expiry_hours(project)
    items.append(
        Interruption(
            kind="mode",
            description=(
                f"approvalMode resolves to '{mode}' (parked approvals expire after {expiry_hours}h)"
            ),
            detail=mode,
        )
    )

    for name, spec in sorted(_channel.load_catalog().entries.items()):
        if spec.enabled and "notify" in spec.capabilities:
            on = ", ".join(spec.on) or "nothing configured"
            items.append(
                Interruption(
                    kind="channel",
                    description=f"channel '{name}' ({spec.dialect}) will notify on: {on}",
                    detail=name,
                )
            )

    return items


def _normalized_command(command: str) -> str:
    """Collapse whitespace before digesting a command -- the ADR 0016 SS10 limit ("exact
    after whitespace normalisation"): a model that rephrases the command is asked again."""
    return " ".join(command.split())


def record_pregrant(
    project: str,
    task_id: str,
    command: str,
    *,
    tool: str = "bash",
    channel: str,
    actor: str = "",
) -> str:
    """Record a single-use pre-grant for one exact *command* on one task, ahead of dispatch --
    same shape a live park's own grant appends. Raises `InterruptionsError` when *task_id* is
    not in *project*'s own queue -- a pre-grant never crosses pods."""
    tasks = _dispatch.read_tasks(project)
    if not any(t.get("id") == task_id for t in tasks):
        raise InterruptionsError(f"Task '{task_id}' not found in pod '{project}'.")

    normalized = _normalized_command(command)
    args_digest = _oc.canonical_args_digest(tool, {"command": normalized})
    expires_at = (
        _dt.datetime.now(_dt.UTC) + _dt.timedelta(hours=_approval_expiry_hours(project))
    ).isoformat()

    token = _approval.create_pregrant(
        project,
        "implementer",
        tool,
        args_digest,
        task_id=task_id,
        expires_at=expires_at,
        channel=channel,
        actor=actor,
    )

    def _fn(doc: dict[str, Any]) -> dict[str, Any] | None:
        tasks_raw = doc.get("tasks")
        found_tasks = tasks_raw if isinstance(tasks_raw, list) else []
        for t in found_tasks:
            if t.get("id") == task_id:
                pregrants_raw = t.get("pregrants")
                pregrants = list(pregrants_raw) if isinstance(pregrants_raw, list) else []
                pregrants.append({"token": token, "tool": tool, "argsDigest": args_digest})
                t["pregrants"] = pregrants
                return {"tasks": found_tasks}
        return None

    _store.read_modify_write(_dispatch.pod_task_list_path(project), _fn)
    return token
