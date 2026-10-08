"""Pod pipeline dispatch: drives queued tasks through lead -> implementer -> reviewer -> tester,
one real agent turn per present role, with a trace event and budget check per hop. Always within
a single pod; invoked only by an explicit trigger or the opt-in ``serve --dispatch`` loop.
Behavioral contract: specs/functional/pod-dispatch.spec.md (claiming, crash recovery, retries,
timeouts, budget/auto-pause, require_approval/``waiting_approval``, verify/verdict/PASS-FAIL
gates) and specs/functional/security-gates.spec.md (``pre_input``/``pre_output``/``pre_tool_call``).
Load-bearing points not obvious from either: a ``claimId`` is identifying only -- the concurrency
guarantee is the filelock held for the whole claim read-modify-write, never a claimId comparison.
``pre_input`` fires once at enqueue, not per hop, so incoming text cannot re-trip a ``"*"``-scoped
policy at every role. ``pod_gating_cost``'s token estimate is gating-only, never recorded spend
(the driver can report ``cost_usd = 0.0``).
"""

from __future__ import annotations

import datetime as _dt
import fnmatch as _fnmatch
import hashlib as _hashlib
import json as _json
import os as _os
import re as _re
import time as _time
import uuid as _uuid
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote as _url_quote

from pydantic import ValidationError as _ValidationError

import docket.config as _cfg
from docket.core import approval as _ap
from docket.core import archetypes as _archetypes
from docket.core import audit as _audit
from docket.core import blueprints as _blueprints
from docket.core import consult as _consult
from docket.core import conversations as _conv
from docket.core import fleet as _fleet
from docket.core import handoff as _handoff
from docket.core import memory as _mem
from docket.core import models as _models
from docket.core import models_policy as _models_policy
from docket.core import operator_contract as _oc
from docket.core import orchestrator as _orch
from docket.core import pipeline as _pipeline
from docket.core import pod as _pod
from docket.core import pod_provisioning as _pp
from docket.core import policy as _policy
from docket.core import runs as _runs
from docket.core import runtime_driver as _rd
from docket.core import secrets as _secrets
from docket.core import security as _sec
from docket.core import trace as _trace
from docket.core import utils as _utils
from docket.edges import store as _store
from docket.edges.adapters import docket_runtime as _dr
from docket.edges.adapters import system as _sys

# Only roles the pod actually has run — lean pod (lead + implementer) = 2 hops; full pod = 4.
PIPELINE_ORDER: tuple[str, ...] = ("lead", "implementer", "reviewer", "tester")

# Injectable runner for tests (matches the RuntimeDriver port's ``run_turn`` signature). The
# 4th positional arg is always the *agent-turn* timeout (never the verify timeout).
Runner = Callable[[str, str, str, int, dict[str, str] | None], _rd.TurnResult]

DEFAULT_TIMEOUT = 300

# Only these TurnResult.failure_kind values are worth retrying — a
# transient hiccup running the turn. A non-zero exit or an unparseable/failing
# verdict is a real answer and must never be retried (retrying would risk
# masking a genuine failure as a transient one, and burns budget for nothing).
_RETRYABLE_FAILURE_KINDS: frozenset[str] = frozenset({"timeout", "daemon_error"})

# Priority sort key shared by task selection everywhere it matters.
_PRIORITY_RANK: dict[str, int] = {"high": 0, "normal": 1, "low": 2}

# `failed` task ``failureKind`` values ``--resume`` is allowed to reclaim (see
# ``_eligible_for_claim`` and pod-dispatch.spec.md "Claiming"): a swept crash
# (``stale_claim``) and a settled deterministic refusal (``dispatch_refused``,
# see ``dispatch_task``'s ``DispatchError`` handling). Neither is a graded
# hop/gate outcome, so neither is a "real gate/hop failure" in the sense
# "blocked and terminal-failure re-entry" uses that phrase for. Shared by
# ``cli/_pod.py``'s "anything to do?" gate so the two never drift apart.
RESUMABLE_FAILURE_KINDS: frozenset[str] = frozenset({"stale_claim", "dispatch_refused"})


def step_session_key(member_id: str, project: str, task_id: str, step_id: str) -> str:
    """Collision-free durable-history key (member + globally-unique step id) so repeated
    roles and parallel children never replay each other's raw turns.
    """
    member = _url_quote(member_id, safe="")
    project_part = _url_quote(project, safe="")
    task = _url_quote(task_id, safe="")
    step = _url_quote(step_id, safe="")
    return f"agent:{member}:{project_part}:task:{task}:step:{step}"


# The Reviewer/Tester verdict patterns live in exactly one place:
# `core/pipeline.py`'s `default_pipeline()` declares them as real `VerdictGate`s, and gate
# execution reads a step's *resolved* gate generically (see `_execute_unit`'s
# `isinstance(gate, _pipeline.VerdictGate)` branch and `core.orchestrator.parse_verdict`)
# instead of branching on a hardcoded role name. A second, independent copy of these patterns
# here would drift from that single source of truth (see `tests/unit/core/test_pipeline__spec.py`).


class DispatchError(Exception):
    """A pod cannot be dispatched (no pod, no lead, …)."""


@dataclass
class HopResult:
    """One agent turn within a task's pipeline."""

    role: str
    member_id: str
    ok: bool
    output: str = ""
    cost_usd: float = 0.0
    error: str = ""
    # Total agent-turn attempts made for this hop (1 = succeeded or failed on
    # the first try, no retry). Only retryable failures (see
    # ``_RETRYABLE_FAILURE_KINDS``) ever push this above 1.
    attempts: int = 1
    # The pipeline-spec step id this hop ran for. Defaults to "" when
    # constructed without one; ``_hop_record``/``_hop_from_record`` backfill it
    # to ``role`` on both write and read -- the built-in default pipeline's step
    # ids equal their role names, so this is only a real distinction for a
    # custom pipeline whose step id differs from its target role (see
    # ``_replay_pipeline_position``).
    step_id: str = ""
    # This hop's structured handoff artifact. ``None`` at construction
    # time backfills in ``__post_init__`` to ``HandoffArtifact.from_output(output)``,
    # so every ``HopResult`` carries a real artifact once constructed.
    artifact: _handoff.HandoffArtifact | None = None
    # A mechanical gate whose command was unset — a real, intentional "no
    # check configured" state, not a failure. ``core/`` never prints; this
    # flag is this run's own in-memory signal only (not persisted — see
    # ``_hop_record``) for ``cli/``'s dispatch renderer to print the notice.
    verification_skipped: bool = False
    # Set only on a hop whose gate outcome was routed via the step's own
    # ``on`` map (see ``_route_outcome``): the resolved target -- an earlier
    # or later step id, or the literal ``"fail"``/``"stop"``. ``None`` for an
    # ordinary hop. Persisted so ``_replay_pipeline_position`` can follow the
    # same routing decision on resume instead of re-deriving it.
    next_step: str | None = None
    # True only for a hop whose in-turn tool call parked mid-turn (ADR 0016
    # SS2, ``_persist_hop_and_trace``'s ``_parked_approval_token``): an
    # attempt, not a real outcome. Persisted so ``_replay_pipeline_position``
    # resumes by re-running this exact index rather than advancing past it.
    parked: bool = False
    # Real evidence from this hop's mechanical verify gate (``_evaluate_mechanical_gate``):
    # ``{"cmd", "exitCode", "durationS", "outputTail", "touched"}`` (``touched`` = absolute paths
    # the verify command created or changed in a git checkout, internal: the harness drops them
    # from its ``files`` and never publishes the key), or ``None`` for a hop with no
    # verify gate, or one whose gate had no ``verifyCmd`` configured (see
    # ``verification_skipped``). ``exitCode`` is ``0``/``1`` (``run_verify_cmd`` itself
    # carries no numeric exit code to relay). ``outputTail`` is already redacted -- see
    # ``_evaluate_mechanical_gate``. ``_hop_record``/``_hop_from_record`` round-trip this
    # key; a record with no ``verify`` key at all defaults to ``None`` on read.
    verify: dict[str, Any] | None = None
    # Real git evidence for an Implementer hop, from ``_implementer_diff_probe``:
    # ``{"commit", "baseCommit", "diffStat"}``, or ``None`` for a non-Implementer hop or one
    # whose member checkout is not a git repository. Each inner field independently degrades
    # to ``None`` rather than raising. Round-tripped by ``_hop_record``/``_hop_from_record``
    # the same way as ``verify``.
    evidence: dict[str, Any] | None = None
    # Measured endpoint tokens for this hop's turn, ``{"input", "output"}``, or ``None`` when the
    # driver reported none. Never an estimate. See pod-dispatch.spec.md, "Evidence v1".
    usage: dict[str, int] | None = None
    # The hop's trace link, ``{"project", "session", "firstTs", "lastTs"}``: the session id the
    # hop's events were written under and the window they fall in. ``None`` when tracing is off.
    trace: dict[str, str] | None = None

    def __post_init__(self) -> None:
        if self.artifact is None:
            self.artifact = _handoff.HandoffArtifact.from_output(self.output)

    def rendered_artifact(self) -> str:
        """This hop's artifact rendered to text — never ``None`` after construction."""
        assert self.artifact is not None
        return self.artifact.render()


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
    # persist it for `core.answers.answer_task` to resolve later. See
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

    @property
    def cost_usd(self) -> float:
        return round(sum(h.cost_usd for h in self.hops), 6)


def _now() -> str:
    return _dt.datetime.now(_dt.UTC).isoformat()


def _parse_iso(ts: str) -> _dt.datetime | None:
    """Parse an ISO timestamp produced by ``_now()``; None on anything else."""
    if not ts:
        return None
    try:
        dt = _dt.datetime.fromisoformat(ts)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_dt.UTC)
    return dt


def pod_task_list_path(project: str) -> Path:
    """The pod's task queue lives in its Lead's workspace: one queue per pod, keyed by
    the Lead, so pods never share a task list.
    """
    lead_id = _pod.member_id(project, "lead")
    return _cfg.workspace_dir(lead_id) / "TASK_LIST.json"


# Fields a task record may lack because enqueue_task does not write them.
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
    """Fill every field ``enqueue_task`` does not write onto a task dict, in place (returns it)."""
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
    task.setdefault("created", _now())
    task.setdefault("id", f"task-{_uuid.uuid4()}")
    return task


def read_tasks(project: str) -> list[dict[str, Any]]:
    """Return the pod's task list ([] if the queue file is absent), normalized."""
    raw = _store.read_json(pod_task_list_path(project))
    tasks = raw.get("tasks") if isinstance(raw, dict) else None
    if not isinstance(tasks, list):
        return []
    return [_normalize_task(t) for t in tasks if isinstance(t, dict)]


def _enqueue_pre_input_gate(
    project: str, session_id: str, task_id: str, description: str, *, trusted: bool
) -> _policy.PolicyHit:
    """Evaluate ``pre_input`` once, at enqueue time; never raises. Unlike ``block``,
    ``require_approval`` does not synthesize a session_end -- the task still runs for real
    once granted. See specs/functional/security-gates.spec.md."""
    hit = _policy.policy_eval_detail("lead", "pre_input", description, trusted=trusted)
    if hit.action == "allow":
        return hit

    if hit.action == "block":
        _trace.trace_event(
            project,
            session_id,
            "lead",
            "session_start",
            _json.dumps({"source": "enqueue", "task": task_id}),
        )
    _trace.trace_event(
        project,
        session_id,
        "lead",
        "guardrail_check",
        _json.dumps({"hook": "pre_input", "policy": hit.policy_id, "action": hit.action}),
    )
    if hit.action == "block":
        _trace.trace_event(
            project,
            session_id,
            "lead",
            "guardrail_block",
            _json.dumps({"hook": "pre_input", "policy": hit.policy_id, "action": hit.action}),
        )
        _trace.trace_event(
            project,
            session_id,
            "lead",
            "session_end",
            _json.dumps({"status": "aborted", "reason": "guardrail_block"}),
        )
    return hit


