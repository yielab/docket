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
from docket.kernel.errors import DispatchError

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
    """One agent turn within a task's pipeline.

    Its dump (``model_dump(by_alias=True)``) is the persisted hop (pod-dispatch.spec.md,
    "Structured handoff artifacts" and "Hop evidence"). A stored hop that is partly invalid
    degrades each of ``artifact``, ``verify``, ``evidence``, ``usage``, ``trace`` and
    ``repo_files`` alone to its default, so one old bad hop never refuses its task."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

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


# Fields a task record may lack because enqueue_task_once does not write them.
# ``hops`` is handled separately below — a shared mutable default would leak
# the same list object across every backfilled task.
_TASK_SCALAR_DEFAULTS: dict[str, Any] = {
    "priority": "normal",
    "status": "pending",
    "startedAt": None,
    "completedAt": None,
    "source": "operator",
    "reason": "",
    "costUsd": 0.0,
    "claimId": None,
    "claimedAt": None,
    # Set together when a require_approval gate fires (status ->
    # "waiting_approval"); cleared on resolution (grant or deny) — see
    # `_apply_result`/`resolve_waiting_approval`.
    "approvalToken": None,
    "pendingApprovalIndex": None,
    # Single-use gate-override handoff from a grant to the *next* claim
    # of this task — captured then cleared from storage atomically inside
    # `_claim_next_task` so it can never leak into an unrelated later claim.
    "gateOverridePipelineIndex": None,
}


def _normalize_task(task: dict[str, Any]) -> dict[str, Any]:
    """Fill every field ``enqueue_task_once`` does not write onto a task dict, in place (returns it)."""
    for key, default in _TASK_SCALAR_DEFAULTS.items():
        task.setdefault(key, default)
    if not isinstance(task.get("hops"), list):
        task["hops"] = []
    # Single-use pre-grants a human has already resolved for this task's exact
    # parked call(s) (ADR 0016 SS2) -- `resolve_waiting_approval` appends,
    # `_compose_hop` serialises unconsumed entries into the resumed hop's env.
    # A fresh list per task for the same reason `hops` gets one above.
    if not isinstance(task.get("pregrants"), list):
        task["pregrants"] = []
    task.setdefault("created", _clock.iso())
    task.setdefault("id", _ids.new_id("task"))
    return task


class TaskRunRefusal(DispatchError):
    """A claimed task's own ``pipeline`` or ``gate`` cannot be honoured; the task settles failed."""
