"""operator-v1: the shared data model for the operator loop (ADR 0016).

Every value that reaches a human channel, an HTTP client, an MCP tool or a CloudEvent is
built through this module, never hand-built twice: task/A2A state, a typed intake brief, a
question/answer pair shaped as an MCP elicitation, an approval/task/inbox view, and one
CloudEvent constructor. Pure data and validation; no I/O.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from docket.kernel import ids as _ids
from docket.kernel.brief import TaskBrief
from docket.kernel.errors import InvalidInput

A2AState = Literal[
    "SUBMITTED",
    "WORKING",
    "INPUT_REQUIRED",
    "AUTH_REQUIRED",
    "COMPLETED",
    "FAILED",
    "CANCELED",
    "REJECTED",
]

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
) -> A2AState:
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
    raise InvalidInput(f"unknown task status: {status!r}")


def validate_requested_schema(d: dict[str, Any]) -> dict[str, Any]:
    """Validate a raw MCP elicitation ``requestedSchema``: a flat object of primitive
    properties. Raises ``ValueError`` naming the problem; returns *d* unchanged."""
    if not isinstance(d, dict):
        raise InvalidInput("requestedSchema must be an object")
    if d.get("type") != "object":
        raise InvalidInput("requestedSchema.type must be 'object'")
    properties = d.get("properties")
    if not isinstance(properties, dict) or not properties:
        raise InvalidInput("requestedSchema.properties must be a non-empty object")
    for name, prop in properties.items():
        if not isinstance(prop, dict):
            raise InvalidInput(f"requestedSchema.properties.{name} must be an object")
        prop_type = prop.get("type")
        if prop_type not in _PRIMITIVE_TYPES:
            raise InvalidInput(
                f"requestedSchema.properties.{name}.type must be one of {_PRIMITIVE_TYPES}"
            )
        enum = prop.get("enum")
        if enum is not None and not isinstance(enum, list):
            raise InvalidInput(f"requestedSchema.properties.{name}.enum must be a list")
    required = d.get("required", [])
    if not isinstance(required, list):
        raise InvalidInput("requestedSchema.required must be a list")
    missing = [r for r in required if r not in properties]
    if missing:
        noun = "property" if len(missing) == 1 else "properties"
        raise InvalidInput(f"requestedSchema.required names undefined {noun}: {missing}")
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
    return _ids.new_short_id("q")


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


QuestionKind = Literal["approval", "clarification", "decision"]


class Option(BaseModel):
    """One choice a v1.1 question offers."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    id: str
    label: str
    description: str
    risks: list[str] = Field(default_factory=list)
    estimated_tokens: int | None = Field(None, alias="estimatedTokens")


class Recommendation(BaseModel):
    """The option the asker recommends, with its reasons and evidence."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    option_id: str = Field(alias="optionId")
    rationale: str
    evidence_refs: list[str] = Field(default_factory=list, alias="evidenceRefs")


class QuestionV11(Question):
    """operator-v1.1 question: a ``Question`` plus ``kind``, ``options`` and a
    ``recommendation``."""

    kind: QuestionKind
    options: list[Option] = Field(default_factory=list)
    recommendation: Recommendation | None = None

    @field_validator("options")
    @classmethod
    def _unique_option_ids(cls, v: list[Option]) -> list[Option]:
        ids = [o.id for o in v]
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        if dupes:
            raise InvalidInput(f"duplicate option ids: {dupes}")
        return v

    @model_validator(mode="after")
    def _recommendation_names_option(self) -> QuestionV11:
        rec = self.recommendation
        if rec is not None and rec.option_id not in {o.id for o in self.options}:
            raise InvalidInput(f"recommendation optionId {rec.option_id!r} names no option")
        return self


class AnswerResultV11(AnswerResult):
    """operator-v1.1 answer: an ``AnswerResult`` plus the chosen ``optionId``. The
    cross-check against the question lives in ``validate_answer_v11``."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    option_id: str | None = Field(None, alias="optionId")


_TYPE_CHECKERS: dict[str, Any] = {
    "string": lambda v: isinstance(v, str),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
}


def validate_content(schema: dict[str, Any], content: dict[str, Any] | None) -> None:
    """Check *content* against the properties of a ``requestedSchema``: every required one is
    present, and each given one has its declared type and lies in its ``enum``. Raises
    ``InvalidInput`` naming the property."""
    properties: dict[str, Any] = schema.get("properties", {})
    required: list[str] = schema.get("required", [])
    given = content or {}
    for name in required:
        if name not in given:
            raise InvalidInput(f"missing required property: {name!r}")
    for name, value in given.items():
        prop = properties.get(name)
        if prop is None:
            continue
        expected_type = prop.get("type")
        checker = _TYPE_CHECKERS.get(expected_type)
        if checker is not None and not checker(value):
            raise InvalidInput(f"property {name!r} does not match type {expected_type!r}")
        enum = prop.get("enum")
        if enum is not None and value not in enum:
            raise InvalidInput(f"property {name!r} is not one of {enum!r}")


