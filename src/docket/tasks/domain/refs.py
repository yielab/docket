"""What an operator can type to name one task: the reference value and its short form."""

from __future__ import annotations

from dataclasses import dataclass, field

from docket.kernel.errors import NotFound

SHORT_ID_LEN = 18
LEAD_STEP_ID = "lead"


class TaskRefError(NotFound):
    """The reference matched no task, or more than one."""


@dataclass(frozen=True)
class TaskRef:
    task_id: str
    project: str
    session_key: str
    run_ids: tuple[str, ...] = field(default_factory=tuple)
    worktree: str = ""


def short_id(task_id: str) -> str:
    """The form `task list` prints."""
    return task_id[:SHORT_ID_LEN]
