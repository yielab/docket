from __future__ import annotations

import json as _json
from pathlib import Path
from typing import Any

from docket.agent import ports as _rd
from docket.governance import approval as _ap
from docket.governance import audit as _audit
from docket.governance import policy as _policy
from docket.governance import profile as _profile
from docket.governance import secrets as _secrets
from docket.hops.application.record import _trace_locked, _UnitContext, _UnitOutcome
from docket.hops.workspace import protected_paths as _protected
from docket.hops.workspace.worktree import _task_worktree_dir
from docket.kernel.home import current_home
from docket.models import selection as _models_policy
from docket.operator import contract as _oc
from docket.pipeline.domain import gates as _gates
from docket.pipeline.domain import plan as _orch
from docket.tasks.application.queue import pod_full_roster, read_tasks
from docket.tasks.domain.task import DispatchError, TaskResult
from docket.teams import fleet as _fleet
from docket.teams import pod as _pod
from docket.teams import pod_settings as _teams_pod_settings
from docket.teams import utils as _utils
from docket.teams.settings import _pod_settings, pod_recorded_cost


def pod_gating_cost(project: str) -> tuple[float, bool]:
    """The pod's spend for budget-**gating**: recorded, or a token x pricing-table estimate
    (the driver always reports ``cost_usd = 0.0``). Returns ``(amount, estimated)`` -- never
    present the estimate as, or mix it into, recorded spend. See cost-tracking.spec.md."""
    recorded = pod_recorded_cost(project)
    if recorded > 0.0:
        return recorded, False

    all_ids = [a.id for a in _fleet.list_agents()]
    total_est = 0.0
    any_estimate = False
    for mid, _role, _idx in _pod.members_of(all_ids, project):
        # recorded == 0.0 above, so every member's own recorded spend is 0.0 too --
        # this always resolves through teams/utils.py::gating_cost's estimate branch.
        est, estimated = _utils.gating_cost(mid)
        if estimated:
            total_est += est
            any_estimate = True
    return round(total_est, 6), any_estimate


def _pause_lead_for_budget(project: str) -> None:
    """Mark the pod's Lead paused once budget is reached, so ``_claim_next_task`` refuses
    every further claim (one write here, not a per-hop recheck) until an operator clears it
    (``docket run --resume``). Idempotent."""
    lead_id = _pod.member_id(project, "lead")
    _fleet.meta_set(lead_id, "paused", True)
    _fleet.meta_set(lead_id, "pausedReason", "budget")


def _pipeline_step_requires_approval(gate: _gates.Gate | None) -> bool:
    """The pipeline-defined ``approval`` step source: *gate* is the current position's
    resolved gate; an ``ApprovalGate`` requires a human decision."""
    return isinstance(gate, _gates.ApprovalGate)


def _approval_action_text(role: str, task: dict[str, Any]) -> str:
    """Human-readable description recorded on the approval record; ``governance/approval.py``
    redacts it before persisting, so this need not scrub secrets itself.
    """
    desc = str(task.get("description", "")).strip()
    task_id = str(task.get("id", "task"))
    return f"pod dispatch — {role} hop for task {task_id}: {desc}"[:1000]


def _hop_network(pod_mode: str, task_mode: str | None) -> str:
    """The hop's jail network: ``"none"`` when the pod or the task says so, else ``"open"``.
    A task can only cut the network, never open one the pod closed."""
    return "none" if "none" in (pod_mode, task_mode) else "open"


def _task_token_budget(task: dict[str, Any]) -> int | None:
    """What *task*'s ``maxTokens`` has left after its persisted hops' counted usage (input minus
    cache reads, plus output); ``None`` without a cap. Zero or less means no hop may start."""
    cap = task.get("maxTokens")
    if not isinstance(cap, int) or isinstance(cap, bool):
        return None
    used = 0
    for hop in task.get("hops") or []:
        usage = hop.get("usage") if isinstance(hop, dict) else None
        if isinstance(usage, dict):
            fresh = int(usage.get("input") or 0) - int(usage.get("cached") or 0)
            used += max(0, fresh) + int(usage.get("output") or 0)
    return cap - used


