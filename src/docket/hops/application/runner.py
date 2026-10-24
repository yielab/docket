from __future__ import annotations

import json as _json

from docket.agent import ports as _rd
from docket.hops.application import driver as _dr
from docket.hops.application.compose import _compose_hop
from docket.hops.gates.post_hop import _apply_output_guardrails, _evaluate_hop_gates
from docket.hops.gates.pre_hop import (
    _gate_budget,
    _gate_pre_hop_approval,
    _hop_model,
    _warn_unpriced_hop,
)
from docket.kernel import clock as _clock
from docket.kernel.errors import DispatchError
from docket.kernel.home import current_home
from docket.kernel.ids import step_session_key
from docket.pipeline.domain import plan as _orch
from docket.tasks.application import runs as _runs
from docket.tasks.application.record import (
    UnitContext,
    UnitOutcome,
    build_hop_result,
    persist_hop_and_trace,
    trace_locked,
)
from docket.tasks.domain.task import HopResult
from docket.teams import fleet as _fleet
from docket.teams import model_selection as _models_policy
from docket.teams import pod as _pod
from docket.teams.settings import retries_for_role
from docket.teams.workspace.worktree import task_worktree_dir

# Only these TurnResult.failure_kind values are worth retrying — a
# transient hiccup running the turn. A non-zero exit or an unparseable/failing
# verdict is a real answer and must never be retried (retrying would risk
# masking a genuine failure as a transient one, and burns budget for nothing).
_RETRYABLE_FAILURE_KINDS: frozenset[str] = frozenset({"timeout", "daemon_error"})


def _run_hop_turn(
    ctx: UnitContext,
    node: _orch.PlannedUnit,
    role: str,
    member_id: str,
    history_session_key: str,
    message: str,
    env: dict[str, str] | None,
) -> tuple[_rd.TurnResult, int]:
    """Run this hop's agent turn, retrying only a retryable failure in place (a non-zero
    exit or bad verdict is a real answer and stops here) -- see pod-dispatch.spec.md
    ("Retries and the failure-kind taxonomy"). Returns the total tries made. A step's own
    ``retries``/``timeout`` override wins over the pod's role-based budget and turn timeout.
    A step's own ``model`` (pipeline-format.spec.md "Steps" Req. 10) is resolved once per call
    and passed to the production driver only, for this hop alone -- see "Per-hop execution"."""
    retry_budget = node.retries if node.retries is not None else retries_for_role(role)
    hop_timeout = node.timeout if node.timeout is not None else ctx.resolved_turn_timeout
    resolved_model: str | None = None
    if node.model:
        try:
            resolved_model = _models_policy.resolve_step_model(node.model)
        except ValueError as exc:
            raise DispatchError(f"step {node.step_id!r}: {exc}") from exc

    # Record the production driver's spawned pid as in-flight for
    # `docket task cancel` — only while the subprocess is actually
    # running; removed again the moment this attempt returns, so a long
    # multi-hop task never accumulates stale pids from finished hops.
    run_id_for_pids = _runs.current_run_id() if ctx.track_pid else None
    spawned_pid: list[int] = []

    def _on_spawn(pid: int) -> None:
        spawned_pid.append(pid)
        if run_id_for_pids is not None:
            _runs.add_hop_pid(run_id_for_pids, pid)

    attempt = 1
    while True:
        spawned_pid.clear()
        if ctx.track_pid:
            # `ctx.run` is typed as the plain 5-arg `Runner` Callable (every
            # test double's exact shape); calling the concrete production
            # driver directly here (rather than through `ctx.run`) is what
            # lets it take the extra `on_spawn` kwarg type-safely.
            driver: _rd.RuntimeDriver = _dr.default_driver()
            run_res = driver.run_turn(
                member_id,
                history_session_key,
                message,
                hop_timeout,
                env,
                on_spawn=_on_spawn,
                trace_project=ctx.project,
                trace_session_key=ctx.session_id,
                trace_task_id=ctx.task_id,
                model=resolved_model,
            )
        else:
            run_res = ctx.run(member_id, history_session_key, message, hop_timeout, env)
        if run_id_for_pids is not None and spawned_pid:
            _runs.remove_hop_pid(run_id_for_pids, spawned_pid[-1])
        if run_res.ok or run_res.failure_kind not in _RETRYABLE_FAILURE_KINDS:
            break
        if attempt > retry_budget:
            break
        trace_locked(
            ctx.project,
            ctx.session_id,
            role,
            "hop_retry",
            _json.dumps(
                {
                    "hop": role,
                    "attempt": attempt,
                    "retry_budget": retry_budget,
                    "failure_kind": run_res.failure_kind,
                    "error": run_res.error,
                    "retry_after_s": run_res.retry_after_s,
                }
            ),
        )
        # A retry means the dispatcher is alive and making forward progress,
        # not crashed — refresh the claim before the backoff sleep so a
        # concurrent dispatcher's stale-claim sweep never mistakes it for one
        # (see the module docstring / _touch_claim).
        if ctx.on_retry is not None:
            ctx.on_retry()
        # The endpoint's own Retry-After (when it named one) can push the wait
        # past the linear backoff; either way it is capped so one large value
        # never stalls a hop indefinitely (pod-dispatch.spec.md, "Retries and
        # the failure-kind taxonomy" requirement 3).
        ctx.do_sleep(
            min(
                max(
                    current_home().dispatch_retry_backoff_s * attempt, run_res.retry_after_s or 0.0
                ),
                current_home().dispatch_retry_max_wait_s,
            )
        )
        attempt += 1
    return run_res, attempt


