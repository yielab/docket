"""Pod pipeline dispatch: drives queued tasks through lead -> implementer -> reviewer,
one real agent turn per present role, with a trace event and budget check per hop. Always within
a single pod; invoked only by an explicit trigger or the opt-in ``serve --dispatch`` loop.
Behavioral contract: specs/functional/pod-dispatch.spec.md (claiming, crash recovery, retries,
timeouts, budget/auto-pause, require_approval/``waiting_approval``, verify/verdict/PASS-FAIL
gates) and specs/functional/security-gates.spec.md (``pre_input``/``pre_output``/``pre_tool_call``).
Load-bearing points not obvious from either: the concurrency guarantee of a claim is the
filelock held for the whole claim read-modify-write, never a comparison of any claim value.
``pre_input`` fires once at enqueue, not per hop, so incoming text cannot re-trip a ``"*"``-scoped
policy at every role. ``pod_gating_cost``'s token estimate is gating-only, never recorded spend
(the driver can report ``cost_usd = 0.0``).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

from docket.hops.application.executor import _record_task_run, _resolve_task_run, dispatch_task
from docket.hops.application.steps import effective_pipeline
from docket.hops.application.waits import probe_wait
from docket.kernel.errors import DispatchError
from docket.pipeline.domain import spec as _pipeline
from docket.tasks.application.escalation_sweep import sweep_waits
from docket.tasks.application.lifecycle import (
    finalize_task,
    reclaim_stale_running,
    sweep_stale_claims,
)
from docket.tasks.application.queue import (
    claim_next_task,
    prepare_claimed_task,
    refuse_claimed_task,
    touch_claim,
)
from docket.tasks.application.record import Runner, persist_hop
from docket.tasks.application.repository import TaskRepository
from docket.tasks.domain.task import HopResult, TaskResult, TaskRunRefusal
from docket.teams.pod import pod_pipeline


def _unsupplied_variables(
    spec: _pipeline.PipelineSpec, variables: dict[str, Any] | None
) -> str | None:
    """Why *spec* cannot run with *variables* alone (a required one missing, or a step's
    instructions naming one nothing resolves), or ``None`` when it can."""
    try:
        resolved = _pipeline.resolve_variables(spec, variables)
    except _pipeline.VariableError as exc:
        return str(exc)
    missing = _pipeline.unresolved_step_variables(spec, resolved)
    if missing:
        return (
            "refusing dispatch: step instructions reference unresolved pipeline "
            "variable(s): " + ", ".join(missing)
        )
    return None


def _tasks_supply_variables(project: str) -> bool:
    """Whether an unfinished task of *project* carries its own variables or names its own
    pipeline: what the caller left unresolved is then the task's to supply, at its claim."""
    return any(
        bool(r.variables or r.pipeline) and not r.is_terminal
        for r in TaskRepository.for_pod(project).list()
    )


