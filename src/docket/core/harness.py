"""The harness-mode contract: pure models and pure functions, no CLI.

``HarnessEvent``/``HarnessResult`` are the versioned wire shapes an outside
caller pins against; ``preflight``/``agent_meta_for``/``result_from`` are
the pure helpers the future ``docket harness`` command composes. Nothing
here touches a filesystem, an environment store, or stdout, so it stays
free to import from either the CLI distribution or the runtime closure.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from docket.core.archetypes import BUILTIN_ARCHETYPES
from docket.core.models import AgentKind, AgentMeta

if TYPE_CHECKING:
    from docket.core.runtime_driver import TurnResult, UsageReport

# Bump only for a breaking change to the wire shape below -- an outside
# repository pins the generated JSON Schema against this exact string.
HARNESS_CONTRACT_VERSION = "1.0.0"

# A second, opt-in wire contract alongside the unchanged v1.0 one above --
# the v1.0 classes below are untouched, so a caller pinned to them sees no
# change; process lifecycle events, stdin answers, file reporting and
# recipe runs are declared here but not yet produced by any live path.
HARNESS_CONTRACT_V11 = "1.1.0"
HARNESS_CONTRACT_VERSIONS = (HARNESS_CONTRACT_VERSION, HARNESS_CONTRACT_V11)

HarnessResultStatus = Literal["ok", "failed", "blocked", "cancelled", "refused"]
# `docket harness status TOKEN`'s three answers -- a later command's own
# concern, named here because the contract's status vocabulary is one document.
HarnessRunState = Literal["live", "finished", "unknown"]


class _VersionedEnvelope(BaseModel):
    """Shared base: every harness model pins ``v`` to the one supported version."""

    v: str = HARNESS_CONTRACT_VERSION

    # A fixture or wire payload naming any other version must fail validation
    # rather than being tolerated -- there is exactly one supported contract
    # version at a time, and the schema is only ever pinned to it.
    @field_validator("v")
    @classmethod
    def _known_version(cls, value: str) -> str:
        if value != HARNESS_CONTRACT_VERSION:
            raise ValueError(f"unsupported harness contract version: {value!r}")
        return value


class HarnessEvent(_VersionedEnvelope):
    """One streamed line: docket's trace vocabulary inside a versioned envelope."""

    token: str
    seq: int
    ts: str
    # The exact record core.trace.trace_event produced (or would produce)
    # for this line -- not a second, harness-specific event vocabulary.
    # Stated explicitly: older pydantic 2.x omits it, and the committed schema
    # must render byte-identically at the dependency floor.
    event: dict[str, Any] = Field(json_schema_extra={"additionalProperties": True})


class _VersionedEnvelopeV11(BaseModel):
    """1.1 sibling of ``_VersionedEnvelope``, pinned to ``"1.1.0"`` exactly --
    a separate base, not a parameterized one, keeps v1.0's schema byte-identical."""

    v: str = HARNESS_CONTRACT_V11

    @field_validator("v")
    @classmethod
    def _known_version(cls, value: str) -> str:
        if value != HARNESS_CONTRACT_V11:
            raise ValueError(f"unsupported harness contract version: {value!r}")
        return value


class HarnessEventV11(_VersionedEnvelopeV11):
    """1.1 sibling of ``HarnessEvent``. Same shape -- a process lifecycle
    event type needs no new field here, since ``event`` is an open dict."""

    token: str
    seq: int
    ts: str
    event: dict[str, Any] = Field(json_schema_extra={"additionalProperties": True})


class BlockedInfo(BaseModel):
    """Which policy rule stopped the run, when ``status`` is ``"blocked"``."""

    tool: str = ""
    call_id: str = ""
    denial_kind: str = ""
    policy_id: str = ""
    reason: str = ""


class ModelInfo(BaseModel):
    """What the caller asked for versus what actually answered the last request."""

    requested: str = ""
    served: str = ""


class UsageInfo(BaseModel):
    """Measured token counts for the whole run -- never a dollar figure."""

    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    turns: int = 0


class HarnessResult(_VersionedEnvelope):
    """The one terminal object a harness run ends with, on stdout, once."""

    token: str
    status: HarnessResultStatus
    stop_reason: str = ""
    error: str = ""
    blocked: BlockedInfo | None = None
    model: ModelInfo
    usage: UsageInfo
    cost_usd: None = None
    run_state: str = ""