def enqueue_task(
    project: str,
    description: str,
    priority: str = "normal",
    *,
    trusted: bool | None = None,
    brief: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Locked read-modify-write, so concurrent ``delegate`` calls cannot clobber each other's
    task. Raises DispatchError with no Lead workspace, an invalid *brief*, or a blocked
    ``pre_input`` (nothing persisted). ``trusted`` never overrides the persisted ``source``."""
    path = pod_task_list_path(project)
    if not path.parent.is_dir():
        raise DispatchError(f"no pod for '{project}' (run from its directory: docket init)")

    # *brief*, when given, is a pre-brief the operator already knows: validated as a
    # TaskBrief (invalid raises DispatchError, nothing persisted), folded into the enqueued
    # description under its own heading -- so the pre_input screen below covers it like any
    # other human-sent string, and the Lead's first hop sees it -- and stored on the task's
    # own `brief` field.
    parsed_brief: _oc.TaskBrief | None = None
    if brief is not None:
        try:
            parsed_brief = _oc.TaskBrief.model_validate(brief)
        except _ValidationError as exc:
            raise DispatchError(f"invalid brief: {exc}") from exc
        description = f"{description}\n\n## Pre-brief\n{_handoff.render_brief(parsed_brief)}"

    task_id = f"task-{_uuid.uuid4()}"
    source = "operator"
    session_id = f"agent:{project}:{task_id}"
    effective_trusted = (source == "operator") if trusted is None else trusted

    hit = _enqueue_pre_input_gate(
        project, session_id, task_id, description, trusted=effective_trusted
    )
    if hit.action == "block":
        raise DispatchError(
            f"task rejected by guardrail policy '{hit.policy_id}' at enqueue"
            + (f": {hit.message}" if hit.message else "")
        )

    task: dict[str, Any] = {
        "id": task_id,
        "description": _trace.redact(description) if hit.action == "redact" else description,
        "priority": priority if priority in ("high", "normal", "low") else "normal",
        "status": "pending",
        "created": _now(),
        "startedAt": None,
        "completedAt": None,
        "source": source,
        "hops": [],
        "reason": "",
        "costUsd": 0.0,
        "claimId": None,
        "claimedAt": None,
    }
    if parsed_brief is not None:
        task["brief"] = parsed_brief.model_dump(by_alias=True)

    if hit.action == "require_approval":
        action_text = f"pod dispatch — task enqueue for '{project}': {description}"[:1000]
        token = _ap.approval_create(
            project, "lead", action_text, context={"taskId": task_id, "pipelineIndex": 0}
        )
        task["status"] = "waiting_approval"
        task["approvalToken"] = token
        task["pendingApprovalIndex"] = 0
        _trace.trace_event(
            project,
            session_id,
            "lead",
            "approval_required",
            _json.dumps(
                {"role": "lead", "token": token, "pipelineIndex": 0, "policy": hit.policy_id}
            ),
        )

    def _fn(doc: dict[str, Any]) -> dict[str, Any]:
        tasks_raw = doc.get("tasks")
        tasks = (
            [_normalize_task(t) for t in tasks_raw if isinstance(t, dict)]
            if isinstance(tasks_raw, list)
            else []
        )
        tasks.append(task)
        return {"tasks": tasks}

    _store.read_modify_write(path, _fn)
    return task


def pod_pipeline(project: str) -> list[tuple[str, str]]:
    """Present pod roles in pipeline order, as ``(role, member_id)``; raises DispatchError
    with no Lead. Duplicate implementers collapse to the first (one doer per role).
    """
    all_ids = [a.id for a in _fleet.list_agents()]
    members = _pod.members_of(all_ids, project)
    if not members:
        raise DispatchError(f"no pod found for '{project}'")
    by_role: dict[str, str] = {}
    for mid, role, _idx in members:
        by_role.setdefault(role, mid)  # first member of each role wins
    if "lead" not in by_role:
        raise DispatchError(f"pod '{project}' has no lead — cannot dispatch")
    return [(role, by_role[role]) for role in PIPELINE_ORDER if role in by_role]


def pod_full_roster(project: str) -> dict[str, str]:
    """Every role this pod has, first member per role (``role -> member_id``). Unlike
    :func:`pod_pipeline` (fixed to ``PIPELINE_ORDER``), this covers every role name so a
    custom :class:`~docket.core.pipeline.PipelineSpec` can target a non-legacy role."""
    all_ids = [a.id for a in _fleet.list_agents()]
    by_role: dict[str, str] = {}
    for mid, role, _idx in _pod.members_of(all_ids, project):
        by_role.setdefault(role, mid)
    return by_role


_BOUND_PIPELINE_SOURCE_PREFIX = "bound pipeline"


# Fails loud on a missing/unreadable copy, a hash mismatch (the copy changed on disk since
# it was bound), or a copy that no longer validates -- never a silent fall back to the
# blueprint/built-in pipeline (see pod-dispatch.spec.md, "Pipeline order and participation").
def _bound_pipeline(project: str, pipeline_hash: str) -> _pipeline.PipelineSpec:
    """Load this pod's bound pipeline copy, verified against *pipeline_hash*
    (the Lead's stored ``PodSettings.pipeline`` digest)."""
    path = _pod.bound_pipeline_path(project)
    rebind_hint = f"rebind with 'docket pod set pipeline <file> --pod {project}'"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise DispatchError(
            f"pod '{project}' has a bound pipeline (hash {pipeline_hash[:12]}...) but its "
            f"stored copy at {path} is unreadable ({exc}) -- {rebind_hint}"
        ) from exc
    actual_hash = _hashlib.sha256(text.encode("utf-8")).hexdigest()
    if actual_hash != pipeline_hash:
        raise DispatchError(
            f"pod '{project}'s bound pipeline copy at {path} no longer matches its recorded "
            f"hash (expected {pipeline_hash[:12]}..., found {actual_hash[:12]}...) -- {rebind_hint}"
        )
    result = _pipeline.load_pipeline(text)
    if result.spec is None:
        raise DispatchError(
            f"pod '{project}'s bound pipeline copy at {path} no longer validates: "
            f"{'; '.join(result.errors)} -- {rebind_hint}"
        )
    return result.spec


# Resolution order: this pod's bound pipeline (PodSettings.pipeline) -> the Lead's
# ``blueprint`` meta's default_pipeline -> the built-in default. *source* is the
# human-readable label ``docket pod plan`` names ("bound pipeline (hash ...)",
# "blueprint '<name>'", or "built-in default" -- see pod-dispatch.spec.md, "Pipeline order
# and participation").
def _blueprint_pipeline(project: str) -> tuple[_pipeline.PipelineSpec, str]:
    """The resolved (spec, source) base pipeline for a caller-supplied-spec-free
    dispatch -- see the comment above for the resolution order."""
    settings = _pod_settings(project)
    if settings.pipeline:
        spec = _bound_pipeline(project, settings.pipeline)
        return spec, f"{_BOUND_PIPELINE_SOURCE_PREFIX} (hash {settings.pipeline[:12]}...)"
    lead_id = _pod.member_id(project, "lead")
    name = _fleet.meta_get(lead_id, "blueprint", "")
    if name:
        try:
            return _blueprints.get_blueprint(name).default_pipeline, f"blueprint '{name}'"
        except _blueprints.BlueprintError:
            pass  # absent/unknown blueprint -- fall through to the built-in default
    builtin = _pipeline.load_pipeline(None).spec
    assert builtin is not None  # load_pipeline(None) always succeeds
    return builtin, "built-in default"


def effective_pipeline_source(project: str) -> str:
    """The source label ``effective_pipeline(project, None)`` would resolve to
    -- see ``_blueprint_pipeline``; a caller-supplied ``--file`` never reaches this."""
    return _blueprint_pipeline(project)[1]


# A caller-supplied *spec* is never patched. A pod's bound pipeline is caller-supplied-like
# and is also never patched -- its own rework config wins, matching today's ``--file``
# semantics, since an operator who hand-wrote a custom rework edge did not ask for the pod's
# ``maxReworkCycles`` to override it. Only the blueprint/built-in default gets the patch.
def effective_pipeline(project: str, spec: _pipeline.PipelineSpec | None) -> _pipeline.PipelineSpec:
    """The PipelineSpec this dispatch actually runs (see pod-dispatch.spec.md,
    "Pipeline order and participation"). Public so ``cli/_pipeline.py`` renders
    this same resolved spec."""
    if spec is not None:
        return spec
    builtin, source = _blueprint_pipeline(project)
    if source.startswith(_BOUND_PIPELINE_SOURCE_PREFIX):
        return builtin
    configured = pod_max_rework_cycles(project)
    new_steps = []
    changed = False
    for step in builtin.steps:
        gate = step.gate
        if (
            isinstance(gate, _pipeline.VerdictGate)
            and gate.rework is not None
            and gate.rework.max_cycles != configured
        ):
            new_rework = gate.rework.model_copy(update={"max_cycles": configured})
            step = step.model_copy(update={"gate": gate.model_copy(update={"rework": new_rework})})
            changed = True
        new_steps.append(step)
    return builtin.model_copy(update={"steps": new_steps}) if changed else builtin


def pod_recorded_cost(project: str) -> float:
    """Sum each pod member's recorded USD spend (always 0.0 today — see ``pod_gating_cost``)."""
    all_ids = [a.id for a in _fleet.list_agents()]
    total = 0.0
    for mid, _role, _idx in _pod.members_of(all_ids, project):
        total += float(_utils.aggregate_cost(mid).cost_usd)
    return round(total, 6)


def _pod_settings(project: str) -> _pod.PodSettings:
    """Load this pod's validated Lead-meta settings, or raise ``DispatchError``
    naming the offending key -- never a silently substituted default (see
    ``core.pod.PodSettings``)."""
    try:
        return _pod.PodSettings.load_for(project)
    except _pod.PodSettingsError as exc:
        raise DispatchError(str(exc)) from exc


def pod_budget(project: str) -> float:
    """The pod's USD budget cap (Lead's ``budgetUsd``), 0.0 = unlimited."""
    return _pod_settings(project).budget_usd


def pod_max_rework_cycles(project: str) -> int:
    """Bounded rework budget for a REQUEST-CHANGES review: Lead's ``maxReworkCycles`` meta
    (default ``1``; ``0`` disables rework -- a hard gate, no retry). See pod-dispatch.spec.md
    ("Reviewer verdict gate and bounded rework")."""
    return _pod_settings(project).max_rework_cycles


def _retries_for_role(role: str) -> int:
    """Max retry attempts (after the first try) for one role's hop."""
    return _cfg.DISPATCH_RETRIES_PER_ROLE.get(role, _cfg.DISPATCH_RETRIES_DEFAULT)


def _lead_meta_timeout(project: str, field_name: str) -> int | None:
    """Read one already-validated timeout field off this pod's ``PodSettings``."""
    settings = _pod_settings(project)
    return settings.turn_timeout_s if field_name == "turnTimeoutS" else settings.verify_timeout_s


def pod_turn_timeout(project: str) -> int | None:
    """The pod's configured agent-turn timeout (Lead's ``turnTimeoutS``), if set."""
    return _lead_meta_timeout(project, "turnTimeoutS")


def pod_verify_timeout(project: str) -> int | None:
    """The pod's configured verifyCmd timeout (Lead's ``verifyTimeoutS``), if set."""
    return _lead_meta_timeout(project, "verifyTimeoutS")


def pod_approval_mode_is_set(project: str) -> bool:
    """Whether this pod's Lead meta carries its own explicit ``approvalMode`` (see
    ``pod_approval_mode``)."""
    # Reads the raw stored key directly, never a validated PodSettings value, since that
    # always carries the field default ("wait") once loaded -- indistinguishable from a
    # real "wait" unless the raw presence is checked first.
    lead_id = _pod.member_id(project, "lead")
    return bool(_fleet.meta_get(lead_id, "approvalMode", ""))


def pod_approval_mode(
    project: str, *, caller_default: Literal["wait", "park"] = "wait"
) -> Literal["wait", "park", "refuse"]:
    """The pod's configured unattended-approval posture: an explicit Lead ``approvalMode``
    always wins; an unset one resolves through *caller_default* instead of a fixed "wait"."""
    # ADR 0016 SS2: `serve --dispatch`'s sweep and a non-TTY foreground dispatch pass
    # "park", a TTY foreground dispatch passes "wait" -- see `_compose_hop`.
    if pod_approval_mode_is_set(project):
        return _pod_settings(project).approval_mode
    return caller_default


def _resolve_timeout(explicit: int | None, pod_value: int | None) -> int:
    """Timeout precedence: an explicit per-call override, else the pod's Lead-meta
    config, else ``DEFAULT_TIMEOUT`` (the fallback of last resort)."""
    if explicit is not None:
        return explicit
    if pod_value is not None:
        return pod_value
    return DEFAULT_TIMEOUT


def pod_gating_cost(project: str) -> tuple[float, bool]:
    """The pod's spend for budget-**gating**: recorded, or a token x pricing-table estimate
    (the driver always reports ``cost_usd = 0.0``). Returns ``(amount, estimated)`` -- never
    present the estimate as, or mix it into, recorded spend. See cost-tracking.spec.md."""
    recorded = pod_recorded_cost(project)
    if recorded > 0.0:
        return recorded, False

    all_ids = [a.id for a in _fleet.list_agents()]
    total_est = 0.0
    any_estimate = False
    for mid, _role, _idx in _pod.members_of(all_ids, project):
        # recorded == 0.0 above, so every member's own recorded spend is 0.0 too --
        # this always resolves through core/utils.py::gating_cost's estimate branch.
        est, estimated = _utils.gating_cost(mid)
        if estimated:
            total_est += est
            any_estimate = True
    return round(total_est, 6), any_estimate


def _pause_lead_for_budget(project: str) -> None:
    """Mark the pod's Lead paused once budget is reached, so ``_claim_next_task`` refuses
    every further claim (one write here, not a per-hop recheck) until an operator clears it
    (``docket run --resume``). Idempotent."""
    lead_id = _pod.member_id(project, "lead")
    _fleet.meta_set(lead_id, "paused", True)
    _fleet.meta_set(lead_id, "pausedReason", "budget")


@dataclass
class _HopComposition:
    """Per-hop prompt-composition stats, recorded via the ``context_composed`` trace event."""

    description_bytes: int
    sections: list[dict[str, Any]] = field(default_factory=list)
    total_bytes: int = 0
    truncated: bool = False


def _resolve_hop_instructions(
    role: str, project: str, rework_hop: HopResult | None, step_instructions: str
) -> str:
    """This role's own hop instruction text: the step's own override, else a built-in
    role's fixed text, else a custom role's registry-resolved ``hopInstruction``."""
    if step_instructions:
        return step_instructions
    if role == "implementer":
        return (
            "You are the Implementer. Address the reviewer's REQUEST-CHANGES "
            "above, then implement the change in the workspace."
            if rework_hop is not None
            else "You are the Implementer. Implement the change in the workspace."
        )
    if role == "reviewer":
        return (
            "You are the Reviewer. Review the diff (read-only). Start exactly one "
            "output line with APPROVE or REQUEST-CHANGES (case-insensitive); "
            "reasons may come before or after that marker line."
        )
    if role == "tester":
        return (
            "You are the Tester. Validate behaviour only. Start exactly one output "
            "line with PASS or FAIL (case-insensitive); evidence may come before or "
            "after that marker line."
        )
    # A custom role: its own archetype's `hopInstruction`, or one generated
    # from its `gateContract` (e.g. a verdict role's marker convention) --
    # see role-archetypes.spec.md ("Hop instructions"). An unrecognized
    # role name (absent from the registry) still gets no instruction,
    # matching today's behavior.
    archetype = _archetypes.load_registry(project).get(role)
    return _archetypes.resolve_hop_instruction(archetype) if archetype else ""


def _latest_brief_hop_index(prior: list[HopResult]) -> int | None:
    """The most recent prior hop whose artifact carries a Lead intake brief, or ``None`` --
    the Implementer's own view (``_hop_message``) replaces that one hop's carryover
    entirely, so only the latest match (not every brief-bearing hop) matters here."""
    index: int | None = None
    for i, h in enumerate(prior):
        if h.artifact is not None and h.artifact.brief is not None:
            index = i
    return index


def _hop_message(
    task: dict[str, Any],
    role: str,
    prior: list[HopResult],
    rework_hop: HopResult | None = None,
    step_instructions: str = "",
    project: str = "",
) -> tuple[str, _HopComposition]:
    """Build one role's message via ``core/context.py``'s token-budget compiler (see
    pod-dispatch.spec.md, "Bounded hop prompts"). The task description is never truncated;
    each prior artifact is fit to a per-role share, shedding ``DROP_ORDER`` fields before
    ``summary``, which is only ever truncated with a marker, never silently dropped.
    *rework_hop* gets the implementer's full carryover budget in its own section, deliberately
    excluded from the generic per-hop loop (not left to recency ranking) since it addresses
    what the rework hop exists for. Returns the message plus a ``_HopComposition``.

    *step_instructions*, when non-empty, is this step's own already-interpolated
    ``instructions`` (pipeline-format.spec.md) -- it replaces whatever instruction text the
    target role would otherwise carry, for every role including the Lead (a built-in's own
    instruction text, or a custom role's own ``hopInstruction``/generated fallback, see
    role-archetypes.spec.md)."""
    from docket.core import context as _ctx

    desc = str(task.get("description", "")).strip()
    if role == "lead":
        if step_instructions:
            lead_instruction = step_instructions
        else:
            lead_archetype = _archetypes.load_registry(project).get("lead")
            lead_instruction = (
                _archetypes.resolve_hop_instruction(lead_archetype) if lead_archetype else ""
            )
        message = f"{lead_instruction}\n\n{desc}" if lead_instruction else desc
        answers_block = _render_operator_answers(task)
        if answers_block:
            message = f"{message}\n\n## Operator answers\n{answers_block}"
        comp = _HopComposition(
            description_bytes=len(desc.encode("utf-8")), total_bytes=len(message.encode("utf-8"))
        )
        return message, comp

    instructions = _resolve_hop_instructions(role, project, rework_hop, step_instructions)

    # The role's total token budget, minus what the immutable task
    # description and this role's own fixed instruction footer already cost
    # — what's left is what the carryover (rework note + prior hops) may
    # spend. This is what makes "the composed message fits its role's
    # budget" a real, checkable property rather than an aspiration: the two
    # pieces that are never shed are accounted for before anything
    # sheddable is given a share.
    total_budget = _ctx.budget_for_role(role, project=project)
    reserved_tokens = _ctx.estimate_tokens(desc) + _ctx.estimate_tokens(instructions)
    carryover_budget = max(total_budget - reserved_tokens, 0)

    lines = [f"Task: {desc}", ""]
    comp = _HopComposition(description_bytes=len(desc.encode("utf-8")))

    if rework_hop is not None and rework_hop.output:
        # Rendered from the hop's *artifact*, not its raw output, so this
        # reflects the same structured content (see `render()`'s own
        # "Verdict: ..." line, added when the artifact carries one) the next
        # hop actually reasons about. Attributed to whichever step actually
        # drove the rework — not hardcoded to "reviewer" — so a custom
        # pipeline's rework source (any role with a verdict gate's `rework`
        # edge) is named correctly too.
        assert rework_hop.artifact is not None
        compiled = _ctx.compile_artifact(rework_hop.artifact, carryover_budget)
        comp.sections.append(
            {
                "role": "rework",
                "original_bytes": len(rework_hop.artifact.render().encode("utf-8")),
                "sent_bytes": len(compiled.text.encode("utf-8")),
                "truncated": compiled.truncated,
                "dropped_fields": list(compiled.dropped_fields),
            }
        )
        comp.truncated = comp.truncated or compiled.truncated
        lines.append(
            f"--- REWORK REQUIRED: {rework_hop.role} requested changes ---\n{compiled.text}\n"
        )

    last_index = len(prior) - 1
    # The Implementer's own view of the latest brief-bearing hop (almost always the
    # Lead's) replaces that hop's carried-forward prose entirely -- see the loop below.
    latest_brief_index = _latest_brief_hop_index(prior) if role == "implementer" else None
    # Iterate in the original chronological order (oldest first), so message
    # *layout* stays stable and only *content* varies with the budget. Only
    # the per-hop budget is recency-aware: rank counts back
    # from the most recent hop (rank 0), so `context.hop_share` gives it the
    # biggest share.
    for i, h in enumerate(prior):
        if not h.output or h is rework_hop:
            continue
        rank = last_index - i
        hop_budget = _ctx.hop_share(rank, carryover_budget)
        # The *artifact* is what gets carried forward and budgeted — not
        # the hop's raw output — so the budget bounds the same structured
        # content the next hop actually reasons about.
        assert h.artifact is not None
        if i == latest_brief_index:
            # The Implementer sees the Lead's typed brief in place of its prose
            # preamble -- never both -- so it reasons from the same structured
            # objective/acceptance/resources a human reviewing the task would.
            assert h.artifact.brief is not None
            brief_text = _handoff.render_brief(h.artifact.brief)
            comp.sections.append(
                {
                    "role": h.role,
                    "original_bytes": len(h.artifact.render().encode("utf-8")),
                    "sent_bytes": len(brief_text.encode("utf-8")),
                    "truncated": False,
                    "dropped_fields": [],
                }
            )
            lines.append(f"## Brief\n{brief_text}\n")
            continue
        compiled = _ctx.compile_artifact(h.artifact, hop_budget)
        comp.sections.append(
            {
                "role": h.role,
                "original_bytes": len(h.artifact.render().encode("utf-8")),
                "sent_bytes": len(compiled.text.encode("utf-8")),
                "truncated": compiled.truncated,
                "dropped_fields": list(compiled.dropped_fields),
            }
        )
        comp.truncated = comp.truncated or compiled.truncated
        lines.append(f"--- {h.role} output ---\n{compiled.text}\n")
    if instructions:
        lines.append(instructions)
    message = "\n".join(lines)
    comp.total_bytes = len(message.encode("utf-8"))
    return message, comp


# Rough character budget for the Lead's "## Operator answers" section, expressed here as a
# token budget for `_ctx._truncate_summary`, which only ever bounds bytes -- ASCII text keeps
# the two close enough for a "capped near N characters" guarantee, never an exact one.
_ANSWERS_CHAR_BUDGET = 4000


def _render_answer_value(entry: dict[str, Any]) -> str:
    """One answered entry's ``A: ...`` line: the single ``answer`` property's value for an
    ``accept``, else a plain marker -- see ``core.answers.answer_task``."""
    action = str(entry.get("action", ""))
    if action == "accept":
        content = entry.get("content")
        content = content if isinstance(content, dict) else {}
        if list(content.keys()) == ["answer"]:
            return str(content["answer"])
        return _json.dumps(content, sort_keys=True)
    if action == "decline":
        return "(declined)"
    if action == "cancel":
        return "(cancelled)"
    return "(no answer)"


def _render_operator_answers(task: dict[str, Any]) -> str:
    """Render ``answers[]`` as ``Q: ...\\nA: ...`` blocks, oldest first, capped near
    ``_ANSWERS_CHAR_BUDGET`` characters with a visible truncation marker. Empty when the task
    carries no answers yet."""
    answers_raw = task.get("answers")
    if not isinstance(answers_raw, list) or not answers_raw:
        return ""
    blocks = [
        f"Q: {str(entry.get('message', '')).strip()}\nA: {_render_answer_value(entry)}"
        for entry in answers_raw
        if isinstance(entry, dict)
    ]
    if not blocks:
        return ""
    from docket.core import context as _ctx

    text = "\n\n".join(blocks)
    budget_tokens = _ANSWERS_CHAR_BUDGET // _cfg.CONTEXT_BYTES_PER_TOKEN
    capped, _truncated = _ctx._truncate_summary(text, budget_tokens)
    return capped


def _hop_env(member_id: str, role: str) -> dict[str, str] | None:
    """Subprocess env override: only an Implementer with an allocated port range gets one
    (real ``DOCKET_PORT_*``/``DOCKET_SCRATCH_DIR`` vars, not TOOLS.md prose); every other
    case returns ``None`` (inherit the parent env)."""
    if role != "implementer":
        return None
    port_start = _fleet.meta_get(member_id, "portRangeStart", "")
    if not port_start:
        return None
    port_count = _fleet.meta_get(member_id, "portRangeCount", "")
    scratch_dir = _fleet.meta_get(member_id, "scratchDir", "")
    return {
        "DOCKET_PORT_BASE": port_start,
        "DOCKET_PORT_COUNT": port_count,
        "DOCKET_SCRATCH_DIR": scratch_dir,
    }


def _task_worktree_dir(task: dict[str, Any]) -> str:
    """The directory of the worktree recorded on *task* at claim, or empty when the task runs in
    place (no recorded worktree, or a recorded fallback)."""
    record = task.get("worktree")
    return str(record.get("dir") or "") if isinstance(record, dict) else ""


def _implementer_diff_probe(
    member_id: str, role: str, task: dict[str, Any]
) -> tuple[list[str], str | None, dict[str, Any] | None]:
    """Real ``files_changed``/``diff_ref``/``evidence`` for an Implementer hop (every other
    role gets ``([], None, None)``); resolves the same working tree the verify gate uses via
    ``core.pod.resolve_member_cwd`` so the two can never disagree. ``evidence`` is
    ``HopResult.evidence``'s ``{"commit", "baseCommit", "diffStat"}`` shape, with each field
    independently ``None`` (never raising) when git is missing, the checkout is not a repo,
    or no base commit can be resolved. ``baseCommit`` is the task worktree's recorded creation
    commit; an in-place task falls back to the merge-base with the codebase's current branch.
    See pod-dispatch.spec.md, "Hop evidence"."""
    if role != "implementer":
        return [], None, None
    task_dir = _task_worktree_dir(task)
    member_codebase = str(_fleet.meta_get(member_id, "codebase", "") or "")
    cwd = _pod.resolve_member_cwd(member_id, task_dir, member_codebase)
    if not _sys.git_available() or not _sys.git_is_repo(cwd):
        return [], None, {"commit": None, "baseCommit": None, "diffStat": None}
    files_changed = _sys.git_changed_files(cwd)
    diff_ref = _sys.git_current_branch(cwd) or None
    commit = _sys.git_head_sha(cwd)
    recorded = task.get("worktree")
    base_commit: str | None = None
    if task_dir and isinstance(recorded, dict):
        base_commit = str(recorded.get("baseCommit") or "") or None
    else:
        base_branch = _sys.git_current_branch(member_codebase or cwd) or None
        base_commit = _sys.git_merge_base(cwd, base_branch) if base_branch else None
    diff_stat = _sys.git_diff_stat(cwd, base_commit) if base_commit else None
    evidence = {"commit": commit, "baseCommit": base_commit, "diffStat": diff_stat}
    return files_changed, diff_ref, evidence


def _hop_record(h: HopResult) -> dict[str, Any]:
    """Persisted shape of one hop (round-trips via ``_hop_from_record``; pod-dispatch.spec.md,
    "Structured handoff artifacts" and "Hop evidence"). ``artifact``/``verify``/``evidence`` are
    persisted alongside ``output``; ``verification_skipped`` stays an in-memory-only flag."""
    return {
        "role": h.role,
        "member": h.member_id,
        "ok": h.ok,
        "output": h.output,
        "costUsd": round(h.cost_usd, 6),
        "error": h.error,
        "attempts": h.attempts,
        # Falls back to `role` when unset — see HopResult.step_id.
        "stepId": h.step_id or h.role,
        "artifact": h.artifact.model_dump() if h.artifact is not None else None,
        "nextStep": h.next_step,
        "parked": h.parked,
        "verify": h.verify,
        "evidence": h.evidence,
        "usage": h.usage,
        "trace": h.trace,
    }


def _hop_from_record(rec: dict[str, Any]) -> HopResult:
    """Reconstruct a HopResult from a persisted hop record (for resume). A missing or invalid
    ``artifact``, ``verify``, or ``evidence`` key degrades each to its own default -- see
    pod-dispatch.spec.md ("Structured handoff artifacts", "Hop evidence")."""
    output = str(rec.get("output", ""))
    artifact_raw = rec.get("artifact")
    artifact: _handoff.HandoffArtifact | None = None
    if isinstance(artifact_raw, dict):
        try:
            artifact = _handoff.HandoffArtifact.model_validate(artifact_raw)
        except Exception:
            artifact = None
    next_step_raw = rec.get("nextStep")
    verify_raw = rec.get("verify")
    evidence_raw = rec.get("evidence")
    usage_raw = rec.get("usage")
    trace_raw = rec.get("trace")
    return HopResult(
        role=str(rec.get("role", "")),
        member_id=str(rec.get("member", "")),
        ok=bool(rec.get("ok", False)),
        output=output,
        cost_usd=float(rec.get("costUsd", 0.0) or 0.0),
        error=str(rec.get("error", "")),
        attempts=int(rec.get("attempts", 1) or 1),
        step_id=str(rec.get("stepId", "") or rec.get("role", "")),
        artifact=artifact,
        next_step=next_step_raw if isinstance(next_step_raw, str) else None,
        parked=bool(rec.get("parked", False)),
        verify=verify_raw if isinstance(verify_raw, dict) else None,
        evidence=evidence_raw if isinstance(evidence_raw, dict) else None,
        usage=usage_raw if isinstance(usage_raw, dict) else None,
        trace=trace_raw if isinstance(trace_raw, dict) else None,
    )


@dataclass
class _ResumePosition:
    """Where a (possibly resumed) run should continue: ``pipeline_index`` into
    ``runtime_steps``; ``rework_counts``/``route_counts`` (cycles consumed, keyed by
    gated step id, or by ``(step_id, outcome_label)`` for a route)."""

    pipeline_index: int
    rework_counts: dict[str, int]
    route_counts: dict[tuple[str, str], int] = field(default_factory=dict)
    rework_hop: HopResult | None = None


def _group_complete(node: _orch.PlannedGroup, prior: list[HopResult]) -> bool:
    """Whether every child of a parallel group already has a persisted hop."""
    seen = {h.step_id or h.role for h in prior}
    return all((c.step_id or "") in seen for c in node.children)


def _replay_pipeline_position(
    runtime_steps: tuple[_orch.PlannedNode, ...], prior: list[HopResult]
) -> _ResumePosition:
    """Replay a hop history to find where dispatch should continue. See pod-dispatch.spec.md
    ("Per-hop incremental persistence and crash recovery" for why a completed-roles set can't
    resume once rework reruns a role; "Parallel step groups" item 6 for the known group-resume
    limit this function's trailing loop implements). Matches a verdict gate's ``rework`` edge
    by step id, not a hardcoded role. Only replays *non-terminal* history -- a terminal outcome
    is decided/persisted synchronously in the same ``dispatch_task`` call, and an ordinary
    graded-failure ``failed`` task is never reclaimed for resume (only one tagged with a
    RESUMABLE_FAILURE_KINDS reason)."""
    id_to_index = {node.step_id: i for i, node in enumerate(runtime_steps)}
    pi = 0
    rework_counts: dict[str, int] = {}
    route_counts: dict[tuple[str, str], int] = {}
    rework_hop: HopResult | None = None
    for hop in prior:
        step_id = hop.step_id or hop.role
        idx = id_to_index.get(step_id)
        if idx is None:
            continue  # a parallel-group child's hop — handled by the trailing check below
        node = runtime_steps[idx]
        if hop.parked:
            # An in-turn tool call parked mid-hop (ADR 0016 SS2): the hop was
            # attempted, not decided -- it never reached a gate or a route, so
            # neither applies. Resume re-runs this exact index (not the one
            # after it), carrying no rework state forward.
            rework_hop = None
            pi = idx
            continue
        if hop.next_step:
            # This hop's gate outcome was routed via its step's own `on` map
            # (see `_route_outcome`) — follow that exact decision instead of
            # re-deriving it, the same "don't re-decide, replay" contract the
            # rework branch below already follows for the older mechanism.
            target_index = id_to_index.get(hop.next_step)
            if target_index is not None:
                if target_index <= idx:
                    label = (
                        hop.artifact.verdict
                        if hop.artifact is not None and hop.artifact.verdict is not None
                        else "fail"
                    )
                    key = (step_id, label)
                    route_counts[key] = route_counts.get(key, 0) + 1
                rework_hop = None
                pi = target_index
                continue
        gate = node.gate if isinstance(node, _orch.PlannedUnit) else None
        if isinstance(gate, _pipeline.VerdictGate) and gate.rework is not None:
            verdict = hop.artifact.verdict if hop.artifact is not None else None
            if verdict is None:
                # A record whose artifact carries no verdict falls back to
                # parsing the hop's raw output.
                verdict = _orch.parse_verdict(gate, hop.output)
            when_set = _orch.normalize_values(gate.rework.when, gate.case_sensitive)
            cycles_so_far = rework_counts.get(step_id, 0)
            target_index = id_to_index.get(gate.rework.to)
            if (
                verdict is not None
                and verdict in when_set
                and cycles_so_far < gate.rework.max_cycles
                and target_index is not None
            ):
                rework_counts[step_id] = cycles_so_far + 1
                rework_hop = hop
                pi = target_index
                continue
        rework_hop = None
        pi = idx + 1
    while (
        pi < len(runtime_steps)
        and isinstance(runtime_steps[pi], _orch.PlannedGroup)
        and _group_complete(runtime_steps[pi], prior)  # type: ignore[arg-type]
    ):
        pi += 1
        rework_hop = None
    return _ResumePosition(
        pipeline_index=pi,
        rework_counts=rework_counts,
        route_counts=route_counts,
        rework_hop=rework_hop,
    )


def _pod_requires_approval(project: str, role: str) -> bool:
    """The pod-level require_approval source: Lead's ``requireApprovalRoles`` meta, a
    comma-separated case-insensitive role list; blank/missing means no gate. See
    pod-dispatch.spec.md ("require_approval gate and waiting_approval")."""
    lead_id = _pod.member_id(project, "lead")
    raw = _fleet.meta_get(lead_id, "requireApprovalRoles", "")
    if not raw:
        return False
    roles = {r.strip().lower() for r in raw.split(",") if r.strip()}
    return role.lower() in roles


def _policy_requires_approval(project: str, role: str, task: dict[str, Any]) -> bool:
    """An explicit seam that always returns ``False`` today; kept as a real function, not
    deleted, so ``_hop_requires_approval``'s three-source shape stays intact for a future
    per-hop policy source. See pod-dispatch.spec.md ("require_approval gate and waiting_approval")."""
    return False


def _pipeline_step_requires_approval(gate: _pipeline.Gate | None) -> bool:
    """The pipeline-defined ``approval`` step source: *gate* is the current position's
    resolved gate; an ``ApprovalGate`` requires a human decision, same as the pod-level
    ``requireApprovalRoles`` source."""
    return isinstance(gate, _pipeline.ApprovalGate)


def _hop_requires_approval(
    project: str,
    role: str,
    task: dict[str, Any],
    pipeline_index: int,
    gate: _pipeline.Gate | None,
) -> bool:
    """Whether the require_approval gate fires: an OR of three independent sources (pod-level
    ``requireApprovalRoles``, the ``_policy_requires_approval`` seam, a pipeline ``approval``
    step) -- any one firing is enough. See pod-dispatch.spec.md ("require_approval gate")."""
    return (
        _pod_requires_approval(project, role)
        or _policy_requires_approval(project, role, task)
        or _pipeline_step_requires_approval(gate)
    )


def _approval_action_text(role: str, task: dict[str, Any]) -> str:
    """Human-readable description recorded on the approval record; ``core/approval.py``
    redacts it before persisting, so this need not scrub secrets itself.
    """
    desc = str(task.get("description", "")).strip()
    task_id = str(task.get("id", "task"))
    return f"pod dispatch — {role} hop for task {task_id}: {desc}"[:1000]


def _trace_locked(*args: Any, **kwargs: Any) -> _trace.TraceStatus:
    """``trace.trace_event``, serialized against ``orchestrator.trace_write_lock`` because a
    parallel group's children share one task's tracefile (the append-only exemption is safe
    only across *different* session files). See pod-dispatch.spec.md ("Parallel step groups")."""
    with _orch.trace_write_lock:
        return _trace.trace_event(*args, **kwargs)


def _verdict_event_names(role: str) -> tuple[str, str, str]:
    """(rework_event, rejected_event, unparseable_event) names for a verdict gate's non-pass
    outcome. Keeps exact legacy names for ``reviewer``/``tester`` (pinned by
    test_reviewer_gate.py/test_verify_gate.py) so gate logic stays generic without changing
    operator-visible trace names; other roles get generic ``verdict_*`` names."""
    if role == "reviewer":
        return "rework_started", "review_rejected", "reviewer_verdict_unparseable"
    if role == "tester":
        return "verdict_rework_started", "tester_verdict_failed", "tester_verdict_failed"
    return "verdict_rework_started", "verdict_rejected", "verdict_unparseable"


@dataclass
class _UnitOutcome:
    """What happened running one ``PlannedUnit``'s hop. ``kind`` adds ``"routed"`` to the
    existing set; its resolved gate outcome (for ``_route_outcome``) is ``label``."""

    kind: str
    hops: list[HopResult] = field(default_factory=list)
    reason: str = ""
    rework_target_index: int | None = None
    approval_token: str = ""
    pending_approval_index: int | None = None
    label: str = ""
    # Only set for kind == "waiting_input" -- the minted Question, dumped by alias.
    question: dict[str, Any] | None = None


@dataclass
class _UnitContext:
    """Per-invocation state a ``PlannedUnit``'s execution needs but does not own. Two
    attributes are mutated across a run, not just read -- passing a *copy* instead of the
    same shared object would silently break each: ``rework_counts`` accumulates each gated
    step's cycle count in place; ``override_index`` is rebound to ``None`` the first time a
    run reaches the pipeline position a granted approval named (see ``_claim_next_task``)."""

    project: str
    task: dict[str, Any]
    task_id: str
    session_id: str
    cap: float
    resolved_turn_timeout: int
    resolved_verify_timeout: int
    id_to_index: dict[str, int]
    rework_counts: dict[str, int]
    override_index: int | None
    track_pid: bool
    run: Runner
    do_sleep: Callable[[float], None]
    on_hop: Callable[[HopResult], None] | None
    on_retry: Callable[[], None] | None
    # Each step id's own already-interpolated `instructions` override (see
    # `_pipeline.step_instructions_by_id`/`interpolate_instructions`); a step
    # absent here defers to its role's own hop instruction. Defaulted so
    # every existing direct `_UnitContext(...)` construction (tests included)
    # is unaffected.
    step_instructions: dict[str, str] = field(default_factory=dict)
    # This run's resolved pipeline variables, stringified -- the `var`/`is` half of a
    # step's `when` predicate compares against these. Defaulted for the same reason
    # as `step_instructions` above.
    variables: dict[str, str] = field(default_factory=dict)
    # Cycles consumed by an `on:` backward/self route, keyed by (step_id,
    # outcome_label) -- alongside `rework_counts`, mutated in place by
    # `_route_outcome`. Defaulted for the same reason as `step_instructions`.
    route_counts: dict[tuple[str, str], int] = field(default_factory=dict)
    # The caller's own resolution for an *unset* pod ``approvalMode`` (ADR 0016 SS2) --
    # "wait" for a foreground TTY dispatch, "park" for `serve --dispatch`'s sweep or a
    # non-TTY foreground dispatch. An explicit pod value always wins over this (see
    # `pod_approval_mode`). Defaulted for the same reason as `step_instructions` above.
    approval_default: Literal["wait", "park"] = "wait"


def _gate_budget(ctx: _UnitContext, role: str) -> _UnitOutcome | None:
    """Budget gate before the hop (see ``pod_gating_cost``); on trip, marks the Lead paused
    so future dispatch attempts are refused at claim time instead of re-running this check.
    Returns ``None`` when the hop may proceed."""
    if ctx.cap <= 0.0:
        return None
    spent, estimated = pod_gating_cost(ctx.project)
    if spent < ctx.cap:
        return None
    spent_label = f"~${spent:.2f} (estimated — no cost recorded)" if estimated else f"${spent:.2f}"
    _trace_locked(
        ctx.project,
        ctx.session_id,
        role,
        "budget_exceeded",
        _json.dumps(
            {
                "spent": round(spent, 6),
                "cap": round(ctx.cap, 6),
                "role": role,
                "estimated": estimated,
            }
        ),
    )
    return _UnitOutcome(
        kind="blocked",
        reason=f"pod budget reached ({spent_label} ≥ ${ctx.cap:.2f}) before {role}",
    )


def _gate_pre_hop_approval(
    ctx: _UnitContext,
    role: str,
    node: _orch.PlannedUnit,
    *,
    check_approval: bool,
    index_for_context: int,
) -> _UnitOutcome | None:
    """require_approval gate: after budget (affordability), before the hop (permission).
    Mutates ``ctx.override_index``, consuming a granted approval's single-use override the
    first time a run reaches its minted position, so a later hop revisiting that position
    (a rework cycle) still gates normally. Returns ``None`` when the hop may proceed."""
    if not check_approval:
        return None
    if index_for_context == ctx.override_index:
        ctx.override_index = None
        return None
    if not _hop_requires_approval(ctx.project, role, ctx.task, index_for_context, node.gate):
        return None
    action = _approval_action_text(role, ctx.task)
    token = _ap.approval_create(
        ctx.project,
        role,
        action,
        context={"taskId": ctx.task_id, "pipelineIndex": index_for_context},
    )
    _trace_locked(
        ctx.project,
        ctx.session_id,
        role,
        "approval_required",
        _json.dumps({"role": role, "token": token, "pipelineIndex": index_for_context}),
    )
    return _UnitOutcome(
        kind="waiting_approval",
        reason=f"approval required before {role} hop (token={token})",
        approval_token=token,
        pending_approval_index=index_for_context,
    )


def _consult_answer_note(task: dict[str, Any], step_id: str) -> str:
    """The operator's answer to this step's parked consultation, as a trailing message block
    (empty when the step has none)."""
    answer = task.get("consultAnswer")
    if not isinstance(answer, dict) or answer.get("step") != step_id:
        return ""
    return f"\n\n{answer.get('text', '')}\n"


def _consult_budget_env(ctx: _UnitContext, env: dict[str, str] | None) -> dict[str, str] | None:
    """Once the task has parked consultations, this hop's cap is what the task has left
    (``maxConsultationsPerTask`` minus them); before that the pod setting applies as is."""
    used = ctx.task.get("consultations")
    if not isinstance(used, int) or used <= 0:
        return env
    remaining = max(0, _pod_settings(ctx.project).max_consultations_per_task - used)
    return {**(env or {}), _rd.DOCKET_MAX_CONSULTATIONS: str(remaining)}


def _compose_hop(
    ctx: _UnitContext,
    node: _orch.PlannedUnit,
    role: str,
    member_id: str,
    prior_snapshot: list[HopResult],
    rework_hop: HopResult | None,
) -> tuple[str, dict[str, str] | None]:
    """Build this hop's prompt/environment and emit its ``context_composed``/``tool_call``
    trace pair. A downstream hop's message gets an extra checkout note naming the real
    implementation worktree, when allocated -- see pod-dispatch.spec.md ("Downstream worktree continuity")."""
    step_override = ctx.step_instructions.get(node.step_id, "")
    message, composition = _hop_message(
        ctx.task,
        role,
        prior_snapshot,
        rework_hop,
        step_instructions=step_override,
        project=ctx.project,
    )
    message += _consult_answer_note(ctx.task, node.step_id)
    pipeline_worktree = ""
    if role != "lead":
        pipeline_worktree = _task_worktree_dir(ctx.task)
        if pipeline_worktree:
            if role == "implementer":
                checkout_note = (
                    "\nYour working checkout for this task: "
                    f"`{pipeline_worktree}`. Make every change there, not in the origin "
                    "codebase path named elsewhere in your instructions.\n"
                )
            else:
                checkout_note = (
                    "\nEffective implementation checkout for this downstream hop: "
                    f"`{pipeline_worktree}`. Inspect and test this checkout, not the origin "
                    "codebase; keep your role's existing tool permissions."
                )
                if isinstance(node.gate, _pipeline.VerdictGate):
                    checkout_note += (
                        " Your final reply must still contain one distinct recognized "
                        "verdict marker at the start of a complete line; reasons may "
                        "come before or after it."
                    )
                checkout_note += "\n"
            message += checkout_note
            composition.total_bytes += len(checkout_note.encode("utf-8"))
    _trace_locked(
        ctx.project,
        ctx.session_id,
        role,
        "context_composed",
        _json.dumps(
            {
                "hop": role,
                "description_bytes": composition.description_bytes,
                "sections": composition.sections,
                "total_bytes": composition.total_bytes,
                "truncated": composition.truncated,
            }
        ),
    )
    _trace_locked(
        ctx.project,
        ctx.session_id,
        role,
        "tool_call",
        _json.dumps({"hop": role, "agent": member_id}),
    )
    env = _hop_env(member_id, role)
    if pipeline_worktree:
        env = dict(env or {})
        env[_rd.PIPELINE_WORKTREE_ENV] = pipeline_worktree
    resolved_mode = pod_approval_mode(ctx.project, caller_default=ctx.approval_default)
    if resolved_mode in ("refuse", "park"):
        # Same internal-env route as PIPELINE_WORKTREE_ENV/harness mode
        # (cli/_harness.py): DocketDriver pops this before the tool env
        # reaches ToolContext, so it is never a real tool-visible variable.
        env = dict(env or {})
        env[_rd.DOCKET_APPROVAL_MODE] = resolved_mode
        if resolved_mode == "park":
            # This hop's own deadline for a call it parks (ADR 0016 SS2) --
            # popped by DocketDriver into ToolContext.approval_expires_at,
            # stamped on the parked record by core/tools.py's `_park_call`.
            # Computed fresh per hop (not once per task) so a long-running
            # earlier hop never shortens a later one's window.
            expiry_hours = _pod_settings(ctx.project).approval_expiry_hours
            deadline = _dt.datetime.now(_dt.UTC) + _dt.timedelta(hours=expiry_hours)
            env[_rd.DOCKET_APPROVAL_EXPIRES_AT] = deadline.isoformat()
    env = _consult_budget_env(ctx, env)
    pregrants_raw = ctx.task.get("pregrants")
    pregrants_raw = [
        *(pregrants_raw if isinstance(pregrants_raw, list) else []),
        *_mint_task_grant_pregrants(ctx, role),
    ]
    if pregrants_raw:
        # Every pre-grant this task's human has already resolved (ADR 0016
        # SS2) -- a human already consumed one carries no live effect
        # (`consume_pregrant` is single-use and atomic), so passing the whole
        # list along is a harmless no-op for anything already spent; it only
        # ever lets an unconsumed exact-match call through without asking
        # again.
        env = dict(env or {})
        env[_rd.DOCKET_PREGRANTS] = _json.dumps(pregrants_raw)
    return message, env


def _run_hop_turn(
    ctx: _UnitContext,
    node: _orch.PlannedUnit,
    role: str,
    member_id: str,
    history_session_key: str,
    message: str,
    env: dict[str, str] | None,
) -> tuple[_rd.TurnResult, int]:
    """Run this hop's agent turn, retrying only a retryable failure in place (a non-zero
    exit or bad verdict is a real answer and stops here) -- see pod-dispatch.spec.md
    ("Retries and the failure-kind taxonomy"). Returns the total tries made. A step's own
    ``retries``/``timeout`` override wins over the pod's role-based budget and turn timeout.
    A step's own ``model`` (pipeline-format.spec.md "Steps" Req. 10) is resolved once per call
    and passed to the production driver only, for this hop alone -- see "Per-hop execution"."""
    retry_budget = node.retries if node.retries is not None else _retries_for_role(role)
    hop_timeout = node.timeout if node.timeout is not None else ctx.resolved_turn_timeout
    resolved_model: str | None = None
    if node.model:
        try:
            resolved_model = _models_policy.resolve_step_model(node.model)
        except ValueError as exc:
            raise DispatchError(f"step {node.step_id!r}: {exc}") from exc

    # Record the production driver's spawned pid as in-flight for
    # `docket task cancel` — only while the subprocess is actually
    # running; removed again the moment this attempt returns, so a long
    # multi-hop task never accumulates stale pids from finished hops.
    run_id_for_pids = _runs.current_run_id() if ctx.track_pid else None
    spawned_pid: list[int] = []

    def _on_spawn(pid: int) -> None:
        spawned_pid.append(pid)
        if run_id_for_pids is not None:
            _runs.add_hop_pid(run_id_for_pids, pid)

    attempt = 1
    while True:
        spawned_pid.clear()
        if ctx.track_pid:
            # `ctx.run` is typed as the plain 5-arg `Runner` Callable (every
            # test double's exact shape); calling the concrete production
            # driver directly here (rather than through `ctx.run`) is what
            # lets it take the extra `on_spawn` kwarg type-safely.
            run_res = _dr.default_driver().run_turn(
                member_id,
                history_session_key,
                message,
                hop_timeout,
                env,
                on_spawn=_on_spawn,
                trace_project=ctx.project,
                trace_session_key=ctx.session_id,
                trace_task_id=ctx.task_id,
                model=resolved_model,
            )
        else:
            run_res = ctx.run(member_id, history_session_key, message, hop_timeout, env)
        if run_id_for_pids is not None and spawned_pid:
            _runs.remove_hop_pid(run_id_for_pids, spawned_pid[-1])
        if run_res.ok or run_res.failure_kind not in _RETRYABLE_FAILURE_KINDS:
            break
        if attempt > retry_budget:
            break
        _trace_locked(
            ctx.project,
            ctx.session_id,
            role,
            "hop_retry",
            _json.dumps(
                {
                    "hop": role,
                    "attempt": attempt,
                    "retry_budget": retry_budget,
                    "failure_kind": run_res.failure_kind,
                    "error": run_res.error,
                    "retry_after_s": run_res.retry_after_s,
                }
            ),
        )
        # A retry means the dispatcher is alive and making forward progress,
        # not crashed — refresh the claim before the backoff sleep so a
        # concurrent dispatcher's stale-claim sweep never mistakes it for one
        # (see the module docstring / _touch_claim).
        if ctx.on_retry is not None:
            ctx.on_retry()
        # The endpoint's own Retry-After (when it named one) can push the wait
        # past the linear backoff; either way it is capped so one large value
        # never stalls a hop indefinitely (pod-dispatch.spec.md, "Retries and
        # the failure-kind taxonomy" requirement 3).
        ctx.do_sleep(
            min(
                max(_cfg.DISPATCH_RETRY_BACKOFF_S * attempt, run_res.retry_after_s or 0.0),
                _cfg.DISPATCH_RETRY_MAX_WAIT_S,
            )
        )
        attempt += 1
    return run_res, attempt


def _apply_output_guardrails(
    ctx: _UnitContext, role: str, run_res: _rd.TurnResult
) -> tuple[str, bool, str]:
    """``pre_output`` guardrail scan over the hop's real output, before it is embedded in
    the carried-forward artifact or persisted record. See security-gates.spec.md
    ("pre_output"): only ``redact``/``block`` change what is carried forward;
    ``require_approval`` behaves like ``warn`` since the hop already ran -- there is no
    "before" moment left to gate. Returns the (possibly redacted) output, hop-ok, error text."""
    hop_output = run_res.output
    hop_ok = run_res.ok
    hop_error = run_res.error
    if hop_output:
        hit = _policy.policy_eval_detail(role, "pre_output", hop_output)
        # Also classify the hop's real output against the built-in
        # high-risk action classes (core/security.py's HIGH_RISK_PATTERNS),
        # independently of the JSON policy engine above. This is a second,
        # independent check over what the hop *reports* it did, not what a
        # tool call literally asked to run — it still catches a
        # money-movement or secret-access command described in the hop's
        # own summary even when the underlying call never reached
        # `dispatch_tool`'s live `pre_tool_call` gate (e.g. a runner that
        # doesn't route through it at all, such as a test double). A match
        # never downgrades an already-stronger policy_eval_detail verdict —
        # redact/block/require_approval all outrank a bare "allow" — it only
        # raises a plain "allow" to "warn". It cannot go further than
        # "warn": there is no live approver to "ask" post-hoc (the hop
        # already ran, the same reasoning behind pre_output's
        # require_approval-behaves-like-warn rule), and HIGH_RISK_PATTERNS
        # is a built-in Python list, not an installed, operator-authored
        # JSON policy — so this only ever adds visibility, it never
        # redacts or blocks on the operator's behalf the way a real
        # installed policy can.
        risk_cls = _sec.match_high_risk(hop_output)
        if risk_cls is not None and hit.action == "allow":
            hit = _policy.PolicyHit(
                action="warn",
                policy_id=f"high-risk:{risk_cls.name}",
                message=risk_cls.description,
            )
        if hit.action != "allow":
            _trace_locked(
                ctx.project,
                ctx.session_id,
                role,
                "guardrail_check",
                _json.dumps({"hook": "pre_output", "policy": hit.policy_id, "action": hit.action}),
            )
        if hit.action == "redact":
            hop_output = _trace.redact(hop_output)
        elif hit.action == "block":
            _trace_locked(
                ctx.project,
                ctx.session_id,
                role,
                "guardrail_block",
                _json.dumps({"hook": "pre_output", "policy": hit.policy_id, "action": hit.action}),
            )
            if hop_ok:
                hop_ok = False
                hop_error = f"blocked by guardrail policy '{hit.policy_id}'"
    return hop_output, hop_ok, hop_error


def _hop_usage(run_res: _rd.TurnResult) -> dict[str, int] | None:
    """The turn's measured tokens as the hop record's ``usage`` block, or ``None``."""
    if run_res.usage is None:
        return None
    return {"input": run_res.usage.input_tokens, "output": run_res.usage.output_tokens}


def _hop_trace_link(ctx: _UnitContext, first_ts: str) -> dict[str, str] | None:
    """The hop's trace link; ``lastTs`` is refreshed once the hop's closing events are written
    (``_persist_hop_and_trace``). ``None`` under ``DOCKET_NO_TRACE``."""
    if _cfg.no_trace() or not first_ts:
        return None
    return {
        "project": ctx.project,
        "session": ctx.session_id,
        "firstTs": first_ts,
        "lastTs": _trace._now_iso(),
    }


def _build_hop_result(
    ctx: _UnitContext,
    node: _orch.PlannedUnit,
    role: str,
    member_id: str,
    run_res: _rd.TurnResult,
    hop_output: str,
    hop_ok: bool,
    hop_error: str,
    attempt: int,
    first_ts: str = "",
) -> HopResult:
    """Build this hop's persisted record and handoff artifact. The verdict is parsed once,
    guarded on ``hop_ok`` (not ``run_res.ok``) since a ``pre_output`` block can fail an
    otherwise-successful call and must not hand a "here is what I changed" artifact
    downstream; the diff probe is likewise gated. Uses ``hop_output``, never
    ``run_res.output`` -- the raw text would silently undo a ``redact`` verdict's rewrite."""
    verdict: str | None = None
    if hop_ok and isinstance(node.gate, _pipeline.VerdictGate):
        verdict = _orch.parse_verdict(node.gate, hop_output)
    files_changed: list[str] = []
    diff_ref: str | None = None
    evidence: dict[str, Any] | None = None
    if hop_ok:
        files_changed, diff_ref, evidence = _implementer_diff_probe(member_id, role, ctx.task)
    # A hop's raw text carrying a parseable TaskBrief (ADR 0016 §4) is never limited to
    # the Lead role by construction -- any hop's reply can end in one -- but is `None`
    # for the overwhelming majority that never emit one, `_handoff.parse_brief` failing
    # closed on anything else.
    brief = _handoff.parse_brief(hop_output) if hop_ok else None
    artifact = _handoff.HandoffArtifact(
        summary=hop_output,
        verdict=verdict,
        files_changed=files_changed,
        diff_ref=diff_ref,
        brief=brief,
    )
    return HopResult(
        role=role,
        member_id=member_id,
        ok=hop_ok,
        output=hop_output,
        cost_usd=run_res.cost_usd,
        error=hop_error,
        attempts=attempt,
        step_id=node.step_id,
        artifact=artifact,
        evidence=evidence,
        usage=_hop_usage(run_res),
        trace=_hop_trace_link(ctx, first_ts),
    )


# `core.agent_loop.approval_parked_error` owns this string's format (quoted
# key=value pairs, the same convention `core.harness`'s `_extract_field` already
# parses for `approval_unavailable_error`'s sibling string) -- TurnResult carries
# no structured field for a parked call's token, so this is the one place
# dispatch.py re-derives it. Only the token is needed here (the tool/policy/reason
# fields feed the harness contract, not this seam), so this stays a narrow,
# single-field parser rather than a second copy of harness.py's generic one.
_PARKED_ERROR_PREFIX = "approval_parked:"
_APPROVAL_TOKEN_RE = _re.compile(r"approval_token=(?:'([^']*)'|\"([^\"]*)\"|(\S+))")


def _parked_approval_token(error: str) -> str | None:
    """The approval token from a hop's ``approval_parked`` stop, or ``None`` for an
    ordinary failure or an unparseable one."""
    # Fails closed: an unmatched parked call falls through to an ordinary `failed`
    # outcome instead of silently waiting forever.
    if not error.startswith(_PARKED_ERROR_PREFIX):
        return None
    match = _APPROVAL_TOKEN_RE.search(error)
    if not match:
        return None
    return next((g for g in match.groups() if g is not None), None) or None


def _parked_consult_question(
    ctx: _UnitContext, hop: HopResult, token: str | None
) -> dict[str, Any] | None:
    """The question a parked ``consult`` left, rebound to this task and step (stored on the
    task like an input step's), or ``None`` when *token* is not a consultation's."""
    if token is None or not token.startswith(_consult.PARK_TOKEN_PREFIX):
        return None
    question = _consult.parked_question(token)
    if question is None:
        return None
    question.task_id = ctx.task_id
    question.step = hop.step_id or hop.role
    return question.model_dump(by_alias=True)


def _persist_hop_and_trace(
    ctx: _UnitContext,
    role: str,
    hop: HopResult,
    run_res: _rd.TurnResult,
    hop_ok: bool,
    hop_error: str,
    index_for_context: int,
) -> _UnitOutcome | None:
    """Persist this hop and trace its result; short-circuit a failed hop. Returns the
    terminal outcome, or ``None`` to proceed to the gate."""
    # Persisted immediately, not deferred to a group join, so a crash in a sibling child
    # never loses an already-completed hop. A hop whose turn stopped on an in-turn
    # `approval_parked` denial (park-mode DOCKET_APPROVAL_MODE, see `_compose_hop`) is
    # persisted with `hop.parked = True` before `on_hop` -- so a crash right after still
    # leaves the correct record for `_replay_pipeline_position` to resume from -- and
    # yields the same `waiting_approval` outcome shape the pre-hop `require_approval` gate
    # already produces, at this hop's own pipeline index (ADR 0016 SS2).
    parked_token = None if hop_ok else _parked_approval_token(hop_error)
    if parked_token is not None:
        hop.parked = True
    consult_question = _parked_consult_question(ctx, hop, parked_token)

    _trace_locked(
        ctx.project,
        ctx.session_id,
        role,
        "tool_result" if hop_ok else "error",
        hop.output or hop_error or "",
        cost_usd=run_res.cost_usd or None,
    )
    if run_res.cost_usd:
        _trace_locked(
            ctx.project,
            ctx.session_id,
            role,
            "cost_charged",
            _json.dumps({"role": role}),
            cost_usd=run_res.cost_usd,
        )

    # The hop's closing events are written, so its trace window can now be closed; this precedes
    # `on_hop` so the persisted record's `lastTs` covers them (evidence-v1).
    if hop.trace is not None:
        hop.trace["lastTs"] = _trace._now_iso()

    if ctx.on_hop is not None:
        ctx.on_hop(hop)

    if not hop_ok:
        if run_res.failure_kind == "run_cancelled":
            return _UnitOutcome(
                kind="cancelled",
                hops=[hop],
                reason="run cancellation requested",
            )
        if consult_question is not None:
            return _UnitOutcome(
                kind="waiting_input",
                hops=[hop],
                reason=f"{role} hop parked a consultation (question={consult_question['id']})",
                question=consult_question,
            )
        if parked_token is not None and parked_token.startswith(_consult.PARK_TOKEN_PREFIX):
            # No approval record can resolve a consult token, so parking on it would be stuck.
            return _UnitOutcome(
                kind="failed",
                hops=[hop],
                reason=f"{role} hop failed: consult_question_missing (the parked consultation carried no question)",
            )
        if parked_token is not None:
            # Reuses the pre-hop gate's own event type (core/trace.py's
            # EVENT_TYPES is not this card's to extend): both mean exactly
            # "a require_approval-equivalent gate fired; task ->
            # waiting_approval", whether the trigger was a pre-hop gate or, as
            # here, an in-turn tool call parking mid-hop.
            _trace_locked(
                ctx.project,
                ctx.session_id,
                role,
                "approval_required",
                _json.dumps(
                    {"role": role, "token": parked_token, "pipelineIndex": index_for_context}
                ),
            )
            return _UnitOutcome(
                kind="waiting_approval",
                hops=[hop],
                reason=f"{role} hop parked for approval (token={parked_token})",
                approval_token=parked_token,
                pending_approval_index=index_for_context,
            )
        return _UnitOutcome(
            kind="failed",
            hops=[hop],
            reason=f"{role} hop failed: {hop_error or 'no result'}",
        )
    return None


def _match_on_route(on: dict[str, Any] | None, label: str) -> Any:
    """The raw ``Route`` value in *on* whose key matches *label* case-insensitively
    (outcome labels always compare case-insensitively -- see pipeline-format.spec.md
    "Outcome routing"), or ``None`` when *on* has no entry for it."""
    if not on:
        return None
    norm = label.lower()
    for key, route in on.items():
        if str(key).lower() == norm:
            return route
    return None


def _evaluate_mechanical_gate(
    ctx: _UnitContext,
    gate: _pipeline.MechanicalGate,
    node: _orch.PlannedUnit,
    role: str,
    member_id: str,
    hop: HopResult,
) -> _UnitOutcome:
    """A ``MechanicalGate``: run ``verifyCmd`` (or the gate's own command) and gate on its
    exit, in the dir from ``core.pod.resolve_member_cwd`` (shared with cli/_pod.py so the two
    never disagree); a ``"pass"``/``"fail"`` named in the step's own ``on`` map routes instead."""
    verify_cmd = gate.command or str(_fleet.meta_get(member_id, "verifyCmd", "") or "")
    if not verify_cmd:
        # Check if verification is required
        require_verify = _pod_settings(ctx.project).require_verify
        if require_verify:
            _trace_locked(
                ctx.project,
                ctx.session_id,
                role,
                "verification_failed",
                _json.dumps({"reason": "verification_missing", "member": member_id}),
            )
            return _UnitOutcome(
                kind="failed",
                hops=[hop],
                reason="verifyCmd required but not set",
            )
        # Honesty rule: never silently skip — a missing verifyCmd is
        # visible via a trace event (parity with the "passed" case
        # below) and the hop's own `verification_skipped` flag, which
        # `cli/`'s dispatch renderer prints. `core/` never prints
        # directly.
        _trace_locked(
            ctx.project,
            ctx.session_id,
            role,
            "tool_result",
            _json.dumps({"verification": "skipped", "member": member_id}),
        )
        hop.verification_skipped = True
        return _UnitOutcome(kind="advance", hops=[hop])

    member_codebase = str(_fleet.meta_get(member_id, "codebase", "") or "")
    cwd = _pod.resolve_member_cwd(member_id, _task_worktree_dir(ctx.task), member_codebase)
    # The verify command gets its own timeout, decoupled from the agent-turn
    # timeout above — a 20-minute test suite and a hung LLM turn are no longer
    # forced to share one budget.
    mech_timeout = gate.timeout or ctx.resolved_verify_timeout
    before_verify = _sys.git_worktree_fingerprint(cwd)
    verify_start = _time.monotonic()
    passed, raw_output = _sys.run_verify_cmd(verify_cmd, cwd, mech_timeout)
    duration_s = _time.monotonic() - verify_start
    after_verify = _sys.git_worktree_fingerprint(cwd)
    produced = sorted(p for p, fp in after_verify.items() if before_verify.get(p) != fp)
    redacted = _trace.redact(raw_output)
    # Persisted regardless of pass/fail/route -- see HopResult.verify. `outputTail` is the
    # redacted string's own tail (never the raw one), so a secret is never one truncation
    # away from surviving into the persisted record.
    hop.verify = {
        "cmd": verify_cmd,
        "exitCode": 0 if passed else 1,
        "durationS": round(duration_s, 3),
        "outputTail": redacted[-_cfg.VERIFY_EVIDENCE_TAIL_CHARS :],
        "touched": produced,
    }
    label = "pass" if passed else "fail"
    if _match_on_route(node.on, label) is not None:
        return _UnitOutcome(kind="routed", hops=[hop], label=label)
    if not passed:
        _trace_locked(
            ctx.project,
            ctx.session_id,
            role,
            "verification_failed",
            _json.dumps({"cmd": verify_cmd, "output": redacted}),
        )
        return _UnitOutcome(
            kind="failed",
            hops=[hop],
            reason=f"verifyCmd failed: {verify_cmd!r}",
        )
    _trace_locked(
        ctx.project,
        ctx.session_id,
        role,
        "tool_result",
        _json.dumps({"verification": "passed", "cmd": verify_cmd}),
    )
    return _UnitOutcome(kind="advance", hops=[hop], label=label)


def _evaluate_verdict_gate(
    ctx: _UnitContext,
    gate: _pipeline.VerdictGate,
    node: _orch.PlannedUnit,
    role: str,
    hop: HopResult,
) -> _UnitOutcome:
    """A ``VerdictGate``: pass/rework/fail on the hop's already-parsed verdict (reused from
    the hop's own artifact, never reparsed from ``run_res.output``); a verdict named in the
    step's own ``on`` map routes instead, beating the rework/fail handling below."""
    assert hop.artifact is not None
    verdict = hop.artifact.verdict
    hop_output = hop.output
    pass_set = _orch.normalize_values(gate.pass_values, gate.case_sensitive)
    if verdict is not None and verdict in pass_set:
        return _UnitOutcome(kind="advance", hops=[hop], label=verdict)

    if verdict is not None and _match_on_route(node.on, verdict) is not None:
        return _UnitOutcome(kind="routed", hops=[hop], label=verdict)

    rework = gate.rework
    if rework is not None and verdict is not None:
        when_set = _orch.normalize_values(rework.when, gate.case_sensitive)
        if verdict in when_set:
            cycles_so_far = ctx.rework_counts.get(node.step_id, 0)
            target_index = ctx.id_to_index.get(rework.to)
            if cycles_so_far < rework.max_cycles and target_index is not None:
                ctx.rework_counts[node.step_id] = cycles_so_far + 1
                rework_event, _unused1, _unused2 = _verdict_event_names(role)
                redacted = _trace.redact(hop_output)
                _trace_locked(
                    ctx.project,
                    ctx.session_id,
                    role,
                    rework_event,
                    _json.dumps({"cycle": ctx.rework_counts[node.step_id], "output": redacted}),
                )

                # Record REQUEST-CHANGES to the corrections ledger
                if verdict and verdict.lower() == "request-changes":
                    from docket.core import corrections as _corrections

                    _corrections.record(
                        ctx.project,
                        "request_changes",
                        task_id=ctx.task_id,
                        role=role,
                        text=hop_output,
                        source="reviewer",
                    )

                return _UnitOutcome(kind="rework", hops=[hop], rework_target_index=target_index)
            # Rework budget exhausted (or, defensively, no valid target) —
            # this verdict is now terminal.
            _unused3, rejected_event, _unused4 = _verdict_event_names(role)
            redacted = _trace.redact(hop_output)
            _trace_locked(
                ctx.project,
                ctx.session_id,
                role,
                rejected_event,
                _json.dumps({"cycles": cycles_so_far, "output": redacted}),
            )
            return _UnitOutcome(
                kind="failed",
                hops=[hop],
                reason=(
                    f"{role} rejected after {cycles_so_far} rework cycle(s): {verdict.upper()}"
                ),
            )

    # Anything else is either truly unparseable (no match at all) or a
    # real, parsed marker that's simply neither a pass nor a
    # rework-trigger — distinct outcomes (though, for the tester role
    # specifically, they share one event name — see
    # `_verdict_event_names`).
    _unused5, rejected_event2, unparseable_event = _verdict_event_names(role)
    redacted = _trace.redact(hop_output)
    if verdict is None:
        _trace_locked(
            ctx.project,
            ctx.session_id,
            role,
            unparseable_event,
            _json.dumps({"verdict": "unparseable", "output": redacted}),
        )
        return _UnitOutcome(
            kind="failed",
            hops=[hop],
            reason=f"{role} output unparseable (expected one unambiguous recognized "
            "verdict marker at the start of a line)",
        )
    _trace_locked(
        ctx.project,
        ctx.session_id,
        role,
        rejected_event2,
        _json.dumps({"verdict": verdict, "output": redacted}),
    )
    return _UnitOutcome(kind="failed", hops=[hop], reason=f"{role} reported {verdict.upper()}")


def _evaluate_post_hop_gate(
    ctx: _UnitContext,
    node: _orch.PlannedUnit,
    role: str,
    member_id: str,
    hop: HopResult,
    *,
    check_approval: bool,
) -> _UnitOutcome:
    """Resolve this step's post-hop gate generically, by the gate's own type. See
    pod-dispatch.spec.md ("Generalized gate execution"). An ``ApprovalGate`` was already
    handled pre-hop, so once the turn has run it simply advances."""
    gate = node.gate
    if gate is None:
        return _UnitOutcome(kind="advance", hops=[hop])

    if isinstance(gate, _pipeline.MechanicalGate):
        return _evaluate_mechanical_gate(ctx, gate, node, role, member_id, hop)

    if isinstance(gate, _pipeline.VerdictGate):
        return _evaluate_verdict_gate(ctx, gate, node, role, hop)

    if isinstance(gate, _pipeline.ApprovalGate):
        if not check_approval:
            return _UnitOutcome(
                kind="failed",
                hops=[hop],
                reason=f"{role}: an 'approval' gate is not supported inside a parallel group",
            )
        # Pre-hop already handled this (above) — post-hop, nothing further
        # to check; a granted/override'd approval simply advances.
        return _UnitOutcome(kind="advance", hops=[hop])

    return _UnitOutcome(kind="advance", hops=[hop])  # pragma: no cover - closed Gate union


def _execute_unit(
    ctx: _UnitContext,
    node: _orch.PlannedUnit,
    *,
    prior_snapshot: list[HopResult],
    rework_hop: HopResult | None,
    check_approval: bool,
    index_for_context: int,
) -> _UnitOutcome:
    """Run one PlannedUnit's hop end to end: budget/approval gates, the agent turn (with
    retries), and its post-hop gate. Shared by a top-level step and a group's children --
    *check_approval* is False for a child, since an ``approval`` gate inside a fan-out is a
    configuration error, not a mid-group wait. See pod-dispatch.spec.md ("Parallel step groups")."""
    role = node.role or node.agent or node.step_id
    member_id = node.member_id
    assert member_id is not None  # runnable_nodes() already filtered out skipped units
    history_session_key = step_session_key(member_id, ctx.project, ctx.task_id, node.step_id)

    if _pod.pod_of(member_id) != ctx.project:
        raise DispatchError(
            f"refusing cross-pod dispatch: '{member_id}' is not in pod '{ctx.project}'"
        )

    budget_outcome = _gate_budget(ctx, role)
    if budget_outcome is not None:
        return budget_outcome

    approval_outcome = _gate_pre_hop_approval(
        ctx, role, node, check_approval=check_approval, index_for_context=index_for_context
    )
    if approval_outcome is not None:
        return approval_outcome

    message, env = _compose_hop(ctx, node, role, member_id, prior_snapshot, rework_hop)
    hop_first_ts = _trace._now_iso()
    run_res, attempt = _run_hop_turn(ctx, node, role, member_id, history_session_key, message, env)

    hop_output, hop_ok, hop_error = _apply_output_guardrails(ctx, role, run_res)

    hop = _build_hop_result(
        ctx, node, role, member_id, run_res, hop_output, hop_ok, hop_error, attempt, hop_first_ts
    )

    early_outcome = _persist_hop_and_trace(
        ctx, role, hop, run_res, hop_ok, hop_error, index_for_context
    )
    if early_outcome is not None:
        return early_outcome

    return _evaluate_post_hop_gate(ctx, node, role, member_id, hop, check_approval=check_approval)


def _run_group_node(
    ctx: _UnitContext,
    node: _orch.PlannedGroup,
    prior: list[HopResult],
    index_for_context: int,
) -> _UnitOutcome:
    """Run a parallel group's children concurrently; join before advancing. Merge priority:
    cancelled > blocked > failed > advance (rework is impossible here -- the pipeline
    format's validator forbids a rework edge inside a ``parallel`` group)."""
    prior_snapshot = list(prior)
    child_outcomes = _orch.run_group(
        node.children,
        lambda child: _execute_unit(
            ctx,
            child,
            prior_snapshot=prior_snapshot,
            rework_hop=None,
            check_approval=False,
            index_for_context=index_for_context,
        ),
    )
    merged = _UnitOutcome(kind="advance")
    for oc in child_outcomes:
        merged.hops.extend(oc.hops)
    for oc in child_outcomes:
        if oc.kind == "cancelled":
            merged.kind, merged.reason = "cancelled", oc.reason
            break
    else:
        for oc in child_outcomes:
            if oc.kind == "blocked":
                merged.kind, merged.reason = "blocked", oc.reason
                break
        else:
            for oc in child_outcomes:
                if oc.kind == "failed":
                    merged.kind, merged.reason = "failed", oc.reason
                    break
    return merged


def _resolve_pipeline_steps(
    project: str, spec: _pipeline.PipelineSpec | None
) -> tuple[tuple[_orch.PlannedNode, ...], dict[str, int], dict[str, str]]:
    """Resolve *spec* (or this pod's default pipeline) against the pod's live roster into
    this run's ordered, runnable steps. Assumes the caller already validated the pod/Lead
    exist; this only builds the plan, it does not itself raise for a missing pod."""
    # The third element is each step id's own declared `instructions` text,
    # not yet interpolated -- see `_pipeline.step_instructions_by_id`.
    effective_spec = effective_pipeline(project, spec)
    registry = _archetypes.load_registry()
    roster = pod_full_roster(project)
    plan = _orch.resolve_plan(effective_spec, roster, registry=registry)
    runtime_steps = plan.runnable_nodes()
    id_to_index = {node.step_id: i for i, node in enumerate(runtime_steps)}
    raw_step_instructions = _pipeline.step_instructions_by_id(effective_spec)
    return runtime_steps, id_to_index, raw_step_instructions


def _resolve_resume_state(
    runtime_steps: tuple[_orch.PlannedNode, ...], resume_from: list[HopResult] | None
) -> tuple[list[HopResult], int, dict[str, int], dict[tuple[str, str], int], dict[int, HopResult]]:
    """Compute the pipeline position (and rework state) a run should continue from.
    *resume_from* seeds hops already completed before a crash, which can legitimately
    include the same step more than once mid-rework -- see ``_replay_pipeline_position``."""
    prior: list[HopResult] = list(resume_from) if resume_from else []
    # A step can now legitimately run more than once (a rework cycle re-runs
    # its gate's declared target, then re-runs the gating step), so "where do
    # we continue" is a pipeline position + per-gate rework counts, not a set
    # of already-seen role names — see `_replay_pipeline_position`'s
    # docstring for why this matters for a task resumed mid-rework.
    resume_pos = _replay_pipeline_position(runtime_steps, prior)
    pending_rework_by_index: dict[int, HopResult] = {}
    if resume_pos.rework_hop is not None:
        pending_rework_by_index[resume_pos.pipeline_index] = resume_pos.rework_hop
    return (
        prior,
        resume_pos.pipeline_index,
        dict(resume_pos.rework_counts),
        dict(resume_pos.route_counts),
        pending_rework_by_index,
    )


def _resolve_gate_override(task: dict[str, Any]) -> int | None:
    """A granted approval's single-use override for this one claim (see
    ``_claim_next_task``), consumed the first time this run reaches that pipeline position,
    so a later hop at the same position (a rework cycle) still gates normally."""
    override_index = task.get("gateOverridePipelineIndex")
    return override_index if isinstance(override_index, int) else None


def _when_cwd(ctx: _UnitContext, prior: list[HopResult]) -> str:
    """Working tree a ``when: {changed: ...}`` predicate and a command step's own command
    both run against: the task's own worktree, falling back to the pod Lead's own codebase
    (the task runs in place, or the pod has no Implementer)."""
    worktree = _task_worktree_dir(ctx.task)
    if worktree:
        return worktree
    lead_id = _pod.member_id(ctx.project, "lead")
    return str(_fleet.meta_get(lead_id, "codebase", "") or "")


def _step_skipped(ctx: _UnitContext, node: _orch.PlannedUnit, prior: list[HopResult]) -> bool:
    """Evaluate *node*'s ``when`` (every set predicate ANDed); a false predicate emits
    ``step_skipped`` so the caller advances with no hop. See pod-dispatch.spec.md
    ("Conditional steps and command steps")."""
    when = node.when
    if not when:
        return False
    matched = True
    if "changed" in when:
        cwd = _when_cwd(ctx, prior)
        changed_files = _sys.git_changed_files(cwd) if cwd else []
        pattern = str(when["changed"])
        matched = matched and any(_fnmatch.fnmatch(path, pattern) for path in changed_files)
    if "var" in when:
        actual = ctx.variables.get(str(when["var"]))
        matched = matched and actual is not None and actual == str(when.get("is", ""))
    if "memberPresent" in when:
        matched = matched and str(when["memberPresent"]) in pod_full_roster(ctx.project)
    if matched:
        return False
    _trace_locked(
        ctx.project,
        ctx.session_id,
        node.step_id,
        "step_skipped",
        _json.dumps({"step": node.step_id, "when": when}),
    )
    return True


def _task_command_env(
    ctx: _UnitContext, prior: list[HopResult], step_env: dict[str, str] | None = None
) -> dict[str, str]:
    """A command step's environment: the step's own ``env`` under the task's coordinates -- its
    id, and the base and head commits of the latest successful Implementer hop's evidence
    (empty strings when there is none). The coordinates always win."""
    evidence: dict[str, Any] = {}
    for hop in reversed(prior):
        if hop.role == "implementer" and hop.ok and hop.evidence is not None:
            evidence = hop.evidence
            break
    return {
        **(step_env or {}),
        "DOCKET_TASK_ID": ctx.task_id,
        "DOCKET_BASE_COMMIT": str(evidence.get("baseCommit") or ""),
        "DOCKET_HEAD_COMMIT": str(evidence.get("commit") or ""),
    }


def _run_command_step(
    ctx: _UnitContext,
    node: _orch.PlannedUnit,
    prior: list[HopResult],
    index_for_context: int,
) -> _UnitOutcome:
    """Run *node*'s ``run`` command directly -- no agent turn, no session. Classified like
    any shell-out first: ``allow`` runs it, anything else gates like an ``approval`` step
    (or fails outright under ``approvalMode: refuse``). See pod-dispatch.spec.md."""
    # `park` gates the same non-blocking way `wait` does here -- a command step never
    # reaches the in-turn tool chokepoint a park-mode call would need to record, so there
    # is nothing to park.
    assert node.run is not None
    role = node.step_id
    cmd = node.run
    settings = _pod_settings(ctx.project)
    verdict = _sec.classify_command(cmd, extra_bins=frozenset(settings.allow_commands))
    if verdict.action != "allow":
        if pod_approval_mode(ctx.project, caller_default=ctx.approval_default) == "refuse":
            _trace_locked(
                ctx.project,
                ctx.session_id,
                role,
                "command_step",
                _json.dumps({"step": node.step_id, "cmd": cmd, "exit": None}),
            )
            hop = HopResult(
                role=role,
                member_id="",
                ok=False,
                output="",
                error=f"command step refused: {verdict.reason}",
                step_id=node.step_id,
            )
            return _UnitOutcome(
                kind="failed",
                hops=[hop],
                reason=f"command step {node.step_id!r} refused: {verdict.reason}",
            )
        # "wait" (the default): gate exactly like a pipeline `approval` step, keyed on
        # this exact pipeline position -- a granted single-use override lets a resumed
        # run fall through here without asking again.
        approval_node = replace(node, gate=_pipeline.ApprovalGate(message=verdict.reason))
        approval_outcome = _gate_pre_hop_approval(
            ctx, role, approval_node, check_approval=True, index_for_context=index_for_context
        )
        if approval_outcome is not None:
            return approval_outcome

    cwd = _when_cwd(ctx, prior)
    timeout = node.timeout or ctx.resolved_verify_timeout
    passed, raw_output = _sys.run_verify_cmd(
        cmd, cwd, timeout, env=_task_command_env(ctx, prior, node.env)
    )
    redacted = _trace.redact(raw_output)
    _trace_locked(
        ctx.project,
        ctx.session_id,
        role,
        "command_step",
        _json.dumps({"step": node.step_id, "cmd": cmd, "exit": 0 if passed else 1}),
    )
    hop = HopResult(role=role, member_id="", ok=passed, output=redacted, step_id=node.step_id)
    if ctx.on_hop is not None:
        ctx.on_hop(hop)
    label = _command_outcome_label(raw_output, passed)
    if _match_on_route(node.on, label) is not None:
        return _UnitOutcome(kind="routed", hops=[hop], label=label)
    if not passed:
        return _UnitOutcome(
            kind="failed",
            hops=[hop],
            reason=f"command step {node.step_id!r} failed: {cmd!r}",
            label=label,
        )
    return _UnitOutcome(kind="advance", hops=[hop], label=label)


def _command_outcome_label(output: str, passed: bool) -> str:
    """A command step's outcome label for its ``on:`` map: the last output line when it is a
    single upper-case token (``PASS``, ``NEEDS-REVIEW``), else ``pass``/``fail`` by exit."""
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    if lines:
        last = lines[-1]
        if " " not in last and last.upper() == last and any(c.isalpha() for c in last):
            return last
    return "pass" if passed else "fail"


_DEFAULT_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"answer": {"type": "string"}},
    "required": ["answer"],
}


