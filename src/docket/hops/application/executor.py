from __future__ import annotations

import fnmatch as _fnmatch
import json as _json
import time as _time
from collections.abc import Callable
from typing import Any, Literal

from docket.hops.application import driver as _dr
from docket.hops.application import resolutions as _resolutions
from docket.hops.application.runner import execute_unit, when_cwd
from docket.hops.application.steps import (
    _run_command_step,
    _run_input_step,
    _task_gate,
    _task_gate_step_id,
    _task_pipeline,
    effective_pipeline,
)
from docket.hops.gates.post_hop import (
    _external_failure_kind,
    _latest_implementer_evidence,
    _match_on_route,
)
from docket.hops.gates.pre_hop import (
    _block_on_missing_resources,
    _park_if_check_changed,
    _pause_lead_for_budget,
    _refuse_unmet_profile,
)
from docket.kernel.errors import DispatchError
from docket.kernel.ports import git as _git
from docket.observability import trace as _trace
from docket.pipeline.domain import plan as _orch
from docket.pipeline.domain import spec as _pipeline
from docket.tasks.application.record import (
    Runner,
    UnitContext,
    UnitOutcome,
    is_gate_failure_carryover,
    replay_pipeline_position,
    trace_locked,
)
from docket.tasks.application.repository import TaskRepository
from docket.tasks.domain.task import HopResult, TaskRecord, TaskResult, TaskRunRefusal
from docket.teams import autonomy as _autonomy
from docket.teams import roles as _archetypes
from docket.teams.pod import pod_full_roster, pod_pipeline
from docket.teams.settings import (
    pod_budget,
    pod_turn_timeout,
    pod_verify_timeout,
    resolve_timeout,
)


def _refuse_input_for_level(project: str, task: TaskRecord, spec: _pipeline.PipelineSpec) -> None:
    """A task whose level has nobody to ask (the table's ``input`` row is not ``person``) may not run
    a pipeline with an ``input`` step: raise ``TaskRunRefusal`` naming the step and the way out."""
    level = _autonomy.effective_level(project, task.autonomy)
    if _autonomy.policy_for("input", level)[0] == "person":
        return
    message = _pipeline.input_refusal(spec, level)
    if message is not None:
        raise TaskRunRefusal(message)


def _resolve_task_run(
    project: str,
    task: TaskRecord,
    default_spec: _pipeline.PipelineSpec,
    default_vars: dict[str, Any],
    variables: dict[str, Any] | None,
    default_source: str = "default",
) -> tuple[_pipeline.PipelineSpec, dict[str, Any], str]:
    """Resolve a claimed task's pipeline, variables and gate, or raise ``TaskRunRefusal``."""
    spec, source = _task_pipeline(project, task, default_spec, default_source)
    _task_gate(task)
    _refuse_input_for_level(project, task, spec)
    if spec is default_spec and not task.variables:
        return spec, default_vars, source
    # The task's own variables win over the run's.
    merged = {**(variables or {}), **task.variables}
    label = f"pipeline {task.pipeline!r}" if task.pipeline else "pipeline"
    try:
        resolved = _pipeline.resolve_variables(spec, merged)
    except _pipeline.VariableError as exc:
        raise TaskRunRefusal(f"{label}: {exc}") from exc
    missing = _pipeline.unresolved_step_variables(spec, resolved)
    if missing:
        raise TaskRunRefusal(f"{label}: unresolved variable(s): {', '.join(missing)}")
    return spec, resolved, source


def _record_task_run(
    project: str, task: TaskRecord, source: str, spec: _pipeline.PipelineSpec
) -> None:
    """Record ``pipelineSource`` and ``gateApplied`` on the claimed task and its stored record,
    and, for a caller's file, the spec itself as ``pipelineSpec`` so an answer and a later claim
    replay it."""
    task.pipeline_source = source
    task.gate_applied = task.gate is not None
    if source == "file":
        task.pipeline_spec = spec.model_dump(mode="json", by_alias=True)

    def _fn(stored: TaskRecord) -> None:
        stored.pipeline_source = task.pipeline_source
        stored.gate_applied = task.gate_applied
        stored.pipeline_spec = task.pipeline_spec

    TaskRepository.for_pod(project).update(task.id, _fn)


