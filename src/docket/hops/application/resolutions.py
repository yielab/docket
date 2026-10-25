"""Apply the answers a claimed task is waiting to hear: what ``resolve`` leaves to the claim.

``tasks.application.escalations.resolve`` receives an answer to a parked question or a granted
approval at a pipeline position (it records it and reopens the task ``pending``) and resolves no
pipeline. The claim applies it: before the resume position is computed, ``apply_resolutions``
reads the escalations the task lists and, for each ``input``, ``approval`` or ``gate`` record that
is ``resolved`` and not yet stamped, persists the synthetic operator hop and follows the step's
``on:`` route, or hands back the position the granted approval fired at. The answer to a
``consult`` needs no applying: the re-run hop reads it from the record
(``tasks.application.answers.consult_note``). A record is stamped (``mark_escalation_applied``) only
after its effect is on the task, and each effect is idempotent, so a task claimed twice (a crash, a
``stale_claim`` reclaim) is changed once. Records that are ``expired``, ``decided`` or still
``pending`` are never applied.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from docket.governance import approval as _approval
from docket.hops.gates import post_hop as _post_hop
from docket.kernel import clock as _clock
from docket.kernel.errors import DispatchError
from docket.kernel.handoff import HandoffArtifact
from docket.kernel.operator_contract import Escalation
from docket.pipeline.domain import plan as _orch
from docket.platform import mark_escalation_applied, read_escalation
from docket.tasks.application.record import replay_pipeline_position
from docket.tasks.application.repository import TaskRepository
from docket.tasks.domain.task import HopResult, TaskRecord

__all__ = [
    "Applied",
    "apply_resolutions",
    "mark_escalation_applied",
    "resolve_route",
    "routed_hop",
]

_DECLINE = "decline"
_DENY = "deny"


@dataclass(frozen=True)
class Applied:
    """What applying the answers produced: the hops to resume from, when an answer's route ends the
    task the ``(status, reason)`` it ends with (``done`` or ``failed``), and the pipeline position a
    granted gate fired at, whose approval check the run skips once."""

    hops: list[HopResult]
    ended: tuple[str, str] | None = None
    gate_override_index: int | None = None


def resolve_route(
    on: dict[str, Any] | None,
    label: str,
    route_counts: dict[tuple[str, str], int],
    id_to_index: dict[str, int],
    step_id: str,
    pipeline_index: int,
) -> tuple[str | None, str]:
    """Resolve *label* against *on* like ``hops.application.executor._route_outcome`` does for a live
    hop, minus its tracing. Returns ``(next_step, terminal)``; *terminal* is
    ``"failed"``/``"done"``/``""`` (ordinary advance)."""
    route = _post_hop._match_on_route(on, label)
    if route is None:
        return None, ""
    if isinstance(route, dict):
        target: Any = route.get("goto")
        max_cycles = route.get("max")
    else:
        target = route
        max_cycles = None
    target_str = target if isinstance(target, str) else "stop"
    if target_str == "fail":
        return None, "failed"
    if target_str == "stop":
        return None, "done"
    target_index = id_to_index.get(target_str)
    if target_index is None:
        return None, "failed"
    if target_index <= pipeline_index:
        key = (step_id, label)
        cap = max_cycles if isinstance(max_cycles, int) else 1
        if route_counts.get(key, 0) >= cap:
            return None, "failed"
    return target_str, ""


def routed_hop(step_id: str, escalation_id: str, label: str, target: str | None) -> HopResult:
    """The synthetic ``role="operator"`` hop an answer to an ``input`` step persists."""
    return HopResult(
        role="operator",
        member_id="operator",
        ok=True,
        output=f"answered: {escalation_id}",
        # `verdict` carries the outcome label ("answered"/"declined"), not a real verdict
        # marker -- `replay_pipeline_position`'s own route_counts rebuild keys a backward/
        # self route by `hop.artifact.verdict` (see its handling of `hop.next_step`), the
        # same field a verdict gate's routed hop already relies on; without this a resumed
        # cap check would key on the wrong label.
        artifact=HandoffArtifact(summary=f"answered: {escalation_id}", verdict=label),
        step_id=step_id,
        next_step=target,
    )


def _unapplied(task: TaskRecord) -> list[Escalation]:
    """The task's ``input``, ``approval`` and ``gate`` escalations that are resolved and not applied
    yet. A parked call, a changed check and a wait in the turn are stamped when they are resolved;
    a consult's answer is read by the re-run hop and stamped once a hop of its step is persisted."""
    found: list[Escalation] = []
    for escalation_id in task.escalations:
        escalation = read_escalation(escalation_id)
        if (
            escalation is not None
            and escalation.state == "resolved"
            and escalation.kind in ("input", "approval", "gate")
            and escalation.resolution is not None
            and escalation.resolution.applied_at is None
        ):
            found.append(escalation)
    return found