def _brief_from_step(prior: list[HopResult], step_id: str) -> _oc.TaskBrief | None:
    """The most recent *step_id* hop's parsed brief, or ``None`` -- a plain-text hop, a
    step that never ran, or a Lead reply with no parseable brief all degrade the same way."""
    for h in reversed(prior):
        if h.step_id == step_id and h.artifact is not None and h.artifact.brief is not None:
            return h.artifact.brief
    return None


def _brief_questions_schema(questions: list[str]) -> dict[str, Any]:
    """One string property per brief question (``q1``..``qn``, ``title`` = the question
    text), every one required -- the richer schema an intake brief's own questions earn
    over the generic single free-text ``answer`` property."""
    properties = {f"q{i}": {"type": "string", "title": q} for i, q in enumerate(questions, 1)}
    return {"type": "object", "properties": properties, "required": list(properties)}


def _run_input_step(
    ctx: _UnitContext,
    node: _orch.PlannedUnit,
    prior: list[HopResult],
    index_for_context: int,
) -> _UnitOutcome:
    """Park the task for an operator question minted from *node.input*, trace
    ``input_requested``, and stop ``waiting_input`` -- no hop persisted for this attempt.
    Resumed only by ``core.answers.answer_task``. See pod-dispatch.spec.md."""
    assert node.input is not None
    spec = node.input
    # When the `from` step's latest hop carries a Lead intake brief with its own
    # `questions`, the minted question asks those specific questions instead of one
    # generic free-text answer (pod-dispatch.spec.md, "Task brief").
    brief = _brief_from_step(prior, spec.from_)
    if brief is not None and brief.questions:
        message = f"The Lead needs answers before starting: {brief.objective}"
        requested_schema = _brief_questions_schema(brief.questions)
    else:
        message = spec.message.strip() or f"Operator input requested (from step {spec.from_!r})."
        requested_schema = dict(_DEFAULT_INPUT_SCHEMA)
    expires_at: str | None = None
    if spec.expires_hours is not None:
        expires_at = (
            _dt.datetime.now(_dt.UTC) + _dt.timedelta(hours=spec.expires_hours)
        ).isoformat()
    question = _oc.Question(
        id=_oc.new_question_id(),
        task_id=ctx.task_id,
        pod=ctx.project,
        step=node.step_id,
        message=message,
        requested_schema=requested_schema,
        created_at=_now(),
        expires_at=expires_at,
    )
    _trace_locked(
        ctx.project,
        ctx.session_id,
        node.step_id,
        "input_requested",
        _json.dumps({"task": ctx.task_id, "step": node.step_id, "questionId": question.id}),
    )
    return _UnitOutcome(
        kind="waiting_input",
        reason=f"awaiting operator answer for step {node.step_id!r} (question={question.id})",
        question=question.model_dump(by_alias=True),
    )


