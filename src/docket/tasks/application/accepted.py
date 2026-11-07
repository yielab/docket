"""The terminal tasks, read once: counted tokens of those that ended ``done`` and the outcomes
the work figures fold."""

from __future__ import annotations

from docket.kernel import clock as _clock
from docket.observability.figures import TaskOutcome
from docket.tasks.application.queue import dispatchable_pods
from docket.tasks.application.repository import TaskRepository
from docket.tasks.domain.state import Status


def accepted_counted_tokens() -> list[int]:
    """Counted tokens (input minus cache reads, plus output) of each ``done`` task that carries a
    ``usage`` block, across every dispatchable pod."""
    counted: list[int] = []
    for pod in dispatchable_pods():
        for task in TaskRepository.for_pod(pod).list():
            if task.status == Status.done and task.usage is not None:
                usage = task.usage
                counted.append(max(0, usage.input - usage.cached) + usage.output)
    return counted


def terminal_task_outcomes() -> list[TaskOutcome]:
    """Each task in a terminal status that carries a ``completedAt``, across every dispatchable pod:
    its pod, the role of its last hop, whether it ended ``done`` and the verdict of each hop that
    carries one."""
    outcomes: list[TaskOutcome] = []
    for pod in dispatchable_pods():
        for task in TaskRepository.for_pod(pod).list():
            completed = _clock.parse_epoch(task.completed_at)
            if task.status not in Status.TERMINAL or completed is None:
                continue
            roles = [hop.role for hop in task.hops if hop.role]
            verdicts = tuple(
                (hop.role, hop.artifact.verdict.lower())
                for hop in task.hops
                if hop.role and hop.artifact is not None and hop.artifact.verdict
            )
            outcomes.append(
                TaskOutcome(
                    pod=pod,
                    role=roles[-1] if roles else "none",
                    done=task.status == Status.done,
                    completed=completed,
                    verdicts=verdicts,
                )
            )
    return outcomes
