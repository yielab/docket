"""The one place a task record's ``status`` is written.

``tasks/domain/state.py`` decides what a move does (``decide``, pure); ``apply_to_task`` carries
that out on a record the caller already holds under the queue lock. Every other module asks for a
transition and never assigns ``status`` itself, which ``tests/architecture/test_status_writers.py``
enforces. ``tasks/application/queue.py::apply_transition`` wraps this in its own locked read-modify-write for the
caller that holds only a pod and a task id."""

from __future__ import annotations

from typing import Any

from docket.tasks.domain import state as _state
from docket.tasks.domain.task import TaskRecord

__all__ = ["apply_to_task"]


def apply_to_task(record: TaskRecord, to: _state.Status, **facts: Any) -> _state.Transition:
    """Move *record* to *to*: ``decide``'s field changes, then the status; ``IllegalTransition``
    comes before any change. A dropped field returns to its default (``None``, ``[]``, ``""``)."""
    transition = _state.decide(record.status, to, **facts)
    for name in transition.drop:
        setattr(record, name, _default(name))
    for name, value in transition.fields.items():
        setattr(record, name, value)
    record.status = transition.to
    return transition


def _default(name: str) -> Any:
    return TaskRecord.model_fields[name].get_default(call_default_factory=True)
