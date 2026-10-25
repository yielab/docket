from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    ValidationInfo,
    ValidatorFunctionWrapHandler,
    field_serializer,
    field_validator,
    model_validator,
)

from docket.kernel import clock as _clock
from docket.kernel import handoff as _handoff
from docket.kernel import ids as _ids
from docket.kernel.brief import TaskBrief
from docket.kernel.errors import DispatchError
from docket.kernel.operator_contract import Question, QuestionV11
from docket.tasks.domain.options import TaskGate, TaskRestrictions
from docket.tasks.domain.parts import (
    Answer,
    ConsultAnswer,
    Grant,
    Prepared,
    TaskGrant,
    TaskUsage,
    Worktree,
    is_none,
)
from docket.tasks.domain.state import Status

# The Reviewer/Tester verdict patterns live in exactly one place:
# `pipeline/domain/spec.py`'s `default_pipeline()` declares them as real `VerdictGate`s, and gate
# execution reads a step's *resolved* gate generically (see `execute_unit`'s
# `isinstance(gate, _pipeline.VerdictGate)` branch and `pipeline.domain.plan.parse_verdict`)
# instead of branching on a hardcoded role name. A second, independent copy of these patterns
# here would drift from that single source of truth (see `tests/unit/pipeline/domain/test_spec__spec.py`).


class TaskNotFoundError(DispatchError):
    """The pod has no such task, or the thing asked about (a task branch) is gone."""


class TaskRestrictionError(DispatchError):
    """An enqueue asked for a restriction that would widen the pod's limits."""


class HopResult(BaseModel):
    """One agent turn within a task's pipeline; its alias dump is the persisted hop."""

    # A partly invalid stored hop degrades each of artifact, verify, evidence, usage, trace and
    # repo_files alone to its default, so one old bad hop never refuses its task
    # (pod-dispatch.spec.md, "Structured handoff artifacts" and "Hop evidence").

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    role: str = ""
    member_id: str = Field("", alias="member")
    ok: bool = False
    output: str = ""
    cost_usd: float = Field(0.0, alias="costUsd")
    error: str = ""
    # Total agent-turn attempts made for this hop (1 = succeeded or failed on the first try, no
    # retry). Only retryable failures (see ``_RETRYABLE_FAILURE_KINDS``) ever push this above 1.
    attempts: int = 1
    # The pipeline-spec step id this hop ran for. Empty when constructed without one; the dump
    # writes ``role`` then -- the built-in default pipeline's step ids equal their role names, so
    # this is only a real distinction for a custom pipeline whose step id differs from its target
    # role (see ``_replay_pipeline_position``).
    step_id: str = Field("", alias="stepId")
    # This hop's structured handoff artifact. ``None`` at construction is backfilled to
    # ``HandoffArtifact.from_output(output)``, so every ``HopResult`` carries a real artifact.
    artifact: _handoff.HandoffArtifact | None = None
    # A mechanical gate whose command was unset -- a real, intentional "no check configured" state,
    # not a failure. Application code never prints; this flag is this run's own in-memory signal
    # only (never persisted) for ``interfaces/cli``'s dispatch renderer to print the notice.
    verification_skipped: bool = Field(False, exclude=True)
    # Set only on a hop whose gate outcome was routed via the step's own ``on`` map (see
    # ``_route_outcome``): the resolved target -- an earlier or later step id, or the literal
    # ``"fail"``/``"stop"``. ``None`` for an ordinary hop. Persisted so
    # ``_replay_pipeline_position`` can follow the same routing decision on resume.
    next_step: str | None = Field(None, alias="nextStep")
    # True only for a hop whose in-turn tool call parked mid-turn (ADR 0016 SS2): an attempt, not a
    # real outcome. Persisted so ``_replay_pipeline_position`` resumes by re-running this index.
    parked: bool = False
    # Real evidence from this hop's mechanical verify gate (``_evaluate_mechanical_gate``):
    # ``{"cmd", "exitCode", "durationS", "outputTail"}``, or ``None`` for a hop with no verify gate,
    # or one whose gate had no ``verifyCmd`` configured (see ``verification_skipped``).
    # ``outputTail`` is already redacted.
    verify: dict[str, Any] | None = None
    # Real git evidence for an Implementer hop, from ``_hop_diff_probe``:
    # ``{"commit", "baseCommit", "diffStat"}``, or ``None`` for a non-Implementer hop or one whose
    # member checkout is not a git repository. Each inner field independently degrades to ``None``.
    evidence: dict[str, Any] | None = None
    # Measured endpoint tokens for this hop's turn, ``{"input", "output"}``, or ``None`` when the
    # driver reported none. Never an estimate. See pod-dispatch.spec.md, "Evidence v1".
    usage: dict[str, int] | None = None
    # The hop's trace link, ``{"project", "session", "firstTs", "lastTs"}``: the session id the
    # hop's events were written under and the window they fall in. ``None`` when tracing is off.
    trace: dict[str, str] | None = None
    # Repository files this hop's turn composed from the task's base commit, repository-relative
    # path -> sha256 (``TurnResult.repo_files``). Empty when the turn read the filesystem.
    repo_files: dict[str, str] = Field(default_factory=dict, alias="repoFiles")
    # The served model as ``<provider>/<model id>`` and its catalog provider, or ``""`` while the
    # runtime driver reports no served model (pod-dispatch.spec.md, "Hop events and task usage").
    model: str = ""
    provider: str = ""

    @field_validator("artifact", mode="before")
    @classmethod
    def _known_artifact_keys(cls, value: Any) -> Any:
        # An artifact stored before a key was retired (``notes``) keeps the rest of its content.
        if isinstance(value, dict):
            return {k: v for k, v in value.items() if k in _handoff.HandoffArtifact.model_fields}
        return value

    @field_validator("artifact", "verify", "evidence", "usage", "trace", "repo_files", mode="wrap")
    @classmethod
    def _degrade_alone(
        cls, value: Any, handler: ValidatorFunctionWrapHandler, info: ValidationInfo
    ) -> Any:
        try:
            return handler(value)
        except ValidationError:
            field = cls.model_fields[str(info.field_name)]
            return field.get_default(call_default_factory=True)

    @model_validator(mode="after")
    def _artifact_from_output(self) -> HopResult:
        if self.artifact is None:
            self.artifact = _handoff.HandoffArtifact.from_output(self.output)
        return self

    @field_serializer("cost_usd")
    def _round_cost(self, value: float) -> float:
        return round(value, 6)

    @field_serializer("step_id")
    def _step_id_or_role(self, value: str) -> str:
        return value or self.role

    @field_serializer("artifact")
    def _dump_artifact(self, value: _handoff.HandoffArtifact | None) -> dict[str, Any] | None:
        return value.model_dump() if value is not None else None

    @field_serializer("repo_files")
    def _empty_files_are_null(self, value: dict[str, str]) -> dict[str, str] | None:
        return value or None


