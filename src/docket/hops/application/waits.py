"""A ``wait`` step: park the task until a time or a probe, and apply how the wait ended.

Reaching the step runs no agent turn. ``run_wait_step`` guards the probe like a ``run:`` step,
records the due time and the probe schedule on the task (``TaskRecord.wait``), opens the ``wait``
escalation and parks the task ``waiting_input``. The sweep (``escalation_sweep.sweep_waits``) ends
the wait; ``probe_wait`` is the command it runs, in the envelope a ``run:`` step runs in. The next
claim calls ``apply_wait``, which persists the synthetic hop that moves the resume position past
the step (or along its ``timeout`` route). See pod-dispatch.spec.md "Wait steps".
"""

from __future__ import annotations

import datetime as _dt

from docket.hops.application.resolutions import Applied, resolve_route
from docket.hops.application.steps import _guard_command
from docket.hops.gates.post_hop import _latest_implementer_evidence, _run_in_envelope
from docket.kernel import clock as _clock
from docket.kernel.errors import DispatchError
from docket.kernel.handoff import HandoffArtifact
from docket.pipeline.domain import plan as _orch
from docket.pipeline.domain.step import parse_duration
from docket.tasks.application import escalations as _escalations
from docket.tasks.application.record import (
    UnitContext,
    UnitOutcome,
    claimed_worktree_dir,
    replay_pipeline_position,
)
from docket.tasks.application.repository import TaskRepository
from docket.tasks.domain.task import HopResult, TaskRecord, TaskWait
from docket.teams import fleet as _fleet
from docket.teams import pod as _pod
from docket.teams.settings import pod_verify_timeout, resolve_timeout

__all__ = ["apply_wait", "probe_wait", "run_wait_step"]


def run_wait_step(ctx: UnitContext, node: _orch.PlannedUnit, index_for_context: int) -> UnitOutcome:
    """Park the task on *node*'s wait: guard its probe, record the wait, open the escalation and
    stop ``waiting_input``; no hop is persisted for this attempt."""
    assert node.wait is not None
    if node.until is not None:
        refused = _guard_command(ctx, node, node.until.run, index_for_context)
        if refused is not None:
            return refused
    now = _clock.now()
    due_at = (now + _dt.timedelta(seconds=parse_duration(node.wait))).isoformat()
    every_s = parse_duration(node.until.every) if node.until is not None else None
    wait = TaskWait(
        step=node.step_id,
        due_at=due_at,
        until=node.until.run if node.until is not None else None,
        every_s=every_s,
        next_probe_at=(
            (now + _dt.timedelta(seconds=every_s)).isoformat() if every_s is not None else None
        ),
        routed=any(str(key).lower() == "timeout" for key in node.on or {}),
    )

    def _park(task: TaskRecord) -> bool:
        task.wait = wait
        return True

    TaskRepository.for_pod(ctx.project).update(ctx.task_id, _park)
    ctx.task.wait = wait
    probing = f", probing {wait.until!r} every {node.until.every}" if node.until else ""
    escalation = _escalations.open_for_wait(
        pod=ctx.project,
        task_id=ctx.task_id,
        step=node.step_id,
        prompt=f"waiting until {due_at} at step {node.step_id!r}{probing}",
        due_at=due_at,
    )
    return UnitOutcome(
        kind="waiting_input",
        reason=f"waiting until {due_at} at step {node.step_id!r} (escalation={escalation.id})",
    )


def probe_wait(project: str, task: TaskRecord) -> bool:
    """Run the probe of the wait *task* is parked on in the envelope of a ``run:`` step -- the jail
    when isolation is on, the task's worktree else the Lead's codebase or working directory, the
    pod's verify timeout -- and say whether it exited ``0``. Nothing it prints is kept."""
    wait = task.wait
    if wait is None or not wait.until:
        return False
    worktree = claimed_worktree_dir(task)
    lead_id = _pod.member_id(project, "lead")
    cwd = worktree or str(
        _fleet.meta_get(lead_id, "codebase", "") or _fleet.meta_get(lead_id, "workDir", "") or ""
    )
    evidence = _latest_implementer_evidence(task.hops)
    env = {
        "DOCKET_TASK_ID": task.id,
        "DOCKET_BASE_COMMIT": str(evidence.get("baseCommit") or ""),
        "DOCKET_HEAD_COMMIT": str(evidence.get("commit") or ""),
    }
    timeout = resolve_timeout(None, pod_verify_timeout(project))
    code, _output = _run_in_envelope(project, "run", wait.until, cwd, timeout, env=env)
    return code == 0


def apply_wait(
    project: str,
    task: TaskRecord,
    hops: list[HopResult],
    runtime_steps: tuple[_orch.PlannedNode, ...],
    id_to_index: dict[str, int],
) -> Applied:
    """Apply how the claimed *task*'s wait ended: *hops* plus its synthetic hop, persisted with the
    removal of ``wait`` in one update, and the ``(status, reason)`` a ``timeout`` route ends the
    task with. ``DispatchError`` when the pipeline no longer parks the task at that step."""
    wait = task.wait
    if wait is None or wait.outcome is None:
        return Applied(hops)
    index = id_to_index.get(wait.step)
    node = runtime_steps[index] if index is not None else None
    if index is None or not isinstance(node, _orch.PlannedUnit) or node.wait is None:
        raise DispatchError(f"the wait for step {wait.step!r} names no wait step of this pipeline")
    position = replay_pipeline_position(runtime_steps, hops)
    if position.pipeline_index != index:
        raise DispatchError(f"task {task.id!r} is not parked at step {wait.step!r}")
    label = wait.outcome
    target, terminal = resolve_route(
        node.on, label, dict(position.route_counts), id_to_index, wait.step, index
    )
    hop = HopResult(
        role=wait.step,
        member_id="",
        ok=True,
        output=f"waited: {label}",
        artifact=HandoffArtifact(summary=f"waited: {label}", verdict=label),
        step_id=wait.step,
        next_step=target,
    )

    def _persist(record: TaskRecord) -> bool:
        if record.wait is None:
            return False
        record.hops.append(hop)
        record.wait = None
        return True

    TaskRepository.for_pod(project).update(task.id, _persist)
    task.wait = None
    hops = [*hops, hop]
    if terminal:
        word = "fail" if terminal == "failed" else "stop"
        return Applied(
            hops, (terminal, f"step {wait.step!r} outcome {label.upper()} routed to {word}")
        )
    return Applied(hops)
