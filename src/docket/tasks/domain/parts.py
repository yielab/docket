"""The nested shapes a task record holds, each a closed model under the key its writer chose.

A key the writer omits when it has nothing to say is absent from the dump (``exclude_if``), never
``null``; ``tasks/domain/task.py`` states the rule for the record as a whole."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "Answer",
    "Prepared",
    "TaskUsage",
    "UsageTotals",
    "Worktree",
]


def is_none(value: object) -> bool:
    """``exclude_if`` for an optional key that is absent until something writes it."""
    return value is None


class _Part(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class Worktree(_Part):
    """The task's own git worktree. A fallback (no worktree made) records only ``fallback_reason``
    beside empty ``dir``, ``branch`` and ``base_commit``."""

    dir: str
    branch: str
    base_commit: str = Field(alias="baseCommit")
    base_ref: str | None = Field(None, alias="baseRef", exclude_if=is_none)
    git_dir: str | None = Field(None, alias="gitDir", exclude_if=is_none)
    common_dir: str | None = Field(None, alias="commonDir", exclude_if=is_none)
    fallback_reason: str | None = Field(None, alias="fallbackReason", exclude_if=is_none)
    pruned_at: str | None = Field(None, alias="prunedAt", exclude_if=is_none)


class Prepared(_Part):
    """What the prepare step ran for this task and whether its cache entry was reused."""

    command: str
    source: str
    lock_hash: str = Field(alias="lockHash")
    cache_hit: bool = Field(alias="cacheHit")


class Answer(_Part):
    """One answered question, as a hop's prompt renders it: a projection of a resolved escalation."""

    question_id: str = Field(alias="questionId")
    step: str
    message: str
    action: str
    content: dict[str, Any] | None = None
    channel: str
    actor: str
    answered_at: str = Field(alias="answeredAt")
    kind: str = "clarification"
    created_at: str = Field(alias="createdAt")
    option_id: str | None = Field(None, alias="optionId", exclude_if=is_none)


class UsageTotals(_Part):
    """Measured endpoint tokens."""

    input: int = 0
    cached: int = 0
    cache_write: int = Field(0, alias="cacheWrite")
    output: int = 0


class TaskUsage(UsageTotals):
    """A task's measured tokens: the sum over its hops and the same totals per served model."""

    by_model: dict[str, UsageTotals] = Field(default_factory=dict, alias="byModel")
