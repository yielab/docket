"""The short-form configuration document models: what ``teams.roles.normalize_role``,
``pipeline.domain.spec.normalize_pipeline`` and ``governance.policy.normalize_policy`` accept,
plus the pod and routine documents. They exist for JSON Schema generation and for
``teams.config_docs``'s field-named errors; the normalisers stay the only loaders."""

from __future__ import annotations

import zoneinfo
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic_core import PydanticCustomError

from docket.pipeline.application import schedule as _schedule
from docket.teams import pod as _pod

# ── Short-form models ─────────────────────────────────────────────────────────
#
# These describe exactly the short forms `teams.roles.normalize_role`,
# `pipeline.domain.spec.normalize_pipeline`, and `governance.policy.normalize_policy` accept, for JSON
# Schema generation (`scripts/gen_config_schemas.py`) and to give `load_document`'s error a
# field name and valid-values list when a short-form document fails its kind's real parser.
# The normalisers remain the only loaders; nothing here ever parses a document directly.


class RoleDocument(BaseModel):
    """The short-form role document -- see role-archetypes.spec.md ("Wire format")."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["role"]
    name: str
    description: str | None = None
    model: Literal["cheap", "strong"] | None = None
    cannot: list[str] | None = None
    verdict: list[str] | None = None
    verify: bool | None = None
    approval: bool | None = None
    instructions: str | None = None
    scope: str | None = None
    version: int | None = None
    tokenBudget: int | None = None
    toolProfile: str | None = None
    hopInstruction: str | None = None
    floor: list[str] | None = None
    tools: list[str] | None = None
    maxToolCalls: int | None = None


class PipelineDocument(BaseModel):
    """The short-form pipeline document -- see pipeline-format.spec.md ("Short form"). Each
    `steps` entry's own sugar keys are validated by `pipeline.domain.spec.normalize_pipeline`, not
    here."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["pipeline"]
    name: str
    description: str | None = None
    variables: dict[str, Any] | None = None
    steps: list[dict[Any, Any]]  # a bare YAML `on:` key loads as True


class PolicyCommand(BaseModel):
    """A policy's ``when.command`` predicate -- see security-gates.spec.md ("Policy format v1")."""

    model_config = ConfigDict(extra="forbid")

    program: list[str] | str | None = None
    verb: list[str] | str | None = None
    args: list[str] | str | None = None
    writes: list[str] | str | None = None


class PolicyWhen(BaseModel):
    """A policy's structured predicate -- see security-gates.spec.md ("Policy format v1").
    `plugin`/`with` describe the predicate-plugin escape hatch (ADR 0010 §4); the runtime
    engine's own support for them is a separate, later card."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    tool: str | None = None
    path: str | None = None
    matches: str | None = None
    branch: str | None = None
    command: PolicyCommand | None = None
    anyOf: list[PolicyWhen] | None = None
    plugin: str | None = None
    with_: dict[str, Any] | None = Field(None, alias="with")


PolicyWhen.model_rebuild()


class PolicyLimit(BaseModel):
    """A policy's send quota -- see security-gates.spec.md ("Policy format v1" requirement 9)."""

    model_config = ConfigDict(extra="forbid")
    kind: Literal["send"] | None = None
    tool: str | None = None
    service: str | None = None
    count: int = Field(ge=1)
    per: Literal["hour", "day"]


class PolicyDocument(BaseModel):
    """The short-form policy document -- see security-gates.spec.md ("Policy format v1")."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["policy"]
    name: str
    description: str | None = None
    appliesTo: list[str] | str | None = None
    on: Literal["input", "toolCall", "output"] | None = None
    when: PolicyWhen | None = None
    then: Literal["allow", "warn", "ask", "block", "redact"]
    message: str | None = None
    limit: PolicyLimit | None = None


class PodDocument(BaseModel):
    """The short-form pod manifest -- see pod-blueprints.spec.md ("Pod manifests: apply")."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["pod"]
    name: str
    description: str | None = None
    members: list[str] | None = None
    settings: dict[str, Any] | None = None
    pipeline: str | None = None
    exporters: list[str] | None = None
    prepare: str | None = None
    protects: list[str] | None = None


class RoutineTask(BaseModel):
    """What a routine enqueues each time it fires -- see pod-dispatch.spec.md "Routines"."""

    model_config = ConfigDict(extra="forbid")

    description: str = Field(min_length=1)
    pipeline: str | None = Field(None, pattern=_pod.TASK_PIPELINE_NAME.pattern)
    variables: dict[Annotated[str, Field(min_length=1)], str] | None = None
    priority: Literal["high", "normal", "low"] = "normal"

    @field_validator("description")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise PydanticCustomError("blank", "must not be blank")
        return value


class RoutineDocument(BaseModel):
    """The ``kind: routine`` document, parsed by this model alone -- see config-format.spec.md
    ("The `routine` kind"). ``schedule`` is a 5-field cron expression or ``@every``; ``tz`` an
    IANA zone name."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["routine"]
    name: str = Field(pattern=_pod.TASK_PIPELINE_NAME.pattern)
    description: str | None = None
    schedule: str
    tz: str = "UTC"
    task: RoutineTask
    catchUp: Literal["skip", "once"] = "skip"
    overlap: Literal["skip", "queue"] = "skip"
    enabled: bool = True

    @field_validator("schedule")
    @classmethod
    def _known_schedule(cls, value: str) -> str:
        if _schedule.parse_interval(value) is None and _schedule.parse_cron(value) is None:
            raise PydanticCustomError(
                "schedule",
                "{value} is neither a 5-field cron expression nor '@every <N><s|m|h>'",
                {"value": repr(value)},
            )
        return value

    @field_validator("tz")
    @classmethod
    def _known_zone(cls, value: str) -> str:
        try:
            zoneinfo.ZoneInfo(value)
        except (zoneinfo.ZoneInfoNotFoundError, ValueError, OSError):
            raise PydanticCustomError(
                "tz", "{value} is not an IANA time zone name", {"value": repr(value)}
            ) from None
        return value