@dataclass
class TaskResult:
    """Outcome of driving one task through the whole pipeline."""

    task_id: str
    status: (
        str  # "done" | "failed" | "blocked" | "waiting_approval" | "waiting_input" | "cancelled"
    )
    reason: str = ""
    hops: list[HopResult] = field(default_factory=list)
    # Only meaningful when status == "waiting_approval" — the token the
    # gate created and the pipeline position it stopped at, so the caller
    # (``_apply_result``) can persist enough to resume correctly on a grant.
    approval_token: str = ""
    pending_approval_index: int | None = None
    # Only meaningful when status == "waiting_input" -- the minted ``Question``
    # (operator_contract, dumped by alias), so the caller (``_apply_result``) can
    # persist it for `hops.application.answers.answer_task` to resolve later. See
    # pod-dispatch.spec.md ("Operator input steps and answers").
    question: dict[str, Any] | None = None
    # Only meaningful when status == "failed" -- see RESUMABLE_FAILURE_KINDS.
    # Empty for an ordinary graded hop/gate failure (``_apply_result`` then
    # clears any stale persisted ``failureKind`` instead of writing this).
    failure_kind: str = ""
    # Only meaningful when status == "blocked" -- a short machine-readable code
    # (currently only ever "resources", ADR 0016 §4) distinct from `reason`'s free text,
    # so `operator_contract.a2a_state`'s AUTH_REQUIRED check has something stable to key
    # on. Empty for every other blocked cause (e.g. budget auto-pause), which `_apply_result`
    # then falls back to `reason` for, unchanged from before this field existed.
    blocked_reason: str = ""
    # Only meaningful when status == "waiting_approval" for a `check_changed` approval: the
    # protected paths the task's diff touched, persisted as the task's `checkChanged`.
    check_changed: list[str] = field(default_factory=list)

    @property
    def cost_usd(self) -> float:
        return round(sum(h.cost_usd for h in self.hops), 6)


def _is_empty(value: object) -> bool:
    return not value