def _run_group_node(
    ctx: UnitContext,
    node: _orch.PlannedGroup,
    prior: list[HopResult],
    index_for_context: int,
) -> UnitOutcome:
    """Run a parallel group's children concurrently; join before advancing. Merge priority:
    cancelled > blocked > failed > advance (rework is impossible here -- the pipeline
    format's validator forbids a rework edge inside a ``parallel`` group)."""
    prior_snapshot = list(prior)
    child_outcomes = _orch.run_group(
        node.children,
        lambda child: execute_unit(
            ctx,
            child,
            prior_snapshot=prior_snapshot,
            rework_hop=None,
            check_approval=False,
            index_for_context=index_for_context,
        ),
    )
    merged = UnitOutcome(kind="advance")
    for oc in child_outcomes:
        merged.hops.extend(oc.hops)
    for oc in child_outcomes:
        if oc.kind == "cancelled":
            merged.kind, merged.reason = "cancelled", oc.reason
            break
    else:
        for oc in child_outcomes:
            if oc.kind == "blocked":
                merged.kind, merged.reason = "blocked", oc.reason
                break
        else:
            for oc in child_outcomes:
                if oc.kind == "failed":
                    merged.kind, merged.reason = "failed", oc.reason
                    merged.failure_kind = oc.failure_kind
                    break
    return merged


def resolve_pipeline_steps(
    project: str, spec: _pipeline.PipelineSpec | None
) -> tuple[tuple[_orch.PlannedNode, ...], dict[str, int], dict[str, str]]:
    """Resolve *spec* (or this pod's default pipeline) against the pod's live roster into
    this run's ordered, runnable steps. Assumes the caller already validated the pod/Lead
    exist; this only builds the plan, it does not itself raise for a missing pod."""
    # The third element is each step id's own declared `instructions` text,
    # not yet interpolated -- see `_pipeline.step_instructions_by_id`.
    effective_spec = effective_pipeline(project, spec)
    registry = _archetypes.load_registry(project)
    roster = pod_full_roster(project)
    plan = _orch.resolve_plan(effective_spec, roster, registry=registry)
    runtime_steps = plan.runnable_nodes()
    id_to_index = {node.step_id: i for i, node in enumerate(runtime_steps)}
    raw_step_instructions = _pipeline.step_instructions_by_id(effective_spec)
    return runtime_steps, id_to_index, raw_step_instructions


def _resolve_resume_state(
    runtime_steps: tuple[_orch.PlannedNode, ...], resume_from: list[HopResult] | None
) -> tuple[list[HopResult], int, dict[str, int], dict[tuple[str, str], int], dict[int, HopResult]]:
    """Compute the pipeline position (and rework state) a run should continue from.
    *resume_from* seeds hops already completed before a crash, which can legitimately
    include the same step more than once mid-rework -- see ``replay_pipeline_position``."""
    prior: list[HopResult] = list(resume_from) if resume_from else []
    # A step can now legitimately run more than once (a rework cycle re-runs
    # its gate's declared target, then re-runs the gating step), so "where do
    # we continue" is a pipeline position + per-gate rework counts, not a set
    # of already-seen role names — see `replay_pipeline_position`'s
    # docstring for why this matters for a task resumed mid-rework.
    resume_pos = replay_pipeline_position(runtime_steps, prior)
    pending_rework_by_index: dict[int, HopResult] = {}
    if resume_pos.rework_hop is not None:
        pending_rework_by_index[resume_pos.pipeline_index] = resume_pos.rework_hop
    return (
        prior,
        resume_pos.pipeline_index,
        dict(resume_pos.rework_counts),
        dict(resume_pos.route_counts),
        pending_rework_by_index,
    )


def _step_skipped(ctx: UnitContext, node: _orch.PlannedUnit, prior: list[HopResult]) -> bool:
    """Evaluate *node*'s ``when`` (every set predicate ANDed); a false predicate emits
    ``step_skipped`` so the caller advances with no hop. See pod-dispatch.spec.md
    ("Conditional steps and command steps")."""
    when = node.when
    if not when:
        return False
    matched = True
    if "changed" in when:
        cwd = when_cwd(ctx, prior)
        changed_files = _git.git_changed_files(cwd) if cwd else []
        evidence = _latest_implementer_evidence(prior)
        base, head = evidence.get("baseCommit"), evidence.get("commit")
        if cwd and base and head:
            changed_files += _git.git_diff_names(cwd, str(base), str(head))
        pattern = str(when["changed"])
        matched = matched and any(_fnmatch.fnmatch(path, pattern) for path in changed_files)
    if "var" in when:
        actual = ctx.variables.get(str(when["var"]))
        matched = matched and actual is not None and str(actual) == str(when.get("is", ""))
    if "memberPresent" in when:
        matched = matched and str(when["memberPresent"]) in pod_full_roster(ctx.project)
    if matched:
        return False
    trace_locked(
        ctx.project,
        ctx.session_id,
        node.step_id,
        "step_skipped",
        _json.dumps({"step": node.step_id, "when": when}),
    )
    return True