def _current_task(ctx: _UnitContext) -> dict[str, Any]:
    """The task as the queue holds it now (hops persisted so far), else the claimed snapshot."""
    for entry in read_tasks(ctx.project):
        if entry.get("id") == ctx.task_id:
            return entry
    return ctx.task


def _gate_task_tokens(ctx: _UnitContext, role: str) -> _UnitOutcome | None:
    """Fail the task with ``failureKind: "budget"`` when its ``maxTokens`` is spent before *role*."""
    left = _task_token_budget(_current_task(ctx))
    if left is None or left > 0:
        return None
    return _UnitOutcome(
        kind="failed",
        reason=f"task token budget reached (maxTokens={ctx.task.get('maxTokens')}) before {role}",
        failure_kind="budget",
    )


def _apply_task_restrictions(
    ctx: _UnitContext, env: dict[str, str] | None
) -> dict[str, str] | None:
    """*env* plus the driver coordinates for the task's restrictions and remaining token budget.
    A policy document that is invalid or not ``block`` refuses the hop (``DispatchError``)."""
    extra: dict[str, str] = {}
    restrictions = ctx.task.get("restrictions")
    if isinstance(restrictions, dict):
        if restrictions.get("deniedTools"):
            extra[_rd.DOCKET_TASK_DENIED_TOOLS] = _json.dumps(list(restrictions["deniedTools"]))
        task_mode = restrictions.get("network")
        if task_mode == "none":
            extra[_rd.DOCKET_TASK_NETWORK] = _hop_network(
                _teams_pod_settings.effective_network(ctx.project)[0], task_mode
            )
        if restrictions.get("policies"):
            try:
                documents = [_policy.task_policy_document(d) for d in restrictions["policies"]]
            except ValueError as exc:
                raise DispatchError(f"task restrictions refused: {exc}") from exc
            extra[_rd.DOCKET_TASK_POLICIES] = _json.dumps(documents)
    left = _task_token_budget(_current_task(ctx))
    if left is not None:
        extra[_rd.DOCKET_TURN_TOKEN_BUDGET] = str(left)
    return {**(env or {}), **extra} if extra else env


def _gate_budget(ctx: _UnitContext, role: str) -> _UnitOutcome | None:
    """Budget gate before the hop (see ``pod_gating_cost``); on trip, marks the Lead paused
    so future dispatch attempts are refused at claim time instead of re-running this check.
    Returns ``None`` when the hop may proceed."""
    task_outcome = _gate_task_tokens(ctx, role)
    if task_outcome is not None:
        return task_outcome
    if ctx.cap <= 0.0:
        return None
    spent, estimated = pod_gating_cost(ctx.project)
    if spent < ctx.cap:
        return None
    spent_label = f"~${spent:.2f} (estimated — no cost recorded)" if estimated else f"${spent:.2f}"
    _trace_locked(
        ctx.project,
        ctx.session_id,
        role,
        "budget_exceeded",
        _json.dumps(
            {
                "spent": round(spent, 6),
                "cap": round(ctx.cap, 6),
                "role": role,
                "estimated": estimated,
            }
        ),
    )
    return _UnitOutcome(
        kind="blocked",
        reason=f"pod budget reached ({spent_label} ≥ ${ctx.cap:.2f}) before {role}",
    )


def _hop_model(node: _orch.PlannedUnit, member_id: str) -> str:
    """The model this hop runs: the step's own ``model`` (resolved), else the member's."""
    if node.model:
        try:
            return _models_policy.resolve_step_model(node.model)
        except ValueError:
            return node.model
    return str(_fleet.meta_get(member_id, "model", "") or current_home().default_model)


def _unpriced(model: str) -> bool:
    """A model the budget estimate cannot price; a local provider costs nothing, so never."""
    provider = model.split("/", 1)[0]
    return (
        not _models_policy.is_local_provider(provider) and _models_policy.price_for(model) is None
    )


