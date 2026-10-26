"""The Lead's typed intake brief: the one shape every intake consumer agrees on.

Pure data and validation, no I/O. It lives in ``kernel`` because both the handoff artifact a hop
carries (``kernel/handoff.py``) and the operator's task view (``operator/contract.py``) hold one.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from docket.kernel.errors import InvalidInput

__all__ = ["TaskBrief"]


def _validate_resource(value: str) -> str:
    if value == "verify" or value.startswith("secret:") or value.startswith("path:"):
        return value
    raise InvalidInput(f"resource must be 'verify' or start with 'secret:'/'path:': {value!r}")


class TaskBrief(BaseModel):
    """The Lead's typed intake output: objective, acceptance, what the Implementer needs,
    and the resources a deterministic check must confirm before another turn runs."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    objective: str
    acceptance: list[str] = Field(default_factory=list)
    context: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)
    resources: list[str] = Field(default_factory=list)
    expected_risky_actions: list[str] = Field(default_factory=list, alias="expectedRiskyActions")
    answers: list[dict[str, Any]] = Field(default_factory=list)

    @field_validator("objective")
    @classmethod
    def _objective_non_empty(cls, v: str) -> str:
        if not v.strip():
            raise InvalidInput("objective must not be empty")
        return v

    @field_validator("resources")
    @classmethod
    def _resources_prefixed(cls, v: list[str]) -> list[str]:
        return [_validate_resource(r) for r in v]