def _route_outcome(
    ctx: UnitContext,
    node: _orch.PlannedUnit,
    outcome: UnitOutcome,
    pipeline_index: int,
) -> tuple[int | None, str]:
    """Resolve a ``"routed"`` outcome's target (``fail``/``stop``/a step id, bounded by
    ``max`` when backward) into a next index (``None`` for ``stop``, negative for a
    terminal failure) and reason; traces one ``route_taken`` event either way."""
    route = _match_on_route(node.on, outcome.label)
    label_upper = outcome.label.upper()
    if isinstance(route, dict):
        target: Any = route.get("goto")
        max_cycles = route.get("max")
    else:
        target = route
        max_cycles = None
    target_str = target if isinstance(target, str) else "stop"
    trace_role = node.role or node.agent or node.step_id

    def _trace_route(resolved_target: str) -> None:
        trace_locked(
            ctx.project,
            ctx.session_id,
            trace_role,
            "route_taken",
            _json.dumps(
                {"step": node.step_id, "outcome": outcome.label, "target": resolved_target}
            ),
        )

    if outcome.hops:
        outcome.hops[0].next_step = target_str

    if target_str == "fail":
        _trace_route("fail")
        return -1, f"step {node.step_id!r} outcome {label_upper} routed to fail"
    if target_str == "stop":
        _trace_route("stop")
        return None, f"step {node.step_id!r} outcome {label_upper} routed to stop"

    target_index = ctx.id_to_index.get(target_str)
    if target_index is None:
        _trace_route(target_str)
        return -1, f"step {node.step_id!r}: 'on' target {target_str!r} is not a known step id"

    if target_index <= pipeline_index:
        key = (node.step_id, outcome.label)
        cycles_so_far = ctx.route_counts.get(key, 0)
        cap = max_cycles if isinstance(max_cycles, int) else 1
        if cycles_so_far >= cap:
            _trace_route(target_str)
            return -1, (
                f"step {node.step_id!r} outcome {label_upper} exhausted its routing budget "
                f"({cycles_so_far} of {cap}) toward {target_str!r}"
            )
        ctx.route_counts[key] = cycles_so_far + 1

    _trace_route(target_str)
    return target_index, f"step {node.step_id!r} outcome {label_upper} routed to {target_str!r}"


# A routed-to-fail outcome sets no failure kind today (an ordinary graded gate/hop
# failure) -- the one named exception is the intake pipeline's own REJECT marker, which
# maps to the A2A REJECTED state via `operator_contract.a2a_state`. One constant, so the
# mapping is never hand-built twice (ADR 0016 §4).
_ROUTE_FAILURE_KINDS: dict[str, str] = {"REJECT": "rejected"}