class TaskRecord(BaseModel):
    """One task of a pod's queue; its alias dump is the stored record."""

    # One rule for absent against null. A key the queue always writes (startedAt, approvalToken,
    # hops, pregrants, ...) dumps even when unset; every other key is absent until something writes
    # it and absent again after a drop (exclude_if), never null or []. No global exclude_none or
    # exclude_unset: either would drop a key of the first kind.
    #
    # An unknown key is ignored on read and not written back, so a queue written before a key was
    # retired (claimId, source) still loads; one stray key never makes the whole queue unreadable.
    model_config = ConfigDict(extra="ignore", populate_by_name=True, validate_assignment=True)

    # The request: what was enqueued.
    id: str = Field(default_factory=lambda: _ids.new_id("task"))
    description: str
    priority: str = "normal"
    created: str = Field(default_factory=_clock.iso)
    channel: str = Field("", exclude_if=_is_empty)
    brief: TaskBrief | None = Field(None, exclude_if=is_none)
    external_ref: str | None = Field(None, alias="externalRef", exclude_if=is_none)
    idempotency_key: str | None = Field(None, alias="idempotencyKey", exclude_if=is_none)
    base_ref: str | None = Field(None, alias="baseRef", exclude_if=is_none)
    pipeline: str | None = Field(None, exclude_if=is_none)
    gate: TaskGate | None = Field(None, exclude_if=is_none)
    max_tokens: int | None = Field(None, alias="maxTokens", exclude_if=is_none)
    prepare: str | None = Field(None, exclude_if=is_none)
    restrictions: TaskRestrictions | None = Field(None, exclude_if=is_none)
    # The level its pauses are decided at, as asked at enqueue; unset takes the profile's default.
    autonomy: str | None = Field(None, exclude_if=is_none)

    # The lifecycle: where the task stands.
    status: Status = Status.pending
    started_at: str | None = Field(None, alias="startedAt")
    completed_at: str | None = Field(None, alias="completedAt")
    claimed_at: str | None = Field(None, alias="claimedAt")
    claim_pid: int | None = Field(None, alias="claimPid", exclude_if=is_none)
    reason: str = ""
    failure_kind: str | None = Field(None, alias="failureKind", exclude_if=is_none)
    blocked_reason: str | None = Field(None, alias="blockedReason", exclude_if=is_none)
    approval_token: str | None = Field(None, alias="approvalToken")
    pending_approval_index: int | None = Field(None, alias="pendingApprovalIndex")
    # Single-use handoff from a grant to the next claim of this task: read and cleared by that
    # claim, so it never leaks into an unrelated later one.
    gate_override_pipeline_index: int | None = Field(None, alias="gateOverridePipelineIndex")
    question: QuestionV11 | Question | None = Field(None, exclude_if=is_none)
    consult_answer: ConsultAnswer | None = Field(None, alias="consultAnswer", exclude_if=is_none)

    # The execution: what running it produced.
    hops: list[HopResult] = Field(default_factory=list)
    cost_usd: float = Field(0.0, alias="costUsd")
    worktree: Worktree | None = Field(None, exclude_if=is_none)
    prepared: Prepared | None = Field(None, exclude_if=is_none)
    # Validated where it is used: the domain may not import ``pipeline``.
    pipeline_spec: dict[str, Any] | None = Field(None, alias="pipelineSpec", exclude_if=is_none)
    pipeline_source: str | None = Field(None, alias="pipelineSource", exclude_if=is_none)
    gate_applied: bool | None = Field(None, alias="gateApplied", exclude_if=is_none)
    usage: TaskUsage | None = Field(None, exclude_if=is_none)
    check_changed: list[str] = Field(
        default_factory=list, alias="checkChanged", exclude_if=_is_empty
    )
    consultations: int = Field(0, exclude_if=_is_empty)
    answers: list[Answer] = Field(default_factory=list, exclude_if=_is_empty)
    pregrants: list[Grant] = Field(default_factory=list)
    task_grants: list[TaskGrant] = Field(
        default_factory=list, alias="taskGrants", exclude_if=_is_empty
    )
    # The ids of the escalation records opened for this task, oldest first.
    escalations: list[str] = Field(default_factory=list, exclude_if=_is_empty)

    @property
    def worktree_dir(self) -> str:
        """The task worktree's directory while it exists, else ``""`` (none made, or pruned)."""
        wt = self.worktree
        return wt.dir if wt is not None and wt.dir and not wt.pruned_at else ""

    @property
    def is_terminal(self) -> bool:
        return self.status in Status.TERMINAL

    @property
    def approved_ready(self) -> bool:
        """A pending task a human already approved: a pre-grant or a gate override is waiting."""
        return self.status == Status.pending and (
            bool(self.pregrants) or self.gate_override_pipeline_index is not None
        )

    @property
    def question_is_consultation(self) -> bool:
        """Whether the parked question is one an agent asked (a clarification or a decision)."""
        return self.question is not None and getattr(self.question, "kind", None) in (
            "clarification",
            "decision",
        )


class TaskRunRefusal(DispatchError):
    """A claimed task's own ``pipeline`` or ``gate`` cannot be honoured; the task settles failed."""
