"""The one place a task record's ``status`` is written.

``tasks/domain/state.py`` decides what a move does (``decide``, pure); ``apply_to_task`` carries
that out on a record the caller already holds under the queue lock. Every other module asks for a
transition and never assigns ``status`` itself, which ``tests/architecture/test_status_writers.py``
enforces. ``tasks/application/queue.py::apply_transition`` wraps this in its own locked read-modify-write for the
caller that holds only a pod and a task id."""

from __future__ import annotations

from typing import Any

from docket.tasks.domain import state as _state

__all__ = ["apply_to_task"]


def apply_to_task(task: dict[str, Any], to: _state.Status, **facts: Any) -> _state.Transition:
    """Move *task* to *to*: the field changes ``decide`` returns, then the status.

    Raises ``IllegalTransition`` before touching the record. *facts* are ``decide``'s keywords."""
    transition = _state.decide(str(task.get("status", "")), to, **facts)
    for key in transition.drop:
        task.pop(key, None)
    task.update(transition.fields)
    task["status"] = transition.to.value
    return transition