def _run_pipeline(
    ctx: UnitContext,
    runtime_steps: tuple[_orch.PlannedNode, ...],
    pipeline_index: int,
    pending_rework_by_index: dict[int, HopResult],
    result: TaskResult,
    prior: list[HopResult],
) -> None:
    """Advance one task through its resolved pipeline until a terminal outcome. Mutates
    *result*/*prior* in place per step (each hop is also observed via *on_hop* -- see
    ``persist_hop_and_trace``). The only backward moves are a bounded rework cycle and a
    step's own ``on:`` route, each jumping to a declared target. A ``READY`` verdict
    carrying a Lead intake brief (ADR 0016 §4) is checked against
    ``_check_brief_resources`` before the pipeline is allowed past it."""
    while pipeline_index < len(runtime_steps):
        node = runtime_steps[pipeline_index]

        if isinstance(node, _orch.PlannedGroup):
            outcome = _run_group_node(ctx, node, prior, pipeline_index)
        elif _step_skipped(ctx, node, prior):
            pipeline_index += 1
            continue
        elif node.run is not None:
            outcome = _run_command_step(ctx, node, prior, pipeline_index)
        elif node.input is not None:
            outcome = _run_input_step(ctx, node, prior, pipeline_index)
        else:
            rework_hop = pending_rework_by_index.pop(pipeline_index, None)
            outcome = execute_unit(
                ctx,
                node,
                prior_snapshot=prior,
                rework_hop=rework_hop,
                check_approval=True,
                index_for_context=pipeline_index,
            )

        result.hops.extend(outcome.hops)
        prior.extend(outcome.hops)

        if outcome.kind == "blocked":
            result.status = "blocked"
            result.reason = outcome.reason
            _pause_lead_for_budget(ctx.project)
            break
        if outcome.kind == "waiting_approval":
            result.status = "waiting_approval"
            result.reason = outcome.reason
            result.pending_approval_index = outcome.pending_approval_index
            break
        if outcome.kind == "waiting_input":
            result.status = "waiting_input"
            result.reason = outcome.reason
            break
        if outcome.kind == "failed":
            result.status = "failed"
            result.reason = outcome.reason
            if outcome.failure_kind:
                result.failure_kind = outcome.failure_kind
            break
        if outcome.kind == "cancelled":
            result.status = "cancelled"
            result.reason = outcome.reason
            break
        if outcome.kind == "rework":
            assert outcome.rework_target_index is not None
            pending_rework_by_index[outcome.rework_target_index] = outcome.hops[0]
            pipeline_index = outcome.rework_target_index
            continue
        if outcome.kind == "routed":
            assert isinstance(node, _orch.PlannedUnit)
            next_index, reason = _route_outcome(ctx, node, outcome, pipeline_index)
            if next_index is None:
                result.status = "done"
                result.reason = reason
                break
            if next_index < 0:
                result.status = "failed"
                result.reason = reason
                result.failure_kind = _ROUTE_FAILURE_KINDS.get(
                    outcome.label.upper(), ""
                ) or _external_failure_kind(outcome)
                break
            if _block_on_missing_resources(ctx, outcome, result):
                break
            if next_index <= pipeline_index and is_gate_failure_carryover(outcome.hops[0]):
                # A backward route out of a mechanical gate: the target's next hop is told
                # why the gate failed (see `_gate_failed_section`).
                pending_rework_by_index[next_index] = outcome.hops[0]
            pipeline_index = next_index
            continue
        if outcome.kind == "advance" and _block_on_missing_resources(ctx, outcome, result):
            break
        pipeline_index += 1