def _gate_position(escalation: Escalation) -> int | None:
    """The pipeline position the pre-hop gate of *escalation* fired at, from its approval record;
    ``None`` for a denial (the task already failed) or a record that no longer names one."""
    resolution = escalation.resolution
    assert resolution is not None
    if resolution.option_id == _DENY:
        return None
    try:
        context = _approval.approval_get(_approval.approval_of(escalation.id)).get("context")
    except _approval.ApprovalError:
        return None
    index = context.get("pipelineIndex") if isinstance(context, dict) else None
    return index if isinstance(index, int) else None


def _append_once(record: TaskRecord, hop: HopResult) -> bool:
    """Append *hop* unless *record* holds the same operator hop already."""
    if any(
        h.role == hop.role and h.step_id == hop.step_id and h.output == hop.output
        for h in record.hops
    ):
        return False
    record.hops.append(hop)
    return True


def _apply_input(
    repository: TaskRepository,
    task: TaskRecord,
    escalation: Escalation,
    hops: list[HopResult],
    runtime_steps: tuple[_orch.PlannedNode, ...],
    id_to_index: dict[str, int],
) -> tuple[list[HopResult], tuple[str, str] | None]:
    """Persist the synthetic hop of the answer to *escalation* and follow its route. Returns the
    hops and, when the route ends the task, its ``(status, reason)``."""
    resolution = escalation.resolution
    assert resolution is not None
    step_id = escalation.step
    index = id_to_index.get(step_id)
    node = runtime_steps[index] if index is not None else None
    if index is None or not isinstance(node, _orch.PlannedUnit):
        raise DispatchError(f"the answer for step {step_id!r} names no step of this pipeline")
    question_id = escalation.id
    label = "declined" if resolution.option_id == _DECLINE else "answered"
    done = any(
        h.role == "operator" and h.step_id == step_id and h.output == f"answered: {question_id}"
        for h in hops
    )
    if done:
        # A claim that already persisted the hop: its route count is in the hops, so only a
        # route that ends the task is decided again.
        target, terminal = resolve_route(node.on, label, {}, id_to_index, step_id, index)
    else:
        position = replay_pipeline_position(runtime_steps, hops)
        if position.pipeline_index != index:
            raise DispatchError(f"task {task.id!r} is not parked at step {step_id!r}")
        target, terminal = resolve_route(
            node.on, label, dict(position.route_counts), id_to_index, step_id, index
        )
        hop = routed_hop(step_id, question_id, label, target)
        repository.update(task.id, lambda record: _append_once(record, hop))
        hops = [*hops, hop]
    if terminal:
        word = "fail" if terminal == "failed" else "stop"
        return hops, (terminal, f"step {step_id!r} outcome {label.upper()} routed to {word}")
    return hops, None


def apply_resolutions(
    project: str,
    task: TaskRecord,
    hops: list[HopResult],
    runtime_steps: tuple[_orch.PlannedNode, ...],
    id_to_index: dict[str, int],
) -> Applied:
    """Apply every resolved, unapplied question of the claimed *task*: *hops* plus a synthetic
    operator hop, and the ending an answer's route gives the task. Raises ``DispatchError`` when
    the answer no longer fits the pipeline."""
    repository = TaskRepository.for_pod(project)
    override: int | None = None
    for escalation in _unapplied(task):
        ended: tuple[str, str] | None = None
        if escalation.kind in ("approval", "gate"):
            override = _gate_position(escalation)
        else:
            hops, ended = _apply_input(
                repository, task, escalation, hops, runtime_steps, id_to_index
            )
        mark_escalation_applied(escalation.id, _clock.iso())
        if ended is not None:
            return Applied(hops, ended, override)
    return Applied(hops, gate_override_index=override)