def _route_outcome(
    ctx: _UnitContext,
    node: _orch.PlannedUnit,
    outcome: _UnitOutcome,
    pipeline_index: int,
) -> tuple[int | None, str]:
    """Resolve a ``"routed"`` outcome's target (``fail``/``stop``/a step id, bounded by
    ``max`` when backward) into a next index (``None`` for ``stop``, negative for a
    terminal failure) and reason; traces one ``route_taken`` event either way."""
    route = _match_on_route(node.on, outcome.label)
    label_upper = outcome.label.upper()
    if isinstance(route, dict):
        target: Any = route.get("goto")
        max_cycles = route.get("max")
    else:
        target = route
        max_cycles = None
    target_str = target if isinstance(target, str) else "stop"
    trace_role = node.role or node.agent or node.step_id

    def _trace_route(resolved_target: str) -> None:
        _trace_locked(
            ctx.project,
            ctx.session_id,
            trace_role,
            "route_taken",
            _json.dumps(
                {"step": node.step_id, "outcome": outcome.label, "target": resolved_target}
            ),
        )

    if outcome.hops:
        outcome.hops[0].next_step = target_str

    if target_str == "fail":
        _trace_route("fail")
        return -1, f"step {node.step_id!r} outcome {label_upper} routed to fail"
    if target_str == "stop":
        _trace_route("stop")
        return None, f"step {node.step_id!r} outcome {label_upper} routed to stop"

    target_index = ctx.id_to_index.get(target_str)
    if target_index is None:
        _trace_route(target_str)
        return -1, f"step {node.step_id!r}: 'on' target {target_str!r} is not a known step id"

    if target_index <= pipeline_index:
        key = (node.step_id, outcome.label)
        cycles_so_far = ctx.route_counts.get(key, 0)
        cap = max_cycles if isinstance(max_cycles, int) else 1
        if cycles_so_far >= cap:
            _trace_route(target_str)
            return -1, (
                f"step {node.step_id!r} outcome {label_upper} exhausted its routing budget "
                f"({cycles_so_far} of {cap}) toward {target_str!r}"
            )
        ctx.route_counts[key] = cycles_so_far + 1

    _trace_route(target_str)
    return target_index, f"step {node.step_id!r} outcome {label_upper} routed to {target_str!r}"