def _warn_unpriced_hop(ctx: _UnitContext, role: str, model: str) -> None:
    """Under a budget, an unpriced model adds nothing to the estimate, so the cap cannot stop
    this hop's spend: trace a ``budget_warning`` and let the hop run (cost-tracking.spec.md)."""
    if ctx.cap <= 0.0 or not _unpriced(model):
        return
    reason = f"pod budget ${ctx.cap:.2f} cannot stop this hop: {model} has no price"
    _trace_locked(
        ctx.project,
        ctx.session_id,
        role,
        "budget_warning",
        _json.dumps({"action": "unpriced_model", "status": "unenforced", "reason": reason}),
    )


def _gate_pre_hop_approval(
    ctx: _UnitContext,
    role: str,
    node: _orch.PlannedUnit,
    *,
    check_approval: bool,
    index_for_context: int,
) -> _UnitOutcome | None:
    """require_approval gate: after budget (affordability), before the hop (permission).
    Mutates ``ctx.override_index``, consuming a granted approval's single-use override the
    first time a run reaches its minted position, so a later hop revisiting that position
    (a rework cycle) still gates normally. Returns ``None`` when the hop may proceed."""
    if not check_approval:
        return None
    if index_for_context == ctx.override_index:
        ctx.override_index = None
        return None
    if not _pipeline_step_requires_approval(node.gate):
        return None
    action = _approval_action_text(role, ctx.task)
    token = _ap.approval_create(
        ctx.project,
        role,
        action,
        context={"taskId": ctx.task_id, "pipelineIndex": index_for_context},
    )
    _trace_locked(
        ctx.project,
        ctx.session_id,
        role,
        "approval_required",
        _json.dumps({"role": role, "token": token, "pipelineIndex": index_for_context}),
    )
    return _UnitOutcome(
        kind="waiting_approval",
        reason=f"approval required before {role} hop (token={token})",
        approval_token=token,
        pending_approval_index=index_for_context,
    )


def _consult_budget_env(ctx: _UnitContext, env: dict[str, str] | None) -> dict[str, str] | None:
    """Once the task has parked consultations, this hop's cap is what the task has left
    (``maxConsultationsPerTask`` minus them); before that the pod setting applies as is."""
    used = ctx.task.get("consultations")
    if not isinstance(used, int) or used <= 0:
        return env
    remaining = max(0, _pod_settings(ctx.project).max_consultations_per_task - used)
    return {**(env or {}), _rd.DOCKET_MAX_CONSULTATIONS: str(remaining)}


def _check_brief_resources(project: str, brief: _oc.TaskBrief) -> list[str]:
    """The subset of *brief*'s own ``resources`` entries a deterministic check cannot
    confirm (unconfigured secret, missing path, no ``verifyCmd``); ``[]`` means every
    one named is present. Pure, no side effects."""
    missing: list[str] = []
    configured_secrets: set[str] | None = None
    for item in brief.resources:
        if item.startswith("secret:"):
            if configured_secrets is None:
                configured_secrets = _secrets.secrets_keys()
            if item[len("secret:") :] not in configured_secrets:
                missing.append(item)
        elif item.startswith("path:"):
            if not Path(item[len("path:") :]).exists():
                missing.append(item)
        elif item == "verify":
            implementer_id = pod_full_roster(project).get("implementer")
            verify_cmd = (
                str(_fleet.meta_get(implementer_id, "verifyCmd", "") or "")
                if implementer_id
                else ""
            )
            if not verify_cmd:
                missing.append(item)
    return missing


