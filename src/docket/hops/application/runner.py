from __future__ import annotations

import dataclasses
import json as _json
from collections.abc import Callable

from docket.agent import ports as _rd
from docket.hops.application import driver as _dr
from docket.hops.application.compose import _compose_hop
from docket.hops.gates.post_hop import _apply_output_guardrails, _evaluate_hop_gates
from docket.hops.gates.pre_hop import (
    _gate_budget,
    _gate_pre_hop_approval,
    _hop_model,
    _refuse_failed_floor,
    _warn_unpriced_hop,
)
from docket.kernel import clock as _clock
from docket.kernel import handoff as _handoff
from docket.kernel.errors import DispatchError
from docket.kernel.handoff import HANDOFF_TOOL
from docket.kernel.home import current_home
from docket.kernel.ids import step_session_key
from docket.pipeline.domain import gates as _gates
from docket.pipeline.domain import plan as _orch
from docket.tasks.application import runs as _runs
from docket.tasks.application.actions import ParkedCall, approved_calls_for
from docket.tasks.application.record import (
    UnitContext,
    UnitOutcome,
    build_hop_result,
    claimed_worktree_dir,
    persist_hop_and_trace,
    trace_locked,
)
from docket.tasks.domain.task import HopResult
from docket.teams import fleet as _fleet
from docket.teams import model_selection as _models_policy
from docket.teams import pod as _pod
from docket.teams.settings import retries_for_role

# Only these TurnResult.failure_kind values are worth retrying — a
# transient hiccup running the turn. A non-zero exit or an unparseable/failing
# verdict is a real answer and must never be retried (retrying would risk
# masking a genuine failure as a transient one, and burns budget for nothing).
_RETRYABLE_FAILURE_KINDS: frozenset[str] = frozenset({"timeout", "daemon_error"})


def _declared_verdict(turn: _rd.TurnResult) -> str | None:
    """The verdict the turn's closing ``handoff`` call declared, if it made one."""
    call = _handoff.parse_handoff_call(turn.closing_args)
    return call.verdict if call is not None else None


def _reask_unmarked_verdict(
    ctx: UnitContext,
    role: str,
    gate: _gates.VerdictGate,
    first: _rd.TurnResult,
    call: Callable[[str], _rd.TurnResult],
) -> _rd.TurnResult:
    """A reply with no verdict (neither the ``handoff`` call's nor a marker line) is asked for
    once more on the same session, for the call; the answer is appended to the original reply and
    a call it makes is the turn's. A failed extra request leaves *first* as it was."""
    if _orch.parse_verdict(gate, first.output, _declared_verdict(first)) is not None:
        return first
    values = _orch.verdict_values(gate)
    trace_locked(
        ctx.project,
        ctx.session_id,
        role,
        "verdict_reasked",
        _json.dumps({"hop": role, "values": list(values)}),
    )
    second = call(
        f"Your reply had no verdict. Call `{HANDOFF_TOOL}` with your verdict: "
        f"{' or '.join(values)}."
    )
    if not second.ok:
        return first
    return dataclasses.replace(
        first,
        output=f"{first.output}\n{second.output}".strip(),
        cost_usd=first.cost_usd + second.cost_usd,
        usage=_sum_usage(first.usage, second.usage),
        raw=second.raw,
        closing_args=second.closing_args or first.closing_args,
    )


def _sum_usage(a: _rd.TokenUsage | None, b: _rd.TokenUsage | None) -> _rd.TokenUsage | None:
    if a is None or b is None:
        return a or b
    return _rd.TokenUsage(
        a.input_tokens + b.input_tokens,
        a.output_tokens + b.output_tokens,
        a.cached_tokens + b.cached_tokens,
        a.cache_write_tokens + b.cache_write_tokens,
    )


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

    def _call(turn_message: str) -> _rd.TurnResult:
        spawned_pid.clear()
        run_res = _run(turn_message)
        if run_id_for_pids is not None and spawned_pid:
            _runs.remove_hop_pid(run_id_for_pids, spawned_pid[-1])
        return run_res

    def _run(turn_message: str) -> _rd.TurnResult:
        if ctx.track_pid:
            # `ctx.run` is typed as the plain 5-arg `Runner` Callable (every
            # test double's exact shape); calling the concrete production
            # driver directly here (rather than through `ctx.run`) is what
            # lets it take the extra `on_spawn` kwarg type-safely.
            driver: _rd.RuntimeDriver = _dr.default_driver()
            return driver.run_turn(
                member_id,
                history_session_key,
                turn_message,
                hop_timeout,
                env,
                on_spawn=_on_spawn,
                trace_project=ctx.project,
                trace_session_key=ctx.session_id,
                trace_task_id=ctx.task_id,
                model=resolved_model,
            )
        return ctx.run(member_id, history_session_key, turn_message, hop_timeout, env)

    attempt = 1
    while True:
        run_res = _call(message)
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
    if run_res.ok and isinstance(node.gate, _gates.VerdictGate):
        run_res = _reask_unmarked_verdict(ctx, role, node.gate, run_res, _call)
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

    hop_model = _hop_model(node, member_id)
    _refuse_failed_floor(ctx.project, role, hop_model)
    budget_outcome = _gate_budget(ctx, role)
    if budget_outcome is not None:
        return budget_outcome
    _warn_unpriced_hop(ctx, role, hop_model)

    approval_outcome = _gate_pre_hop_approval(
        ctx, role, node, check_approval=check_approval, index_for_context=index_for_context
    )
    if approval_outcome is not None:
        return approval_outcome

    approved = approved_calls_for(ctx.task_id, role)
    message, env, manifest = _compose_hop(ctx, node, role, member_id, prior_snapshot, rework_hop)
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
        manifest,
    )

    early_outcome = persist_hop_and_trace(
        ctx, role, hop, run_res, hop_ok, hop_error, index_for_context
    )
    if early_outcome is not None:
        return early_outcome
    if hop_ok and approved:
        _trace_unused_approvals(ctx, role, approved)

    return _evaluate_hop_gates(
        ctx, node, role, member_id, hop, prior_snapshot, check_approval=check_approval
    )


def _trace_unused_approvals(ctx: UnitContext, role: str, approved: list[ParkedCall]) -> None:
    """Trace each call the hop was told to issue again that is still unspent after it ended ok."""
    unspent = {call.token for call in approved_calls_for(ctx.task_id, role)}
    for call in approved:
        if call.token in unspent:
            trace_locked(
                ctx.project,
                ctx.session_id,
                role,
                "approval_unused",
                _json.dumps(
                    {
                        "task": ctx.task_id,
                        "role": role,
                        "tool": call.tool,
                        "escalation": call.escalation,
                    }
                ),
            )


def when_cwd(ctx: UnitContext, prior: list[HopResult]) -> str:
    """Working tree a ``when: {changed: ...}`` predicate and a command step's own command
    both run against: the task's own worktree, falling back to the pod Lead's own codebase
    (the task runs in place, or the pod has no Implementer) and then its working directory (a
    `workdir`-kind pod has no codebase)."""
    worktree = claimed_worktree_dir(ctx.task)
    if worktree:
        return worktree
    lead_id = _pod.member_id(ctx.project, "lead")
    return str(
        _fleet.meta_get(lead_id, "codebase", "") or _fleet.meta_get(lead_id, "workDir", "") or ""
    )