def validate_answer(question: Question, result: AnswerResult) -> AnswerResult:
    """Validate an answer's ``content`` against the question's ``requestedSchema``;
    ``decline``/``cancel`` ignore *content*. Raises ``ValueError`` naming the property."""
    if result.action != "accept":
        return result
    validate_content(question.requested_schema, result.content)
    return result


def validate_answer_v11(question: QuestionV11, answer: AnswerResultV11) -> AnswerResultV11:
    """``validate_answer`` plus the option check: an ``accept`` on a question that has
    options MUST carry an ``optionId`` naming one. Raises ``ValueError``."""
    if answer.action == "accept" and question.options:
        if answer.option_id is None:
            raise InvalidInput("accept requires optionId when the question has options")
        if answer.option_id not in {o.id for o in question.options}:
            raise InvalidInput(f"optionId {answer.option_id!r} names no option")
    validate_answer(question, answer)
    return answer


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
    question: QuestionV11 | Question | None = None
    approval_token: str | None = Field(None, alias="approvalToken")
    brief: TaskBrief | None = None


EscalationKind = Literal["approval", "consult", "input", "gate", "check_changed"]
EscalationState = Literal["pending", "resolved", "expired", "decided"]
EscalationPolicy = Literal["person", "recommendation", "deny", "fail"]
EscalationExpiry = Literal["deny", "block"]

_ESCALATION_ID = re.compile(r"esc-[0-9a-f]{12}")


def new_escalation_id() -> str:
    """Mint an escalation id in the ``esc-<12 hex chars>`` shape."""
    return _ids.new_short_id("esc")


def is_escalation_id(value: str) -> bool:
    """Whether *value* is one ``new_escalation_id`` could have minted."""
    return _ESCALATION_ID.fullmatch(value) is not None


class Resolution(BaseModel):
    """How an escalation was settled: the option chosen, any content, and who answered where.
    ``applied_at`` is when the task's continuation was applied (the claim of the task for a
    question), unset until then."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    option_id: str | None = Field(None, alias="optionId")
    content: dict[str, Any] | None = None
    by: str
    channel: str
    at: str
    applied_at: str | None = Field(None, alias="appliedAt")


class _EscalationFields(BaseModel):
    """What an escalation is, shared by the stored record and the view a surface reads."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    id: str
    task: str
    pod: str
    step: str
    role: str
    kind: EscalationKind
    caused_by: str = Field(alias="causedBy")
    prompt: str
    options: list[Option] = Field(default_factory=list)
    recommendation: Recommendation | None = None
    requested_schema: dict[str, Any] | None = Field(None, alias="requestedSchema")
    asked_at: str = Field(alias="askedAt")
    expires_at: str | None = Field(None, alias="expiresAt")
    on_expiry: EscalationExpiry = Field(alias="onExpiry")
    policy: EscalationPolicy = "person"
    state: EscalationState = "pending"
    resolution: Resolution | None = None
    seq: int = 0

    @field_validator("id")
    @classmethod
    def _id_shape(cls, v: str) -> str:
        if not is_escalation_id(v):
            raise InvalidInput(f"escalation id must be esc-<12 hex>: {v!r}")
        return v


class Escalation(_EscalationFields):
    """One pause: docket needs a decision from outside the task, kept as one durable record."""

    # ``legacy`` names the pause in the older fields the task still carries (``token`` of an
    # approval, ``questionId`` of a question), so a surface that knows only those keeps working.
    legacy: dict[str, Any] = Field(default_factory=dict)


class EscalationAffordances(BaseModel):
    """What a client may do with a pending escalation, without naming any surface's command."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    options: list[str] = Field(default_factory=list)
    accepts_text: bool = Field(False, alias="acceptsText")
    resolve_url: str = Field(alias="resolveUrl")


class EscalationView(_EscalationFields):
    """An escalation as a surface reads it: the record without ``legacy``, its ``state`` joined
    with the pause it names, and what can be done with it."""

    affordances: EscalationAffordances


class EscalationPage(BaseModel):
    """The escalations after a cursor; ``next`` is the ``seq`` to pass back as the next cursor."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    escalations: list[EscalationView] = Field(default_factory=list)
    next: int = 0


class InboxView(BaseModel):
    """The derived operator inbox: everything that needs a human, plus recent context."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    needs_you: list[TaskView | ApprovalView] = Field(default_factory=list, alias="needsYou")
    failed: list[TaskView] = Field(default_factory=list)
    done_since: list[TaskView] = Field(default_factory=list, alias="doneSince")
    running: list[TaskView] = Field(default_factory=list)
    next: str | None = None
    escalations: list[EscalationView] = Field(default_factory=list)


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
        raise InvalidInput(f"unknown event kind: {kind!r}")
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
