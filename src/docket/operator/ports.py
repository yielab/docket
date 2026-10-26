"""What the operator asks of the contexts above it, bound once per entry (``bootstrap.bind_adapters``).

The inbox lists every pod's tasks; reading them is the task queue's business and ``tasks`` sits
above ``operator``, so the inbox names only the shape of the answer.
"""

from __future__ import annotations

from typing import Any, Protocol

from docket.kernel.ports import Binding


class TaskReader(Protocol):
    def read_tasks(self, project: str) -> list[dict[str, Any]]:
        """The pod's task list ([] when absent), normalized."""
        ...


task_reader_port: Binding[TaskReader] = Binding("task_reader")
task_reader: TaskReader = task_reader_port.proxy()


def bind_task_reader(adapter: TaskReader) -> None:
    task_reader_port.bind(adapter)
