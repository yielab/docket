from __future__ import annotations

import dataclasses
import json as _json
from collections.abc import Callable

from docket.agent import ports as _rd
from docket.agent import session as _session
from docket.hops.application import driver as _dr
from docket.hops.application.compose import _compose_hop
from docket.hops.domain.budget import resolve_seconds
from docket.hops.domain.continuation import continuation_message
from docket.hops.gates.post_hop import _apply_output_guardrails, _evaluate_hop_gates
from docket.hops.gates.pre_hop import (
    _gate_budget,
    _gate_pre_hop_approval,
    _refuse_failed_floor,
    hop_model,
)
from docket.kernel import clock as _clock
from docket.kernel import handoff as _handoff
from docket.kernel.errors import DispatchError
from docket.kernel.handoff import HANDOFF_TOOL
from docket.kernel.ids import step_session_key
from docket.pipeline.domain import gates as _gates
from docket.pipeline.domain import plan as _orch
from docket.platform import git as _git
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
        usage=_sum_usage(first.usage, second.usage),
        request_retries=first.request_retries + second.request_retries,
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


_CONTINUED_PATHS = 20


def _summary_of(hop: HopResult) -> str:
    return hop.artifact.summary if hop.artifact is not None else hop.output


def _continuation_text(
    ctx: UnitContext,
    prior: list[HopResult],
    error: str,
    summary: str,
    pinned: tuple[str, ...] = (),
) -> str:
    """The continuation message for a step's next turn: the stop's *error* and *summary* and the
    paths changed in the step's working tree, after the *pinned* paths the failed hop already
    committed (``hops/domain/continuation.py``)."""
    cwd = when_cwd(ctx, prior)
    dirty = _git.git_changed_files(cwd, all_untracked=True) if cwd else []
    changed = [*pinned, *(p for p in dirty if p not in pinned)]
    return continuation_message(error, summary, changed[:_CONTINUED_PATHS])


def _failed_hop_to_continue(
    prior: list[HopResult], node: _orch.PlannedUnit, session_key: str
) -> HopResult | None:
    """The step's latest hop when it failed (not parked) and its session already holds rounds:
    the turn that runs now continues that session instead of starting over."""
    mine = [h for h in prior if (h.step_id or h.role) == node.step_id]
    if not mine or mine[-1].ok or mine[-1].parked:
        return None
    return mine[-1] if _session.load_messages(session_key) else None


def _run_hop_turn(
    ctx: UnitContext,
    node: _orch.PlannedUnit,
    role: str,
    member_id: str,
    history_session_key: str,
    message: str,
    env: dict[str, str] | None,
    prior: list[HopResult],
) -> tuple[_rd.TurnResult, int]:
    """Run this hop's agent turn once; the loop retries a failed model request inside it, up to the
    count sent as ``DOCKET_HOP_REQUEST_RETRIES`` -- see pod-dispatch.spec.md ("Retries and the
    failure-kind taxonomy"). Returns the turn and ``1 + request_retries``. A step's own
    ``retries``/``timeout`` override wins over the pod's role-based budget and turn timeout.
    A step's own ``model`` (pipeline-format.spec.md "Steps" Req. 10) is resolved once per call
    and passed to the production driver only, for this hop alone -- see "Per-hop execution".
    A re-run over persisted rounds sends a continuation, not *message* (requirement 6 there)."""
    retry_budget = node.retries if node.retries is not None else retries_for_role(role)
    budget_time = resolve_seconds(
        step=node.timeout, pod=ctx.declared_turn_timeout, default=ctx.resolved_turn_timeout
    )
    hop_timeout = budget_time.value
    env = {
        **(env or {}),
        _rd.DOCKET_HOP_TIMEOUT_SOURCE: budget_time.source,
        _rd.DOCKET_HOP_REQUEST_RETRIES: str(retry_budget),
    }
    resolved_model: str | None = None
    if node.model:
        try:
            resolved_model = _models_policy.resolve_step_model(node.model)
        except ValueError as exc:
            raise DispatchError(f"step {node.step_id!r}: {exc}") from exc

    def _run(turn_message: str) -> _rd.TurnResult:
        if ctx.track_pid:
            # `ctx.run` is typed as the plain 5-arg `Runner` Callable (every
            # test double's exact shape); calling the concrete production
            # driver directly here (rather than through `ctx.run`) is what
            # lets it take the trace and model kwargs type-safely.
            driver: _rd.RuntimeDriver = _dr.default_driver()
            return driver.run_turn(
                member_id,
                history_session_key,
                turn_message,
                hop_timeout,
                env,
                trace_project=ctx.project,
                trace_session_key=ctx.session_id,
                trace_task_id=ctx.task_id,
                model=resolved_model,
            )
        return ctx.run(member_id, history_session_key, turn_message, hop_timeout, env)

    failed_hop = _failed_hop_to_continue(prior, node, history_session_key)
    if failed_hop is not None:
        pinned = tuple(failed_hop.artifact.files_changed) if failed_hop.artifact else ()
        message = _continuation_text(ctx, prior, failed_hop.error, _summary_of(failed_hop), pinned)
    run_res = _run(message)
    if run_res.ok and isinstance(node.gate, _gates.VerdictGate):
        run_res = _reask_unmarked_verdict(ctx, role, node.gate, run_res, _run)
    return run_res, 1 + run_res.request_retries


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

    planned_model = hop_model(node, member_id)
    _refuse_failed_floor(ctx.project, role, planned_model)
    budget_outcome = _gate_budget(ctx, role)
    if budget_outcome is not None:
        return budget_outcome

    approval_outcome = _gate_pre_hop_approval(
        ctx, role, node, check_approval=check_approval, index_for_context=index_for_context
    )
    if approval_outcome is not None:
        return approval_outcome

    approved = approved_calls_for(ctx.task_id, role)
    message, env, composed = _compose_hop(ctx, node, role, member_id, prior_snapshot, rework_hop)
    hop_first_ts = _clock.stamp()
    run_res, attempt = _run_hop_turn(
        ctx, node, role, member_id, history_session_key, message, env, prior_snapshot
    )

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
        composed.manifest,
        started_at=composed.started_at,
        cycle=composed.cycle,
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
