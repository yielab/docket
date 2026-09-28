"""operator-v1: the shared data model for the operator loop (ADR 0016).

Every value that reaches a human channel, an HTTP client, an MCP tool or a CloudEvent is
built through this module, never hand-built twice: task/A2A state, a typed intake brief, a
question/answer pair shaped as an MCP elicitation, an approval/task/inbox view, and one
CloudEvent constructor. Pure data and validation; no I/O.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

A2A_STATES: tuple[str, ...] = (
    "SUBMITTED",
    "WORKING",
    "INPUT_REQUIRED",
    "AUTH_REQUIRED",
    "COMPLETED",
    "FAILED",
    "CANCELED",
    "REJECTED",
)

EVENT_KINDS: tuple[str, ...] = (
    "task.input_required",
    "approval.requested",
    "approval.expiring",
    "task.blocked",
    "task.failed",
    "task.rejected",
    "task.completed",
    "channel.test",
)

_PRIMITIVE_TYPES = ("string", "number", "integer", "boolean")
_EVENT_SCHEMA_URL = "https://docket.dev/schemas/operator-v1/event.schema.json"


def a2a_state(
    status: str, blocked_reason: str | None = None, failure_kind: str | None = None
) -> str:
    """Map a docket task ``status`` (plus reason/kind) onto its A2A 1.0.0 ``TaskState``."""
    if status == "pending":
        return "SUBMITTED"
    if status == "running":
        return "WORKING"
    if status in ("waiting_input", "waiting_approval"):
        return "INPUT_REQUIRED"
    if status == "blocked":
        return "AUTH_REQUIRED" if blocked_reason == "resources" else "INPUT_REQUIRED"
    if status == "done":
        return "COMPLETED"
    if status == "failed":
        return "REJECTED" if failure_kind == "rejected" else "FAILED"
    if status == "cancelled":
        return "CANCELED"
    raise ValueError(f"unknown task status: {status!r}")


def _validate_resource(value: str) -> str:
    if value == "verify" or value.startswith("secret:") or value.startswith("path:"):
        return value
    raise ValueError(f"resource must be 'verify' or start with 'secret:'/'path:': {value!r}")


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
            raise ValueError("objective must not be empty")
        return v

    @field_validator("resources")
    @classmethod
    def _resources_prefixed(cls, v: list[str]) -> list[str]:
        return [_validate_resource(r) for r in v]


def validate_requested_schema(d: dict[str, Any]) -> dict[str, Any]:
    """Validate a raw MCP elicitation ``requestedSchema``: a flat object of primitive
    properties. Raises ``ValueError`` naming the problem; returns *d* unchanged."""
    if not isinstance(d, dict):
        raise ValueError("requestedSchema must be an object")
    if d.get("type") != "object":
        raise ValueError("requestedSchema.type must be 'object'")
    properties = d.get("properties")
    if not isinstance(properties, dict) or not properties:
        raise ValueError("requestedSchema.properties must be a non-empty object")
    for name, prop in properties.items():
        if not isinstance(prop, dict):
            raise ValueError(f"requestedSchema.properties.{name} must be an object")
        prop_type = prop.get("type")
        if prop_type not in _PRIMITIVE_TYPES:
            raise ValueError(
                f"requestedSchema.properties.{name}.type must be one of {_PRIMITIVE_TYPES}"
            )
        enum = prop.get("enum")
        if enum is not None and not isinstance(enum, list):
            raise ValueError(f"requestedSchema.properties.{name}.enum must be a list")
    required = d.get("required", [])
    if not isinstance(required, list):
        raise ValueError("requestedSchema.required must be a list")
    missing = [r for r in required if r not in properties]
    if missing:
        noun = "property" if len(missing) == 1 else "properties"
        raise ValueError(f"requestedSchema.required names undefined {noun}: {missing}")
    return d


class QuestionSchema(BaseModel):
    """The MCP elicitation ``requestedSchema`` shape, used only to render its own JSON
    Schema fragment for the generator; runtime checks go through
    ``validate_requested_schema``."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["object"] = "object"
    properties: dict[str, dict[str, Any]] = Field(default_factory=dict)
    required: list[str] = Field(default_factory=list)


def new_question_id() -> str:
    """Mint a question id in the ``q-<12 hex chars>`` shape used by every question."""
    return f"q-{uuid.uuid4().hex[:12]}"