class FileChange(BaseModel):
    """One file a harness run touched, for ``HarnessResultV11.files``."""

    path: str
    op: Literal["write", "edit", "delete", "unknown"]


class Answer(BaseModel):
    """One resolution to a paused approval or question, in the MCP elicitation
    shape (``action``/``content``): a caller's answer to something the run asked."""

    approvalToken: str | None = None
    questionId: str | None = None
    action: Literal["accept", "decline", "cancel"]
    content: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _exactly_one_target(self) -> Answer:
        if (self.approvalToken is None) == (self.questionId is None):
            raise ValueError("exactly one of approvalToken or questionId must be set")
        return self


class AnswerLine(_VersionedEnvelopeV11):
    """One caller-supplied stdin line answering a paused approval or question."""

    token: str
    answer: Answer


class HarnessTask(BaseModel):
    """Recipe/task-run state a v1.1 result can carry."""

    status: str
    hops: list[dict[str, Any]] = Field(default_factory=list)
    evidence: dict[str, Any] | None = None
    brief: dict[str, Any] | None = None


class Limits(BaseModel):
    """Caller-declared ceilings, echoed back on the result."""

    maxTokens: int | None = None


class HarnessResultV11(_VersionedEnvelopeV11):
    """The 1.1 terminal result: every v1.0 field, plus files/task/limits.
    The empty defaults below are not yet populated by any live path."""

    token: str
    status: HarnessResultStatus
    stop_reason: str = ""
    error: str = ""
    blocked: BlockedInfo | None = None
    model: ModelInfo
    usage: UsageInfo
    cost_usd: None = None
    run_state: str = ""
    files: list[FileChange] = Field(default_factory=list)
    task: HarnessTask | None = None
    limits: Limits = Field(default_factory=Limits)


@dataclass(frozen=True)
class Refusal:
    """Why harness mode exits before any run starts (exit code 2)."""

    reason: str


# No run token exists yet at refusal time -- preflight (and the command's
# own pre-preflight argument checks) fire before create_run -- so every
# field but status/error stays at its empty default.
def refusal_result(
    reason: str, *, version: str = HARNESS_CONTRACT_VERSION
) -> HarnessResult | HarnessResultV11:
    """The one ``HarnessResult`` a refused run ever prints (exit code 2)."""
    if version == HARNESS_CONTRACT_V11:
        return HarnessResultV11(
            v=HARNESS_CONTRACT_V11,
            token="",
            status="refused",
            error=reason,
            model=ModelInfo(),
            usage=UsageInfo(),
        )
    return HarnessResult(
        token="",
        status="refused",
        error=reason,
        model=ModelInfo(),
        usage=UsageInfo(),
    )


def preflight(environ: Mapping[str, str], home_default: Path, workspace: Path) -> Refusal | None:
    """Refuse to run, or clear the caller to proceed, without touching global state."""
    # Measured against the caller's own environ, never docket.config globals,
    # so this stays pure and testable without repointing process-wide state.
    home_raw = environ.get("DOCKET_HOME", "").strip()
    if not home_raw:
        return Refusal("DOCKET_HOME is not set; harness mode never runs against the default home")

    home = Path(home_raw).expanduser()
    try:
        resolved_home = home.resolve()
        resolved_default = home_default.expanduser().resolve()
    except OSError:
        resolved_home, resolved_default = home, home_default
    if resolved_home == resolved_default:
        return Refusal(
            f"DOCKET_HOME resolves to the default home ({resolved_default}); "
            "harness mode requires a caller-owned home"
        )

    if not environ.get("DOCKET_LLM_BASE_URL", "").strip():
        return Refusal(
            "DOCKET_LLM_BASE_URL is required; harness mode never falls back to a stored provider"
        )

    if environ.get("DOCKET_NO_TRACE", "") == "1":
        return Refusal("DOCKET_NO_TRACE=1 would run harness mode unobserved; refused")

    if not workspace.is_dir():
        return Refusal(f"workspace is not a directory: {workspace}")

    return None