def execute_unit(
    ctx: UnitContext,
    node: _orch.PlannedUnit,
    *,
    prior_snapshot: list[HopResult],
    rework_hop: HopResult | None,
    check_approval: bool,
    index_for_context: int,
) -> UnitOutcome:
    """Run one PlannedUnit's hop end to end: budget/approval gates, the agent turn (with
    retries), and its post-hop gate. Shared by a top-level step and a group's children --
    *check_approval* is False for a child, since an ``approval`` gate inside a fan-out is a
    configuration error, not a mid-group wait. See pod-dispatch.spec.md ("Parallel step groups")."""
    role = node.role or node.agent or node.step_id
    member_id = node.member_id
    assert member_id is not None  # runnable_nodes() already filtered out skipped units
    history_session_key = step_session_key(member_id, ctx.project, ctx.task_id, node.step_id)

    if _pod.pod_of(member_id) != ctx.project:
        raise DispatchError(
            f"refusing cross-pod dispatch: '{member_id}' is not in pod '{ctx.project}'"
        )

    budget_outcome = _gate_budget(ctx, role)
    if budget_outcome is not None:
        return budget_outcome
    _warn_unpriced_hop(ctx, role, _hop_model(node, member_id))

    approval_outcome = _gate_pre_hop_approval(
        ctx, role, node, check_approval=check_approval, index_for_context=index_for_context
    )
    if approval_outcome is not None:
        return approval_outcome

    message, env = _compose_hop(ctx, node, role, member_id, prior_snapshot, rework_hop)
    hop_first_ts = _clock.stamp()
    run_res, attempt = _run_hop_turn(ctx, node, role, member_id, history_session_key, message, env)

    hop_output, hop_ok, hop_error = _apply_output_guardrails(ctx, role, run_res)

    hop = build_hop_result(
        ctx,
        node,
        role,
        member_id,
        run_res,
        hop_output,
        hop_ok,
        hop_error,
        attempt,
        hop_first_ts,
        prior_snapshot,
    )

    early_outcome = persist_hop_and_trace(
        ctx, role, hop, run_res, hop_ok, hop_error, index_for_context
    )
    if early_outcome is not None:
        return early_outcome

    return _evaluate_hop_gates(
        ctx, node, role, member_id, hop, prior_snapshot, check_approval=check_approval
    )


def when_cwd(ctx: UnitContext, prior: list[HopResult]) -> str:
    """Working tree a ``when: {changed: ...}`` predicate and a command step's own command
    both run against: the task's own worktree, falling back to the pod Lead's own codebase
    (the task runs in place, or the pod has no Implementer)."""
    worktree = task_worktree_dir(ctx.task)
    if worktree:
        return worktree
    lead_id = _pod.member_id(ctx.project, "lead")
    return str(_fleet.meta_get(lead_id, "codebase", "") or "")