class Question(BaseModel):
    """A question posed to a human, shaped as an MCP elicitation request."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    id: str
    task_id: str = Field(alias="taskId")
    pod: str
    step: str
    message: str
    requested_schema: dict[str, Any] = Field(alias="requestedSchema")
    created_at: str = Field(alias="createdAt")
    expires_at: str | None = Field(None, alias="expiresAt")

    @field_validator("requested_schema")
    @classmethod
    def _validate_schema(cls, v: dict[str, Any]) -> dict[str, Any]:
        return validate_requested_schema(v)


class AnswerResult(BaseModel):
    """The result of answering a ``Question``, shaped as an MCP elicitation result."""

    model_config = ConfigDict(extra="forbid")

    action: Literal["accept", "decline", "cancel"]
    content: dict[str, Any] | None = None


_TYPE_CHECKERS: dict[str, Any] = {
    "string": lambda v: isinstance(v, str),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
}


def validate_answer(question: Question, result: AnswerResult) -> AnswerResult:
    """Validate an answer's ``content`` against the question's ``requestedSchema``;
    ``decline``/``cancel`` ignore *content*. Raises ``ValueError`` naming the property."""
    if result.action != "accept":
        return result
    schema = question.requested_schema
    properties: dict[str, Any] = schema.get("properties", {})
    required: list[str] = schema.get("required", [])
    content = result.content or {}
    for name in required:
        if name not in content:
            raise ValueError(f"missing required property: {name!r}")
    for name, value in content.items():
        prop = properties.get(name)
        if prop is None:
            continue
        expected_type = prop.get("type")
        checker = _TYPE_CHECKERS.get(expected_type)
        if checker is not None and not checker(value):
            raise ValueError(f"property {name!r} does not match type {expected_type!r}")
        enum = prop.get("enum")
        if enum is not None and value not in enum:
            raise ValueError(f"property {name!r} is not one of {enum!r}")
    return result


class ApprovalView(BaseModel):
    """The operator-v1 rendering of a pending or resolved approval record."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    token: str
    pod: str
    task_id: str | None = Field(None, alias="taskId")
    role: str
    tool: str | None = None
    action: str | None = None
    policy: str | None = None
    state: str
    created_at: str = Field(alias="createdAt")
    expires_at: str | None = Field(None, alias="expiresAt")
    a2a_state: str = Field("INPUT_REQUIRED", alias="a2aState")


class TaskView(BaseModel):
    """The operator-v1 rendering of one docket task: lifecycle plus its A2A state."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    id: str
    pod: str
    status: str
    a2a_state: str = Field(alias="a2aState")
    reason: str | None = None
    description: str = ""
    priority: str = ""
    created_at: str = Field("", alias="createdAt")
    updated_at: str = Field("", alias="updatedAt")
    question: Question | None = None
    approval_token: str | None = Field(None, alias="approvalToken")
    brief: TaskBrief | None = None


class InboxView(BaseModel):
    """The derived operator inbox: everything that needs a human, plus recent context."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    needs_you: list[TaskView | ApprovalView] = Field(default_factory=list, alias="needsYou")
    failed: list[TaskView] = Field(default_factory=list)
    done_since: list[TaskView] = Field(default_factory=list, alias="doneSince")
    running: list[TaskView] = Field(default_factory=list)
    next: str | None = None


class CloudEvent(BaseModel):
    """A CloudEvents 1.0 structured-mode envelope."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    specversion: Literal["1.0"] = "1.0"
    id: str
    source: str
    type: str
    time: str
    subject: str
    datacontenttype: Literal["application/json"] = "application/json"
    dataschema: str
    data: dict[str, Any]


def make_event(
    kind: str, pod: str, subject: str, data: dict[str, Any], *, time: str, version: str
) -> CloudEvent:
    """Build one CloudEvent for *kind* (must be in ``EVENT_KINDS``); ``id`` is a stable
    digest of the event type, *subject* and *version*, so redelivery never mints a second."""
    if kind not in EVENT_KINDS:
        raise ValueError(f"unknown event kind: {kind!r}")
    event_type = f"dev.docket.{kind}"
    digest = hashlib.sha256(f"{event_type}|{subject}|{version}".encode()).hexdigest()[:32]
    return CloudEvent(
        specversion="1.0",
        id=digest,
        source=f"urn:docket:pod:{pod}",
        type=event_type,
        time=time,
        subject=subject,
        datacontenttype="application/json",
        dataschema=_EVENT_SCHEMA_URL,
        data=data,
    )


def canonical_args_digest(tool: str, args: dict[str, Any]) -> str:
    """A stable digest of a tool call's arguments, keyed by tool name; matches a
    single-use pre-grant to the exact call it was granted for regardless of key order."""
    canonical = json.dumps(args, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(f"{tool}|{canonical}".encode()).hexdigest()
    return digest[:16]
