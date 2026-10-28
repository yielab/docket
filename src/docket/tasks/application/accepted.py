"""Counted tokens of the tasks that ended ``done``: the input of tokens per accepted task."""

from __future__ import annotations

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