def dispatch_task(
    project: str,
    task: TaskRecord,
    *,
    runner: Runner | None = None,
    turn_timeout: int | None = None,
    verify_timeout: int | None = None,
    resume_from: list[HopResult] | None = None,
    on_hop: Callable[[HopResult], None] | None = None,
    on_retry: Callable[[], None] | None = None,
    sleep: Callable[[float], None] | None = None,
    spec: _pipeline.PipelineSpec | None = None,
    variables: dict[str, Any] | None = None,
    approval_default: Literal["wait", "park"] = "wait",
    approval_timeout: int | None = None,
) -> TaskResult:
    """Drive one task through the pod pipeline, hop by hop. Full contract: pod-dispatch.spec.md
    ("Pipeline order and participation", "Per-hop incremental persistence and crash recovery",
    "Deterministic refusal inside a claimed task", "Retries and the failure-kind taxonomy",
    "Generalized gate execution", "Parallel step groups"). Budget is checked before each hop; a
    failed hop stops the pipeline except for a bounded rework loop re-running a verdict gate's
    declared target up to its own cycle budget. *spec* ``None`` resolves the pod's
    zero-migration pipeline; *resume_from* seeds hops completed before a crash or a settled
    refusal (skipped, not re-invoked) -- including a hop that parked mid-turn, replayed by its
    own exact index (ADR 0016 SS2, see ``replay_pipeline_position``); *turn_timeout*/
    *verify_timeout* override the pod Lead's meta then ``DEFAULT_TIMEOUT``, unless a step
    declares its own. *on_retry* fires before each retry so the caller can refresh the task's
    claim before it goes stale. *variables* is this run's already-resolved pipeline variable
    namespace (``dispatch_pod`` validates and resolves it before calling here) -- used only to
    interpolate any step's own ``instructions`` text (pipeline-format.spec.md); a direct caller
    that skips ``dispatch_pod`` gets no unresolved-reference refusal, only best-effort
    interpolation. *approval_default* is this call's own resolution for an *unset* pod
    ``approvalMode`` (``pod_approval_mode``); an explicit pod value always wins over it.
    The pipeline position a granted pre-hop approval stopped at is read from the task's resolved
    gate escalation (``apply_resolutions``): the approval at that position is skipped once.

    A ``DispatchError`` raised anywhere on this claimed task's path (the membership check near
    the top of ``execute_unit``, or this function's own up-front ``pod_pipeline`` revalidation)
    is caught here and folded into a ``"failed"`` result tagged ``failure_kind="dispatch_refused"``
    instead of propagating -- the caller (``dispatch_pod``) always finalizes and settles the
    claim, and a crash (any *other* exception) still propagates unchanged, leaving the task
    ``running`` for the stale-claim sweep exactly as before."""
    run = runner or _dr.default_driver().run_turn
    # pid tracking (for `docket task cancel`) only makes sense for a real
    # OS process, i.e. the production driver — never an injected test
    # runner/fake, none of which accept an `on_spawn` kwarg (and none of which
    # have a process to report anyway). Gating on `runner is None` (rather
    # than duck-typing) keeps every existing 5-arg-Callable test double
    # working completely unchanged.
    track_pid = runner is None
    do_sleep = sleep or _time.sleep
    task_id = task.id
    session_id = f"agent:{project}:{task_id}"

    _dr.start_export()
    _trace.trace_event(
        project,
        session_id,
        "lead",
        "session_start",
        _json.dumps({"source": "dispatch", "task": task_id, "resumed": bool(resume_from)}),
    )

    result = TaskResult(task_id=task_id, status="done", hops=list(resume_from or []))
    try:
        pod_pipeline(project)  # validates pod/lead up front (raises DispatchError otherwise)
        cap = pod_budget(project)
        resolved_turn_timeout = resolve_timeout(turn_timeout, pod_turn_timeout(project))
        resolved_verify_timeout = resolve_timeout(verify_timeout, pod_verify_timeout(project))

        task_gate = _task_gate(task)
        runtime_steps, id_to_index, raw_step_instructions = resolve_pipeline_steps(project, spec)
        # What a person answered while the task waited is applied here, at the claim, and not by
        # the answering call: the resume position below reads the hops it may add.
        applied = _resolutions.apply_resolutions(
            project, task, list(resume_from or []), runtime_steps, id_to_index
        )
        resume_from = applied.hops
        if applied.ended is not None:
            status, reason = applied.ended
            _trace.trace_event(
                project, session_id, "lead", "session_end", _json.dumps({"status": status})
            )
            return TaskResult(task_id=task_id, status=status, reason=reason, hops=applied.hops)
        resolved_vars: dict[str, Any] = variables or {}
        step_instructions = {
            sid: _pipeline.interpolate_instructions(text, resolved_vars)
            for sid, text in raw_step_instructions.items()
        }
        prior, pipeline_index, rework_counts, route_counts, pending_rework_by_index = (
            _resolve_resume_state(runtime_steps, resume_from)
        )

        # The pipeline position a granted approval stopped at is handed to this one claim:
        # consumed the first time this run reaches that position, so a later hop at the same
        # position (a rework cycle revisiting it) still gates normally.
        ctx = UnitContext(
            project=project,
            task=task,
            task_id=task_id,
            session_id=session_id,
            cap=cap,
            resolved_turn_timeout=resolved_turn_timeout,
            resolved_verify_timeout=resolved_verify_timeout,
            id_to_index=id_to_index,
            rework_counts=rework_counts,
            override_index=applied.gate_override_index,
            track_pid=track_pid,
            run=run,
            do_sleep=do_sleep,
            on_hop=on_hop,
            on_retry=on_retry,
            step_instructions=step_instructions,
            variables={k: str(v) for k, v in resolved_vars.items()},
            route_counts=route_counts,
            approval_default=approval_default,
            approval_timeout=approval_timeout,
            task_gate=task_gate,
            task_gate_step_id=_task_gate_step_id(runtime_steps) if task_gate else None,
        )
        if task_gate and ctx.task_gate_step_id is None:
            raise DispatchError("the task gate has no step that runs an agent turn to follow")

        result = TaskResult(task_id=task_id, status="done", hops=list(prior))

        _refuse_unmet_profile(project, task_id, runtime_steps)
        _run_pipeline(ctx, runtime_steps, pipeline_index, pending_rework_by_index, result, prior)
        if result.status == "done":
            _park_if_check_changed(ctx, runtime_steps, result)
    except DispatchError as exc:
        result.status = "failed"
        result.reason = str(exc)
        result.failure_kind = "dispatch_refused"
        _trace.trace_event(
            project, session_id, "lead", "dispatch_refused", _json.dumps({"reason": str(exc)})
        )

    _trace.trace_event(
        project,
        session_id,
        "lead",
        "session_end",
        _json.dumps({"status": result.status}),
    )
    return result