# A routed-to-fail outcome sets no failure kind today (an ordinary graded gate/hop
# failure) -- the one named exception is the intake pipeline's own REJECT marker, which
# maps to the A2A REJECTED state via `operator_contract.a2a_state`. One constant, so the
# mapping is never hand-built twice (ADR 0016 §4).
_ROUTE_FAILURE_KINDS: dict[str, str] = {"REJECT": "rejected"}


def _check_brief_resources(project: str, brief: _oc.TaskBrief) -> list[str]:
    """The subset of *brief*'s own ``resources`` entries a deterministic check cannot
    confirm (unconfigured secret, missing path, no ``verifyCmd``); ``[]`` means every
    one named is present. Pure, no side effects."""
    missing: list[str] = []
    configured_secrets: set[str] | None = None
    for item in brief.resources:
        if item.startswith("secret:"):
            if configured_secrets is None:
                configured_secrets = _secrets.secrets_keys()
            if item[len("secret:") :] not in configured_secrets:
                missing.append(item)
        elif item.startswith("path:"):
            if not Path(item[len("path:") :]).exists():
                missing.append(item)
        elif item == "verify":
            implementer_id = pod_full_roster(project).get("implementer")
            verify_cmd = (
                str(_fleet.meta_get(implementer_id, "verifyCmd", "") or "")
                if implementer_id
                else ""
            )
            if not verify_cmd:
                missing.append(item)
    return missing