def _block_on_missing_resources(
    ctx: _UnitContext, outcome: _UnitOutcome, result: TaskResult
) -> bool:
    """A ``READY`` outcome whose brief names something ``_check_brief_resources`` finds
    missing blocks *result* and returns ``True``; the caller's own ``break`` stops the
    pipeline. A brief with nothing missing, or no brief, returns ``False`` unchanged."""
    if outcome.label.upper() != "READY" or not outcome.hops:
        return False
    brief = outcome.hops[-1].artifact.brief if outcome.hops[-1].artifact else None
    if brief is None:
        return False
    missing = _check_brief_resources(ctx.project, brief)
    if not missing:
        return False
    result.status = "blocked"
    result.blocked_reason = "resources"
    result.reason = "brief names missing resources: " + ", ".join(missing)
    return True


def _refuse_unmet_profile(
    project: str, task_id: str, runtime_steps: tuple[_orch.PlannedNode, ...]
) -> None:
    """Under the ``lights-out`` profile, refuse the task before its first hop when a requirement
    is unmet: audit ``profile.refused`` and raise ``DispatchError`` naming each fix."""
    violations = _profile.project_violations(project, runtime_steps)
    if not violations:
        return
    _audit.audit_log(
        "profile.refused",
        f"pod={project} task={task_id} requirements={','.join(v.requirement for v in violations)}",
    )
    lines = "; ".join(f"{v.requirement}: {v.detail} ({v.fix})" for v in violations)
    raise DispatchError(f"lights-out profile not met -- {lines}")


def _checked_commands(
    project: str, task: dict[str, Any], runtime_steps: tuple[_orch.PlannedNode, ...]
) -> list[str]:
    """The commands this task runs as checks: the Implementer's ``verifyCmd``, every mechanical or
    external gate command and ``run:`` step of the pipeline, and the task's own gate command."""
    implementer = pod_full_roster(project).get("implementer")
    commands = [str(_fleet.meta_get(implementer, "verifyCmd", "") or "")] if implementer else []
    for node in runtime_steps:
        for unit in node.children if isinstance(node, _orch.PlannedGroup) else (node,):
            commands.append(unit.run or "")
            if isinstance(unit.gate, (_gates.MechanicalGate, _gates.ExternalGate)):
                commands.append(unit.gate.command or "")
    raw_gate = task.get("gate")
    if isinstance(raw_gate, dict):
        commands.append(str(raw_gate.get("command") or ""))
    return [c for c in commands if c]


def _park_if_check_changed(
    ctx: _UnitContext, runtime_steps: tuple[_orch.PlannedNode, ...], result: TaskResult
) -> None:
    """A finished task whose diff touches a protected path (hops/workspace/protected_paths.py) parks
    ``waiting_approval`` for a person whatever the profile, instead of ending ``done``. A task
    with no recorded worktree is not checked."""
    record = ctx.task.get("worktree")
    directory = _task_worktree_dir(ctx.task)
    branch = str(record.get("branch") or "") if isinstance(record, dict) else ""
    base = str(record.get("baseCommit") or "") if isinstance(record, dict) else ""
    if not (directory and branch and base):
        return
    paths = _protected.changed_protected(
        directory,
        base,
        branch,
        _pod_settings(ctx.project).protects,
        _checked_commands(ctx.project, ctx.task, runtime_steps),
    )
    if not paths:
        return
    listed = ", ".join(paths[: _protected.MAX_LISTED_PATHS])
    if len(paths) > _protected.MAX_LISTED_PATHS:
        listed += f" and {len(paths) - _protected.MAX_LISTED_PATHS} more"
    token = _ap.approval_create(
        ctx.project,
        "lead",
        f"pod dispatch -- task {ctx.task_id} edits what checks it: {listed}",
        context={"kind": "check_changed", "taskId": ctx.task_id, "paths": paths},
    )
    _trace_locked(
        ctx.project,
        ctx.session_id,
        "lead",
        "approval_required",
        _json.dumps({"role": "lead", "token": token, "kind": "check_changed", "paths": paths}),
    )
    result.status = "waiting_approval"
    result.reason = f"the change edits what checks it: {listed} (token={token})"
    result.approval_token = token
    result.pending_approval_index = None
    result.check_changed = paths