def dispatch_pod(
    project: str,
    *,
    runner: Runner | None = None,
    turn_timeout: int | None = None,
    verify_timeout: int | None = None,
    max_tasks: int | None = None,
    resume: bool = False,
    sleep: Callable[[float], None] | None = None,
    spec: _pipeline.PipelineSpec | None = None,
    variables: dict[str, Any] | None = None,
    approval_default: Literal["wait", "park"] = "wait",
    stop: Callable[[], bool] | None = None,
) -> list[TaskResult]:
    """Dispatch a pod's pending tasks through the pipeline (highest priority first), looping
    ``dispatch_task`` over locked claims until none remain or *max_tasks* is hit --
    see ``dispatch_task`` and pod-dispatch.spec.md for the full claiming/crash-recovery/retry
    contract. A stale ``running`` claim is swept first; pass *resume* to also reclaim those
    and continue from the last persisted hop. Returns one TaskResult per task attempted.
    Raises DispatchError if the pod has no Lead, or -- checked once, here, before any task is
    claimed or any hop runs -- if *variables* (the caller-supplied pipeline variable mapping;
    e.g. the serve webhook's resolved body, or ``docket run --var``) leaves a required variable
    missing or any step's own ``instructions`` with an unresolved ``${var}`` reference, unless an
    unfinished task carries its own ``variables`` or ``pipeline``: the check then waits for each
    claim, and a task with neither is refused ``failed`` with the same reason. A ``wait`` step's parked tasks
    whose time has come or whose probe passes are woken before the first claim (pod-dispatch.spec.md
    "Wait steps"). *stop* is polled before each
    claim, never inside a task. See
    specs/functional/pipeline-format.spec.md ("Variables"). A task's own ``variables`` are merged
    over these at its claim and win. *approval_default* is this caller's
    own resolution for an unset pod ``approvalMode`` (ADR 0016 SS2) -- forwarded to every task's
    ``dispatch_task`` call unchanged; an explicit pod value always wins over it."""
    pod_pipeline(project)  # validates pod/lead up front
    effective_spec = effective_pipeline(project, spec)
    resolved_vars = dict(variables or {})
    deferred = _unsupplied_variables(effective_spec, variables)
    if deferred is None:
        resolved_vars = _pipeline.resolve_variables(effective_spec, variables)
    elif not _tasks_supply_variables(project):
        raise DispatchError(deferred)
    sweep_stale_claims(project)
    sweep_waits(pod=project, probe=probe_wait)
    if resume:
        reclaim_stale_running(project)

    results: list[TaskResult] = []
    claimed_ids: set[str] = set()
    while (max_tasks is None or len(results) < max_tasks) and not (stop is not None and stop()):
        claim = claim_next_task(project, resume=resume, skip=frozenset(claimed_ids))
        if claim is None:
            break
        task = claim.record
        resume_hops = claim.resume_hops
        task_id = task.id
        claimed_ids.add(task_id)
        if claim.refusal is not None:
            results.append(refuse_claimed_task(project, task, *claim.refusal))
            continue
        if deferred is not None and not (task.variables or task.pipeline or task.pipeline_spec):
            results.append(refuse_claimed_task(project, task, "pipeline", deferred))
            continue
        try:
            run_spec, run_vars, source = _resolve_task_run(
                project,
                task,
                effective_spec,
                resolved_vars,
                variables,
                "default" if spec is None else "file",
            )
        except TaskRunRefusal as exc:
            results.append(refuse_claimed_task(project, task, "pipeline", str(exc)))
            continue
        _record_task_run(project, task, source, run_spec)
        refused = prepare_claimed_task(project, task)
        if refused is not None:
            results.append(refused)
            continue

        def _persist(hop: HopResult, _project: str = project, _task_id: str = task_id) -> None:
            persist_hop(_project, _task_id, hop)

        def _touch(_project: str = project, _task_id: str = task_id) -> None:
            touch_claim(_project, _task_id)

        res = dispatch_task(
            project,
            task,
            runner=runner,
            turn_timeout=turn_timeout,
            verify_timeout=verify_timeout,
            resume_from=resume_hops,
            on_hop=_persist,
            on_retry=_touch,
            sleep=sleep,
            spec=spec if source == "default" else run_spec,
            variables=run_vars,
            approval_default=approval_default,
        )
        finalize_task(project, task_id, res)
        results.append(res)
        if res.status == "blocked" and res.blocked_reason != "resources":
            break  # budget is pod-wide; no point trying further tasks this run
    return results


# A "dispatch every pod in one sweep" helper doesn't exist here on purpose —
# not an oversight. The HTTP server's sweep loop (`interfaces/http/server.py`) instead iterates
# `dispatchable_pods()` and calls `dispatch_pod()` per pod through
# `tasks.application.runs.execute` (see `tests/guards/test_no_suppressed_dispatch.py`).
# A single-sweep helper's natural shape — one record for the whole sweep,
# catching and swallowing `DispatchError` per pod — loses per-pod granularity
# in the run registry (one run id per pod) and hides a real error instead of
# surfacing it. Do not reintroduce that shape.