def _block_on_missing_resources(
    ctx: _UnitContext, outcome: _UnitOutcome, result: TaskResult
) -> bool:
    """A ``READY`` outcome whose brief names something ``_check_brief_resources`` finds
    missing blocks *result* and returns ``True``; the caller's own ``break`` stops the
    pipeline. A brief with nothing missing, or no brief, returns ``False`` unchanged."""
    if outcome.label.upper() != "READY" or not outcome.hops:
        return False
    brief = outcome.hops[-1].artifact.brief if outcome.hops[-1].artifact else None
    if brief is None:
        return False
    missing = _check_brief_resources(ctx.project, brief)
    if not missing:
        return False
    result.status = "blocked"
    result.blocked_reason = "resources"
    result.reason = "brief names missing resources: " + ", ".join(missing)
    return True


def _run_pipeline(
    ctx: _UnitContext,
    runtime_steps: tuple[_orch.PlannedNode, ...],
    pipeline_index: int,
    pending_rework_by_index: dict[int, HopResult],
    result: TaskResult,
    prior: list[HopResult],
) -> None:
    """Advance one task through its resolved pipeline until a terminal outcome. Mutates
    *result*/*prior* in place per step (each hop is also observed via *on_hop* -- see
    ``_persist_hop_and_trace``). The only backward moves are a bounded rework cycle and a
    step's own ``on:`` route, each jumping to a declared target. A ``READY`` verdict
    carrying a Lead intake brief (ADR 0016 §4) is checked against
    ``_check_brief_resources`` before the pipeline is allowed past it."""
    while pipeline_index < len(runtime_steps):
        node = runtime_steps[pipeline_index]

        if isinstance(node, _orch.PlannedGroup):
            outcome = _run_group_node(ctx, node, prior, pipeline_index)
        elif _step_skipped(ctx, node, prior):
            pipeline_index += 1
            continue
        elif node.run is not None:
            outcome = _run_command_step(ctx, node, prior, pipeline_index)
        elif node.input is not None:
            outcome = _run_input_step(ctx, node, prior, pipeline_index)
        else:
            rework_hop = pending_rework_by_index.pop(pipeline_index, None)
            outcome = _execute_unit(
                ctx,
                node,
                prior_snapshot=prior,
                rework_hop=rework_hop,
                check_approval=True,
                index_for_context=pipeline_index,
            )

        result.hops.extend(outcome.hops)
        prior.extend(outcome.hops)

        if outcome.kind == "blocked":
            result.status = "blocked"
            result.reason = outcome.reason
            _pause_lead_for_budget(ctx.project)
            break
        if outcome.kind == "waiting_approval":
            result.status = "waiting_approval"
            result.reason = outcome.reason
            result.approval_token = outcome.approval_token
            result.pending_approval_index = outcome.pending_approval_index
            break
        if outcome.kind == "waiting_input":
            result.status = "waiting_input"
            result.reason = outcome.reason
            result.question = outcome.question
            break
        if outcome.kind == "failed":
            result.status = "failed"
            result.reason = outcome.reason
            break
        if outcome.kind == "cancelled":
            result.status = "cancelled"
            result.reason = outcome.reason
            break
        if outcome.kind == "rework":
            assert outcome.rework_target_index is not None
            pending_rework_by_index[outcome.rework_target_index] = outcome.hops[0]
            pipeline_index = outcome.rework_target_index
            continue
        if outcome.kind == "routed":
            assert isinstance(node, _orch.PlannedUnit)
            next_index, reason = _route_outcome(ctx, node, outcome, pipeline_index)
            if next_index is None:
                result.status = "done"
                result.reason = reason
                break
            if next_index < 0:
                result.status = "failed"
                result.reason = reason
                result.failure_kind = _ROUTE_FAILURE_KINDS.get(outcome.label.upper(), "")
                break
            if _block_on_missing_resources(ctx, outcome, result):
                break
            pipeline_index = next_index
            continue
        if outcome.kind == "advance" and _block_on_missing_resources(ctx, outcome, result):
            break
        pipeline_index += 1