def agent_meta_for(
    agent_id: str, workspace: Path, model: str, role: str = "implementer"
) -> AgentMeta:
    """Build the minimal ``.docket-meta.json`` a harness run's driver call requires."""
    # DocketDriver.run_turn derives its tool roots from codebase and refuses
    # a turn with no meta at all: this is registration in a caller-owned,
    # disposable home, never a provisioned workspace. A role that cannot
    # write is a usage error -- harness mode's one job is to make an edit.
    archetype = BUILTIN_ARCHETYPES.get(role)
    if archetype is None or "write" in archetype.denied_tools:
        raise ValueError(f"role {role!r} cannot write; harness mode requires a writing role")
    return AgentMeta(
        kind=AgentKind.project,
        codebase=str(workspace),
        model=model,
        role=role,
        name=agent_id,
    )


# A refused approval reaches TurnResult only as a plain error string --
# TurnResult carries no structured denial field. This extracts the
# tool/call/policy/reason back out of that string using the `key=value`
# convention (bare or quoted values) core/tools.py already uses for its own
# audit strings. The exact producer of that string is owned elsewhere; treat
# this parser as a named integration point to re-check once that side lands.
_FIELD_RE_TEMPLATE = r"\b{key}=(?:'([^']*)'|\"([^\"]*)\"|(\S+))"


def _extract_field(text: str, *keys: str) -> str:
    """Return the first ``key=value`` match among *keys*, or ``""``."""
    for key in keys:
        match = re.search(_FIELD_RE_TEMPLATE.format(key=re.escape(key)), text)
        if match:
            return next((g for g in match.groups() if g is not None), "")
    return ""


def result_from(turn: TurnResult, usage: UsageReport, run: dict[str, Any]) -> HarnessResult:
    """Translate one driver outcome into the published, versioned result."""
    # Status precedence: a genuinely completed turn is "ok"; a cooperative
    # cancellation is "cancelled"; a refused approval is "blocked" with the
    # parsed rule; anything else is "failed". "refused" is never produced
    # here -- it comes from preflight, before a TurnResult exists at all.
    if turn.ok:
        status: HarnessResultStatus = "ok"
    elif turn.failure_kind == "run_cancelled":
        status = "cancelled"
    elif "approval_unavailable" in (turn.error or ""):
        status = "blocked"
    else:
        status = "failed"

    blocked = None
    if status == "blocked":
        error = turn.error or ""
        blocked = BlockedInfo(
            tool=_extract_field(error, "tool"),
            call_id=_extract_field(error, "call_id", "callId", "call"),
            denial_kind="approval_unavailable",
            policy_id=_extract_field(error, "policy_id", "policyId"),
            reason=_extract_field(error, "reason") or error,
        )

    totals = usage.totals
    variables = run.get("variables") or {}
    served = turn.raw.get("model") if isinstance(turn.raw, dict) else None

    return HarnessResult(
        token=str(run.get("id", "")),
        status=status,
        stop_reason=turn.failure_kind or "",
        error=turn.error or "",
        blocked=blocked,
        model=ModelInfo(
            requested=str(variables.get("model", "")),
            served=str(served) if served else "",
        ),
        usage=UsageInfo(
            input_tokens=totals.input_tokens,
            output_tokens=totals.output_tokens,
            cached_tokens=totals.cache_read,
            turns=totals.turns,
        ),
        cost_usd=None,
        run_state=str(run.get("state", "")),
    )


def result_from_v11(
    turn: TurnResult,
    usage: UsageReport,
    run: dict[str, Any],
    *,
    files: Sequence[FileChange] = (),
    task: HarnessTask | None = None,
    limits: Limits | None = None,
) -> HarnessResultV11:
    """The v1.1 sibling of ``result_from``: same status/blocked/usage mapping,
    reused rather than re-derived, plus the caller-supplied v1.1-only fields."""
    base = result_from(turn, usage, run)
    return HarnessResultV11(
        v=HARNESS_CONTRACT_V11,
        token=base.token,
        status=base.status,
        stop_reason=base.stop_reason,
        error=base.error,
        blocked=base.blocked,
        model=base.model,
        usage=base.usage,
        cost_usd=base.cost_usd,
        run_state=base.run_state,
        files=list(files),
        task=task,
        limits=limits if limits is not None else Limits(),
    )
