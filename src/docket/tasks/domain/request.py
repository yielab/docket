"""The structured request a caller may send beside a task's description.

Pure data and validation, no I/O. It is a separate field from the Lead's ``TaskBrief``: the brief is
the Lead's output, this is what the plan of record already holds as fields (objective, acceptance,
constraints) and would otherwise flatten into prose.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from docket.tasks.domain.parts import is_none

__all__ = ["TaskRequest"]


class TaskRequest(BaseModel):
    """Every field is optional and a stored request holds only those that were set."""

    model_config = ConfigDict(extra="forbid")

    objective: str | None = Field(None, exclude_if=is_none)
    done_when: str | None = Field(None, alias="doneWhen", exclude_if=is_none)
    acceptance: list[str] | None = Field(None, exclude_if=is_none)
    constraints: list[str] | None = Field(None, exclude_if=is_none)
    risk: str | None = Field(None, exclude_if=is_none)
    answers: list[dict[str, Any]] | None = Field(None, exclude_if=is_none)
    verify: str | None = Field(None, exclude_if=is_none)
    kind: str | None = Field(None, exclude_if=is_none)
    paths: list[str] | None = Field(None, exclude_if=is_none)