def dispatch_task(
    project: str,
    task: dict[str, Any],
    *,
    runner: Runner | None = None,
    turn_timeout: int | None = None,
    verify_timeout: int | None = None,
    resume_from: list[HopResult] | None = None,
    on_hop: Callable[[HopResult], None] | None = None,
    on_retry: Callable[[], None] | None = None,
    sleep: Callable[[float], None] | None = None,
    spec: _pipeline.PipelineSpec | None = None,
    variables: dict[str, Any] | None = None,
    approval_default: Literal["wait", "park"] = "wait",
) -> TaskResult:
    """Drive one task through the pod pipeline, hop by hop. Full contract: pod-dispatch.spec.md
    ("Pipeline order and participation", "Per-hop incremental persistence and crash recovery",
    "Deterministic refusal inside a claimed task", "Retries and the failure-kind taxonomy",
    "Generalized gate execution", "Parallel step groups"). Budget is checked before each hop; a
    failed hop stops the pipeline except for a bounded rework loop re-running a verdict gate's
    declared target up to its own cycle budget. *spec* ``None`` resolves the pod's
    zero-migration pipeline; *resume_from* seeds hops completed before a crash or a settled
    refusal (skipped, not re-invoked) -- including a hop that parked mid-turn, replayed by its
    own exact index (ADR 0016 SS2, see ``_replay_pipeline_position``); *turn_timeout*/
    *verify_timeout* override the pod Lead's meta then ``DEFAULT_TIMEOUT``, unless a step
    declares its own. *on_retry* fires before each retry so the caller can refresh the task's
    claim before it goes stale. *variables* is this run's already-resolved pipeline variable
    namespace (``dispatch_pod`` validates and resolves it before calling here) -- used only to
    interpolate any step's own ``instructions`` text (pipeline-format.spec.md); a direct caller
    that skips ``dispatch_pod`` gets no unresolved-reference refusal, only best-effort
    interpolation. *approval_default* is this call's own resolution for an *unset* pod
    ``approvalMode`` (``pod_approval_mode``); an explicit pod value always wins over it.

    A ``DispatchError`` raised anywhere on this claimed task's path (the membership check near
    the top of ``_execute_unit``, or this function's own up-front ``pod_pipeline`` revalidation)
    is caught here and folded into a ``"failed"`` result tagged ``failure_kind="dispatch_refused"``
    instead of propagating -- the caller (``dispatch_pod``) always finalizes and settles the
    claim, and a crash (any *other* exception) still propagates unchanged, leaving the task
    ``running`` for the stale-claim sweep exactly as before."""
    run = runner or _dr.default_driver().run_turn
    # pid tracking (for `docket task cancel`) only makes sense for a real
    # OS process, i.e. the production driver — never an injected test
    # runner/fake, none of which accept an `on_spawn` kwarg (and none of which
    # have a process to report anyway). Gating on `runner is None` (rather
    # than duck-typing) keeps every existing 5-arg-Callable test double
    # working completely unchanged.
    track_pid = runner is None
    do_sleep = sleep or _time.sleep
    task_id = str(task.get("id", "task"))
    session_id = f"agent:{project}:{task_id}"

    _trace.trace_event(
        project,
        session_id,
        "lead",
        "session_start",
        _json.dumps({"source": "dispatch", "task": task_id, "resumed": bool(resume_from)}),
    )

    result = TaskResult(task_id=task_id, status="done", hops=list(resume_from or []))
    try:
        pod_pipeline(project)  # validates pod/lead up front (raises DispatchError otherwise)
        cap = pod_budget(project)
        resolved_turn_timeout = _resolve_timeout(turn_timeout, pod_turn_timeout(project))
        resolved_verify_timeout = _resolve_timeout(verify_timeout, pod_verify_timeout(project))

        runtime_steps, id_to_index, raw_step_instructions = _resolve_pipeline_steps(project, spec)
        resolved_vars: dict[str, Any] = variables or {}
        step_instructions = {
            sid: _pipeline.interpolate_instructions(text, resolved_vars)
            for sid, text in raw_step_instructions.items()
        }
        prior, pipeline_index, rework_counts, route_counts, pending_rework_by_index = (
            _resolve_resume_state(runtime_steps, resume_from)
        )

        # A granted approval hands the exact pipeline position it stopped at
        # back to this one claim as a single-use override (see
        # `_claim_next_task`'s claim-time handoff) — consumed the first time this
        # run reaches that position, so a later hop at the same position (a
        # rework cycle revisiting it) still gates normally.
        override_index = _resolve_gate_override(task)

        ctx = _UnitContext(
            project=project,
            task=task,
            task_id=task_id,
            session_id=session_id,
            cap=cap,
            resolved_turn_timeout=resolved_turn_timeout,
            resolved_verify_timeout=resolved_verify_timeout,
            id_to_index=id_to_index,
            rework_counts=rework_counts,
            override_index=override_index,
            track_pid=track_pid,
            run=run,
            do_sleep=do_sleep,
            on_hop=on_hop,
            on_retry=on_retry,
            step_instructions=step_instructions,
            variables={k: str(v) for k, v in resolved_vars.items()},
            route_counts=route_counts,
            approval_default=approval_default,
        )

        result = TaskResult(task_id=task_id, status="done", hops=list(prior))

        _run_pipeline(ctx, runtime_steps, pipeline_index, pending_rework_by_index, result, prior)
    except DispatchError as exc:
        result.status = "failed"
        result.reason = str(exc)
        result.failure_kind = "dispatch_refused"
        _trace.trace_event(
            project, session_id, "lead", "dispatch_refused", _json.dumps({"reason": str(exc)})
        )

    _trace.trace_event(
        project,
        session_id,
        "lead",
        "session_end",
        _json.dumps({"status": result.status}),
    )
    return result


def _apply_result(task: dict[str, Any], res: TaskResult) -> None:
    """Fold a TaskResult back onto the stored task dict (terminal state; pod-dispatch.spec.md,
    "blocked and terminal-failure re-entry"). ``blocked``/``waiting_approval``/``waiting_input``
    are never rewritten to ``pending`` here, only via ``unblock_pod``/``retry_task``/
    ``resolve_waiting_approval``/``core.answers.answer_task``. Stays pure -- HEARTBEAT.md sync
    lives in ``_finalize_task``."""
    task["status"] = res.status
    task["reason"] = res.reason
    task["hops"] = [_hop_record(h) for h in res.hops]
    task["costUsd"] = res.cost_usd
    task["claimId"] = None
    task.pop("claimPid", None)
    task.pop("consultAnswer", None)  # delivered to the hop this result came from
    if res.status == "blocked":
        task["blockedReason"] = res.blocked_reason or res.reason
    elif res.status == "waiting_approval":
        task["approvalToken"] = res.approval_token
        task["pendingApprovalIndex"] = res.pending_approval_index
    elif res.status == "waiting_input":
        task["question"] = res.question
        if res.question and res.question.get("kind") in ("clarification", "decision"):
            task["consultations"] = int(task.get("consultations") or 0) + 1
    else:
        task["completedAt"] = _now()
        task.pop("taskGrants", None)
        if res.failure_kind:
            task["failureKind"] = res.failure_kind
        else:
            # A fresh ordinary terminal result supersedes any stale-claim
            # (or settled-refusal) marker left by an earlier attempt at
            # this same task.
            task.pop("failureKind", None)


def _eligible_for_claim(t: dict[str, Any], *, resume: bool) -> bool:
    """Whether *t* can be claimed by this dispatch run. See pod-dispatch.spec.md ("Claiming"):
    ``pending`` always is; a ``failed`` task tagged with a RESUMABLE_FAILURE_KINDS reason only
    when *resume* is set (a swept crash, or a settled deterministic refusal -- neither waited
    out for staleness here, since a refusal's claim was already cleanly settled, not crashed);
    ``waiting_approval``/``waiting_input`` never -- neither status is ``pending`` or ``failed``,
    so both are already excluded by construction; a parked question re-enters only through
    ``core.answers.answer_task`` (-> ``pending``) or expiry (-> ``blocked``, retried like any
    other blocked task)."""
    status = t.get("status")
    if status == "pending":
        return True
    return bool(resume and status == "failed" and t.get("failureKind") in RESUMABLE_FAILURE_KINDS)


def _ensure_task_worktree(project: str, claimed: dict[str, Any]) -> None:
    """Record ``task["worktree"]`` for a newly claimed task; a task that has one keeps it. No
    codebase or an in-place Implementer records nothing; a failed ``worktree add`` records
    ``fallbackReason`` and the task runs in place."""
    if "worktree" in claimed:
        return
    implementer = _pod.member_id(project, "implementer")
    codebase = str(_fleet.meta_get(implementer, "codebase", "") or "")
    if not codebase or _fleet.meta_get(implementer, "inPlace", ""):
        return
    task_id = str(claimed.get("id", ""))
    record, reason = _pp.provision_task_worktree(implementer, project, task_id, codebase)
    stored: dict[str, Any] = (
        record if record else {"dir": "", "branch": "", "baseCommit": "", "fallbackReason": reason}
    )

    def _fn(doc: dict[str, Any]) -> dict[str, Any] | None:
        tasks = doc.get("tasks")
        if not isinstance(tasks, list):
            return None
        for t in tasks:
            if isinstance(t, dict) and t.get("id") == task_id:
                t["worktree"] = stored
        return {"tasks": tasks}

    _store.read_modify_write(pod_task_list_path(project), _fn)
    claimed["worktree"] = stored


def _claim_next_task(
    project: str, *, resume: bool
) -> tuple[dict[str, Any], list[HopResult]] | None:
    """Locked claim of the pod's next eligible task (highest priority first; pod-dispatch.spec.md,
    "Claiming", "Mechanical HEARTBEAT ledger"). One filelocked read-pick-flip-write so two
    concurrent callers can never claim the same task; a paused pod refuses every claim outright,
    checked outside the queue lock since pause changes are rare and operator-driven. Returns
    the claimed task and any recorded hops, or ``None``; also syncs the HEARTBEAT.md ledger."""
    lead_id = _pod.member_id(project, "lead")
    if _models.AgentMeta.coerce_paused(_fleet.meta_get(lead_id, "paused", "")):
        _trace.trace_event(
            project,
            f"agent:{project}:dispatch",
            "lead",
            "paused_refused",
            _json.dumps({"reason": _fleet.meta_get(lead_id, "pausedReason", "") or "budget"}),
        )
        return None

    claimed: dict[str, Any] | None = None

    def _fn(doc: dict[str, Any]) -> dict[str, Any] | None:
        nonlocal claimed
        tasks_raw = doc.get("tasks")
        tasks = (
            [_normalize_task(t) for t in tasks_raw if isinstance(t, dict)]
            if isinstance(tasks_raw, list)
            else []
        )
        candidates = [i for i, t in enumerate(tasks) if _eligible_for_claim(t, resume=resume)]
        if not candidates:
            return None
        candidates.sort(
            key=lambda i: _PRIORITY_RANK.get(str(tasks[i].get("priority", "normal")), 1)
        )
        t = tasks[candidates[0]]
        t["status"] = "running"
        t["startedAt"] = _now()
        t["claimId"] = str(_uuid.uuid4())
        t["claimedAt"] = _now()
        t["claimPid"] = _os.getpid()
        t.pop("failureKind", None)
        claimed = dict(t)
        # A granted approval's gate-override is single-use — captured
        # into the claimed copy above, then cleared from the *stored* record
        # right here, atomically, so it can never leak into a later, unrelated
        # claim of this same task (e.g. a crash-and-`--resume`, or the task
        # revisiting the same pipeline position on a rework cycle).
        t.pop("gateOverridePipelineIndex", None)
        return {"tasks": tasks}

    doc = _store.read_modify_write(pod_task_list_path(project), _fn)
    if claimed is None:
        return None
    _ensure_task_worktree(project, claimed)
    resume_hops = [_hop_from_record(h) for h in claimed.get("hops", []) if isinstance(h, dict)]
    tasks_after = doc.get("tasks")
    _mem.sync_dispatch_tasks(
        _cfg.workspace_dir(lead_id), tasks_after if isinstance(tasks_after, list) else []
    )
    return claimed, resume_hops


def _persist_hop(project: str, task_id: str, hop: HopResult) -> None:
    """Append one just-completed hop to the task's record, called after every hop (not only
    at task end) so a crash loses at most the in-flight hop. Also refreshes ``claimedAt``,
    re-syncs the HEARTBEAT.md ledger, and touches the hop agent's tracked conversation, if any
    -- see pod-dispatch.spec.md ("Conversation registry auto-population"); a no-op if unwired."""

    def _fn(doc: dict[str, Any]) -> dict[str, Any] | None:
        tasks_raw = doc.get("tasks")
        tasks = tasks_raw if isinstance(tasks_raw, list) else []
        for t in tasks:
            if t.get("id") == task_id:
                hops = t.get("hops")
                if not isinstance(hops, list):
                    hops = []
                hops.append(_hop_record(hop))
                t["hops"] = hops
                t["costUsd"] = round(sum(float(h.get("costUsd", 0.0) or 0.0) for h in hops), 6)
                t["claimedAt"] = _now()
                return {"tasks": tasks}
        return None  # task no longer in the queue — nothing to persist

    doc = _store.read_modify_write(pod_task_list_path(project), _fn)
    tasks_after = doc.get("tasks")
    lead_id = _pod.member_id(project, "lead")
    _mem.sync_dispatch_tasks(
        _cfg.workspace_dir(lead_id), tasks_after if isinstance(tasks_after, list) else []
    )

    _conv.touch_for_hop_durable(
        agent_id=hop.member_id, task_ref=task_id, last_message=hop.output, now=_now()
    )


def _touch_claim(project: str, task_id: str) -> None:
    """Refresh a ``running`` task's ``claimedAt``, called before every retry attempt --
    without this, a long retry could push elapsed time past ``CLAIM_STALE_TIMEOUT`` and a
    *concurrent* dispatcher's ``_sweep_stale_claims`` would fail the task out from under the
    one still retrying it. Also re-syncs HEARTBEAT.md. No-op if not ``running``."""

    def _fn(doc: dict[str, Any]) -> dict[str, Any] | None:
        tasks_raw = doc.get("tasks")
        tasks = tasks_raw if isinstance(tasks_raw, list) else []
        for t in tasks:
            if t.get("id") == task_id and t.get("status") == "running":
                t["claimedAt"] = _now()
                return {"tasks": tasks}
        return None

    doc = _store.read_modify_write(pod_task_list_path(project), _fn)
    tasks_after = doc.get("tasks")
    lead_id = _pod.member_id(project, "lead")
    _mem.sync_dispatch_tasks(
        _cfg.workspace_dir(lead_id), tasks_after if isinstance(tasks_after, list) else []
    )


def _finalize_task(project: str, task_id: str, res: TaskResult) -> None:
    """Persist a task's terminal outcome (status/reason/hops/cost), clear its claim, and
    re-sync HEARTBEAT.md. The only trigger that ever *removes* a ledger entry --
    ``_claim_next_task``/``_persist_hop``/``_touch_claim`` only add or keep one current."""

    def _fn(doc: dict[str, Any]) -> dict[str, Any] | None:
        tasks_raw = doc.get("tasks")
        tasks = tasks_raw if isinstance(tasks_raw, list) else []
        for t in tasks:
            if t.get("id") == task_id:
                _apply_result(t, res)
                return {"tasks": tasks}
        return None

    doc = _store.read_modify_write(pod_task_list_path(project), _fn)
    tasks_after = doc.get("tasks")
    lead_id = _pod.member_id(project, "lead")
    _mem.sync_dispatch_tasks(
        _cfg.workspace_dir(lead_id), tasks_after if isinstance(tasks_after, list) else []
    )


def _sweep_stale_claims(project: str) -> None:
    """Crash recovery: fail a ``running`` task whose claim has gone stale (older than
    ``CLAIM_STALE_TIMEOUT``), tagging ``failureKind: "stale_claim"`` and leaving its
    persisted ``hops`` untouched for a later ``--resume`` (pod-dispatch.spec.md, "Per-hop
    incremental persistence and crash recovery"). Runs at the top of every ``dispatch_pod`` call."""
    now = _dt.datetime.now(_dt.UTC)
    swept: list[dict[str, Any]] = []

    def _fn(doc: dict[str, Any]) -> dict[str, Any] | None:
        tasks_raw = doc.get("tasks")
        tasks = (
            [_normalize_task(t) for t in tasks_raw if isinstance(t, dict)]
            if isinstance(tasks_raw, list)
            else []
        )
        changed = False
        for t in tasks:
            if t.get("status") != "running":
                continue
            claimed_at = _parse_iso(str(t.get("claimedAt") or ""))
            if claimed_at is None:
                continue
            if (now - claimed_at).total_seconds() <= _cfg.CLAIM_STALE_TIMEOUT:
                continue
            t["status"] = "failed"
            t["reason"] = "stale claim — dispatcher likely crashed mid-task"
            t["failureKind"] = "stale_claim"
            t["claimId"] = None
            swept.append(dict(t))
            changed = True
        return {"tasks": tasks} if changed else None

    _store.read_modify_write(pod_task_list_path(project), _fn)
    for t in swept:
        task_id = str(t.get("id", "task"))
        _trace.trace_event(
            project,
            f"agent:{project}:{task_id}",
            "lead",
            "stale_claim",
            _json.dumps({"task": task_id, "claimedAt": t.get("claimedAt")}),
        )


def _claim_stale_reason(task: dict[str, Any], now: _dt.datetime, lease_s: int) -> str:
    """Why *task*'s ``running`` claim is stale, or ``""``: the claiming process is gone, or the
    claim is older than *lease_s* (the pod's ``turnTimeoutS`` plus ``verifyTimeoutS``)."""
    pid = task.get("claimPid")
    if isinstance(pid, int) and not _sys.process_alive(pid):
        return f"claimant pid {pid} is gone"
    claimed_at = _parse_iso(str(task.get("claimedAt") or ""))
    if claimed_at is None:
        return ""
    if (now - claimed_at).total_seconds() > lease_s:
        return f"claim older than the {lease_s}s lease"
    return ""


def reclaim_stale_running(project: str) -> None:
    """``--resume``: settle every stale ``running`` claim to ``failed``/``stale_claim`` so the
    claim step that follows picks it up from its last persisted hop; audited ``task.reclaimed``."""
    now = _dt.datetime.now(_dt.UTC)
    lease_s = _resolve_timeout(None, pod_turn_timeout(project)) + _resolve_timeout(
        None, pod_verify_timeout(project)
    )
    reclaimed: list[tuple[str, str]] = []

    def _fn(doc: dict[str, Any]) -> dict[str, Any] | None:
        tasks_raw = doc.get("tasks")
        tasks = (
            [_normalize_task(t) for t in tasks_raw if isinstance(t, dict)]
            if isinstance(tasks_raw, list)
            else []
        )
        changed = False
        for t in tasks:
            if t.get("status") != "running":
                continue
            why = _claim_stale_reason(t, now, lease_s)
            if not why:
                continue
            t["status"] = "failed"
            t["reason"] = "stale claim — " + why
            t["failureKind"] = "stale_claim"
            t["claimId"] = None
            reclaimed.append((str(t.get("id", "task")), why))
            changed = True
        return {"tasks": tasks} if changed else None

    _store.read_modify_write(pod_task_list_path(project), _fn)
    for task_id, why in reclaimed:
        _audit.audit_log("task.reclaimed", f"{project}/{task_id}: {why}")


def retry_task(project: str, task_id: str) -> bool:
    """Re-queue one ``blocked`` or ``failed`` task: a locked flip to ``pending`` that keeps its
    hops and audits ``task.retry``. Returns False if not found or in any other status."""
    found = False

    def _fn(doc: dict[str, Any]) -> dict[str, Any] | None:
        nonlocal found
        tasks_raw = doc.get("tasks")
        tasks = tasks_raw if isinstance(tasks_raw, list) else []
        for t in tasks:
            if t.get("id") == task_id:
                _normalize_task(t)
                if t.get("status") not in ("blocked", "failed"):
                    return None
                t["status"] = "pending"
                for key in ("blockedReason", "failureKind", "reason", "completedAt"):
                    t.pop(key, None)
                found = True
                return {"tasks": tasks}
        return None

    _store.read_modify_write(pod_task_list_path(project), _fn)
    if found:
        _audit.audit_log("task.retry", f"{project}/{task_id}")
    return found


def unblock_pod(project: str) -> int:
    """Un-block every ``blocked`` task in *project*'s queue. Wired to ``docket pod set
    budgetUsd`` and ``docket run --resume`` -- the sanctioned re-entry paths besides ``retry_task``.
    Returns the number of tasks unblocked."""
    path = pod_task_list_path(project)
    if not path.parent.is_dir():
        return 0
    count = 0

    def _fn(doc: dict[str, Any]) -> dict[str, Any] | None:
        nonlocal count
        tasks_raw = doc.get("tasks")
        tasks = tasks_raw if isinstance(tasks_raw, list) else []
        changed = False
        for t in tasks:
            _normalize_task(t)
            if t.get("status") == "blocked":
                t["status"] = "pending"
                t.pop("blockedReason", None)
                count += 1
                changed = True
        return {"tasks": tasks} if changed else None

    _store.read_modify_write(path, _fn)
    return count


TASK_GRANT_CAP = 20


def resolve_waiting_approval(
    token: str, decision: str, *, channel: str = "", actor: str = ""
) -> bool:
    """:func:`resolve_waiting_approval_detail`'s boolean."""
    return resolve_waiting_approval_detail(token, decision, channel=channel, actor=actor)[0]


def resolve_waiting_approval_detail(
    token: str, decision: str, *, channel: str = "", actor: str = ""
) -> tuple[bool, str]:
    """React to a just-applied approval decision by mutating the dispatch task it gated, if
    any -- never mutates the approval record itself, only reacts to a transition
    ``core/approval.py`` already made. See pod-dispatch.spec.md ("require_approval gate and
    waiting_approval") for the pre-hop gate's grant (-> ``pending`` + gate override) and deny
    (-> ``failed``, ``failureKind: "approval_denied"``) outcomes.

    A **parked** in-turn call (ADR 0016 SS2, ``context["parked"] is True``) carries no
    ``taskId`` -- ``core/tools.py``'s ``_park_call`` has no task to name -- so its task is
    found by matching ``approvalToken`` directly instead; a grant appends
    ``{token, tool, argsDigest}`` to the task's ``pregrants`` for ``_compose_hop`` to carry
    into the re-run, and does **not** set ``gateOverridePipelineIndex`` (that field is for
    skipping a pre-hop gate, not for re-running an already-attempted hop -- the resumed hop
    re-runs by ``_replay_pipeline_position``'s own ``hop.parked`` handling instead). A plain
    in-turn ``wait``-mode ask also carries no ``taskId`` (its wait blocks the calling thread
    directly, so there is no task-level state to update here) and is unaffected: not parked
    and no ``taskId`` still no-ops, exactly as before.

    A parked grant whose record chose ``approve_task`` also appends the exact
    ``(tool, argsDigest)`` to the task's ``taskGrants`` (at most ``TASK_GRANT_CAP``);
    ``_compose_hop`` mints a single-use pre-grant from each for every later hop.

    Returns ``(updated, note)``: ``False`` as a harmless no-op for an unrelated/already-resolved
    token or a mismatched task; *note* is non-empty only when a task-wide grant was refused."""
    try:
        rec = _ap.approval_get(token)
    except _ap.ApprovalError:
        return False, ""
    context = rec.get("context")
    context = context if isinstance(context, dict) else {}
    parked = bool(context.get("parked"))
    task_id = str(context.get("taskId", ""))
    project = str(rec.get("project", ""))
    if not project or (not task_id and not parked):
        return False, ""

    updated = False
    note = ""
    resolved_task_id = task_id

    def _fn(doc: dict[str, Any]) -> dict[str, Any] | None:
        nonlocal updated, resolved_task_id, note
        tasks_raw = doc.get("tasks")
        tasks = tasks_raw if isinstance(tasks_raw, list) else []
        for t in tasks:
            if task_id:
                if t.get("id") != task_id:
                    continue
            elif t.get("approvalToken") != token:
                continue
            if t.get("status") != "waiting_approval" or t.get("approvalToken") != token:
                return None
            resolved_task_id = str(t.get("id", ""))
            pending_index = t.get("pendingApprovalIndex")
            t.pop("approvalToken", None)
            t.pop("pendingApprovalIndex", None)
            if decision == "granted":
                t["status"] = "pending"
                if parked:
                    pregrants_raw = t.get("pregrants")
                    pregrants = list(pregrants_raw) if isinstance(pregrants_raw, list) else []
                    pregrants.append(
                        {
                            "token": token,
                            "tool": str(context.get("tool", "")),
                            "argsDigest": str(context.get("argsDigest", "")),
                        }
                    )
                    t["pregrants"] = pregrants
                    if context.get("optionId") == "approve_task":
                        note = _append_task_grant(
                            t, token, context, str(rec.get("role", "")), channel, actor
                        )
                else:
                    t["gateOverridePipelineIndex"] = pending_index
            else:
                t["status"] = "failed"
                t["reason"] = "approval denied"
                t["failureKind"] = "approval_denied"
                t["completedAt"] = _now()
                t["claimId"] = None
                t.pop("taskGrants", None)
            updated = True
            return {"tasks": tasks}
        return None

    _store.read_modify_write(pod_task_list_path(project), _fn)
    if updated:
        _trace.trace_event(
            project,
            f"agent:{project}:{resolved_task_id}",
            "lead",
            "approval_resumed" if decision == "granted" else "approval_task_denied",
            _json.dumps({"task": resolved_task_id, "token": token}),
        )
    return updated, note


def _append_task_grant(
    task: dict[str, Any],
    token: str,
    context: dict[str, Any],
    role: str,
    channel: str,
    actor: str,
) -> str:
    """Record the ``approve_task`` grant for *role* on *task* unless it is already there or the
    task is at ``TASK_GRANT_CAP``; returns a refusal note, ``""`` otherwise."""
    tool = str(context.get("tool", ""))
    digest = str(context.get("argsDigest", ""))
    if not tool or not digest or not role:
        return ""
    raw = task.get("taskGrants")
    grants = [g for g in raw if isinstance(g, dict)] if isinstance(raw, list) else []
    if any(
        g.get("tool") == tool and g.get("argsDigest") == digest and g.get("role") == role
        for g in grants
    ):
        return ""
    channel = channel if channel in _ap.APPROVAL_CHANNELS else "unknown"
    if len(grants) >= TASK_GRANT_CAP:
        _audit.audit_log(
            "approval.task_grant_refused",
            f"token={token} tool={tool} cap={TASK_GRANT_CAP} channel={channel}",
        )
        return (
            f"This task already has {TASK_GRANT_CAP} task-wide grants; this call was approved "
            "once only."
        )
    grants.append(
        {
            "tool": tool,
            "argsDigest": digest,
            "role": role,
            "token": token,
            "grantedAt": _now(),
            "actor": actor,
            "channel": channel,
        }
    )
    task["taskGrants"] = grants
    _audit.audit_log(
        "approval.task_grant",
        f"token={token} tool={tool} channel={channel} actor={actor or '?'}",
    )
    return ""


def _mint_task_grant_pregrants(ctx: _UnitContext, role: str) -> list[dict[str, str]]:
    """One fresh single-use pre-grant per task-wide grant made for *role*, bound to this project
    and role: a grant never reaches a hop of another role."""
    raw = ctx.task.get("taskGrants")
    if not isinstance(raw, list) or not raw:
        return []
    deadline = _dt.datetime.now(_dt.UTC) + _dt.timedelta(
        hours=_pod_settings(ctx.project).approval_expiry_hours
    )
    minted: list[dict[str, str]] = []
    for grant in raw[:TASK_GRANT_CAP]:
        if not isinstance(grant, dict) or grant.get("role") != role:
            continue
        tool = str(grant.get("tool", ""))
        digest = str(grant.get("argsDigest", ""))
        channel = str(grant.get("channel", ""))
        try:
            pre = _ap.create_pregrant(
                ctx.project,
                role,
                tool,
                digest,
                task_id=ctx.task_id,
                expires_at=deadline.isoformat(),
                channel=channel if channel in _ap.APPROVAL_CHANNELS else "cli",
                actor=str(grant.get("actor") or "approve_task"),
            )
        except _ap.ApprovalError:
            continue
        minted.append({"token": pre, "tool": tool, "argsDigest": digest})
    return minted


def dispatch_pod(
    project: str,
    *,
    runner: Runner | None = None,
    turn_timeout: int | None = None,
    verify_timeout: int | None = None,
    max_tasks: int | None = None,
    resume: bool = False,
    sleep: Callable[[float], None] | None = None,
    spec: _pipeline.PipelineSpec | None = None,
    variables: dict[str, Any] | None = None,
    approval_default: Literal["wait", "park"] = "wait",
) -> list[TaskResult]:
    """Dispatch a pod's pending tasks through the pipeline (highest priority first), looping
    ``dispatch_task`` over locked claims until none remain or *max_tasks* is hit --
    see ``dispatch_task`` and pod-dispatch.spec.md for the full claiming/crash-recovery/retry
    contract. A stale ``running`` claim is swept first; pass *resume* to also reclaim those
    and continue from the last persisted hop. Returns one TaskResult per task attempted.
    Raises DispatchError if the pod has no Lead, or -- checked once, here, before any task is
    claimed or any hop runs -- if *variables* (the caller-supplied pipeline variable mapping;
    e.g. the serve webhook's resolved body, or ``docket run --var``) leaves any step's
    own ``instructions`` with an unresolved ``${var}`` reference. See
    specs/functional/pipeline-format.spec.md ("Variables"). *approval_default* is this caller's
    own resolution for an unset pod ``approvalMode`` (ADR 0016 SS2) -- forwarded to every task's
    ``dispatch_task`` call unchanged; an explicit pod value always wins over it."""
    pod_pipeline(project)  # validates pod/lead up front
    effective_spec = effective_pipeline(project, spec)
    try:
        resolved_vars = _pipeline.resolve_variables(effective_spec, variables)
    except _pipeline.VariableError as exc:
        raise DispatchError(str(exc)) from exc
    missing = _pipeline.unresolved_step_variables(effective_spec, resolved_vars)
    if missing:
        raise DispatchError(
            "refusing dispatch: step instructions reference unresolved pipeline "
            "variable(s): " + ", ".join(missing)
        )
    _sweep_stale_claims(project)
    if resume:
        reclaim_stale_running(project)

    results: list[TaskResult] = []
    while max_tasks is None or len(results) < max_tasks:
        claim = _claim_next_task(project, resume=resume)
        if claim is None:
            break
        task, resume_hops = claim
        task_id = str(task.get("id", "task"))

        def _persist(hop: HopResult, _project: str = project, _task_id: str = task_id) -> None:
            _persist_hop(_project, _task_id, hop)

        def _touch(_project: str = project, _task_id: str = task_id) -> None:
            _touch_claim(_project, _task_id)

        res = dispatch_task(
            project,
            task,
            runner=runner,
            turn_timeout=turn_timeout,
            verify_timeout=verify_timeout,
            resume_from=resume_hops,
            on_hop=_persist,
            on_retry=_touch,
            sleep=sleep,
            spec=spec,
            variables=resolved_vars,
            approval_default=approval_default,
        )
        _finalize_task(project, task_id, res)
        results.append(res)
        if res.status == "blocked":
            break  # budget is pod-wide; no point trying further tasks this run
    return results


def dispatchable_pods() -> list[str]:
    """Projects that have a provisioned Lead (and therefore a dispatchable pod)."""
    all_ids = [a.id for a in _fleet.list_agents()]
    projects: list[str] = []
    for aid in all_ids:
        proj = _pod.pod_of(aid)
        if proj and aid == _pod.member_id(proj, "lead") and proj not in projects:
            projects.append(proj)
    return projects


def pod_roster() -> list[dict[str, Any]]:
    """Every provisioned pod (grouped by project, alphabetical) with its member roster. Pure
    data assembly for ``docket start --mcp``'s ``pods`` tool, mirroring ``cli/_pod.py``'s
    ``_pod_list``; lives here (not ``core/pod.py``) to keep that module I/O-free."""
    all_ids = [a.id for a in _fleet.list_agents()]
    projects = sorted({p for aid in all_ids if (p := _pod.pod_of(aid))})

    out: list[dict[str, Any]] = []
    for project in projects:
        members = _pod.members_of(all_ids, project)
        out.append(
            {
                "project": project,
                "members": [
                    {"id": mid, "role": role, "model": _fleet.meta_get(mid, "model", "")}
                    for mid, role, _idx in members
                ],
            }
        )
    return out


# A "dispatch every pod in one sweep" helper doesn't exist here on purpose —
# not an oversight. `serve.py`'s sweep loop instead iterates
# `dispatchable_pods()` and calls `dispatch_pod()` per pod through
# `core.runs.execute` (see `tests/guards/test_no_suppressed_dispatch.py`).
# A single-sweep helper's natural shape — one record for the whole sweep,
# catching and swallowing `DispatchError` per pod — loses per-pod granularity
# in the run registry (one run id per pod) and hides a real error instead of
# surfacing it. Do not reintroduce that shape.
