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
import json as _json
import time as _time
import uuid as _uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote as _url_quote

import docket.config as _cfg
from docket.core import approval as _ap
from docket.core import archetypes as _archetypes
from docket.core import blueprints as _blueprints
from docket.core import conversations as _conv
from docket.core import fleet as _fleet
from docket.core import handoff as _handoff
from docket.core import memory as _mem
from docket.core import models as _models
from docket.core import orchestrator as _orch
from docket.core import pipeline as _pipeline
from docket.core import pod as _pod
from docket.core import policy as _policy
from docket.core import runs as _runs
from docket.core import runtime_driver as _rd
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
    # to ``role`` on both write and read, so a legacy queue record with no
    # persisted ``stepId`` (or a hand-built HopResult in an existing test)
    # replays exactly as before — the built-in default pipeline's step ids
    # equal their role names, so this is never a behavior change for the four
    # built-in roles, only a real distinction for a custom pipeline whose
    # step id differs from its target role (see ``_replay_pipeline_position``).
    step_id: str = ""
    # This hop's structured handoff artifact. ``None`` at construction
    # time backfills in ``__post_init__`` to
    # ``HandoffArtifact.from_legacy_output(output)`` — every ``HopResult``
    # therefore always carries a real artifact once constructed, whether built
    # explicitly with one (a live hop — see ``_execute_unit``) or reconstructed
    # from a legacy persisted record with no ``artifact`` key at all
    # (``_hop_from_record``'s backward-compatibility path), or simply
    # hand-built by an existing test that only ever passed ``output=``.
    artifact: _handoff.HandoffArtifact | None = None
    # A mechanical gate whose command was unset — a real, intentional "no
    # check configured" state, not a failure. ``core/`` never prints; this
    # flag is this run's own in-memory signal only (not persisted — see
    # ``_hop_record``) for ``cli/``'s dispatch renderer to print the notice.
    verification_skipped: bool = False

    def __post_init__(self) -> None:
        if self.artifact is None:
            self.artifact = _handoff.HandoffArtifact.from_legacy_output(self.output)

    def rendered_artifact(self) -> str:
        """This hop's artifact rendered to text — never ``None`` after construction."""
        assert self.artifact is not None
        return self.artifact.render()


@dataclass
class TaskResult:
    """Outcome of driving one task through the whole pipeline."""

    task_id: str
    status: str  # "done" | "failed" | "blocked" | "waiting_approval" | "cancelled"
    reason: str = ""
    hops: list[HopResult] = field(default_factory=list)
    # Only meaningful when status == "waiting_approval" — the token the
    # gate created and the pipeline position it stopped at, so the caller
    # (``_apply_result``) can persist enough to resume correctly on a grant.
    approval_token: str = ""
    pending_approval_index: int | None = None

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


# Fields a v2 task record may lack when loaded from a legacy TASK_LIST.json.
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
    """Backfill v2 fields onto a task dict in place (returns it) so a legacy queue file,
    written before claims/resume/uuid ids existed, loads with no separate migration step.
    """
    for key, default in _TASK_SCALAR_DEFAULTS.items():
        task.setdefault(key, default)
    if not isinstance(task.get("hops"), list):
        task["hops"] = []
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
            _json.dumps({"hook": "pre_input", "policy": hit.policy_id, "action": hit.policy_id}),
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
) -> dict[str, Any]:
    """Locked read-modify-write, so concurrent ``delegate`` calls cannot clobber each other's
    task. Raises DispatchError with no Lead workspace or a ``pre_input`` block (nothing
    persisted). ``trusted`` overrides only this check, never the persisted ``source``."""
    path = pod_task_list_path(project)
    if not path.parent.is_dir():
        raise DispatchError(f"no pod for '{project}' (run from its directory: docket init)")

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


def _blueprint_pipeline(project: str) -> _pipeline.PipelineSpec:
    """The resolved base pipeline for a caller-supplied-spec-free dispatch: the Lead's
    ``blueprint`` meta's ``default_pipeline`` when that meta names a known blueprint, else the
    built-in default (see pod-dispatch.spec.md, "Pipeline order and participation")."""
    lead_id = _pod.member_id(project, "lead")
    name = _fleet.meta_get(lead_id, "blueprint", "")
    if name:
        try:
            return _blueprints.get_blueprint(name).default_pipeline
        except _blueprints.BlueprintError:
            pass  # absent/unknown blueprint -- fall through to the built-in default
    builtin = _pipeline.load_pipeline(None).spec
    assert builtin is not None  # load_pipeline(None) always succeeds
    return builtin


def effective_pipeline(project: str, spec: _pipeline.PipelineSpec | None) -> _pipeline.PipelineSpec:
    """The PipelineSpec this dispatch actually runs (see pod-dispatch.spec.md, "Pipeline order
    and participation"). A caller-supplied *spec* is never patched -- only the ``None`` default
    gets the rework-budget patch. Public so ``cli/_pipeline.py`` renders this same resolved spec."""
    if spec is not None:
        return spec
    builtin = _blueprint_pipeline(project)
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


def pod_budget(project: str) -> float:
    """The pod's USD budget cap (Lead's ``budgetUsd``), 0.0 = unlimited."""
    lead_id = _pod.member_id(project, "lead")
    raw = _fleet.meta_get(lead_id, "budgetUsd", "")
    try:
        return float(raw) if raw else 0.0
    except ValueError:
        return 0.0


def pod_max_rework_cycles(project: str) -> int:
    """Bounded rework budget for a REQUEST-CHANGES review: Lead's ``maxReworkCycles`` meta
    (default ``1``; ``0`` disables rework -- a hard gate, no retry). See pod-dispatch.spec.md
    ("Reviewer verdict gate and bounded rework")."""
    lead_id = _pod.member_id(project, "lead")
    raw = _fleet.meta_get(lead_id, "maxReworkCycles", "")
    if not raw:
        return 1
    try:
        return max(0, int(raw))
    except ValueError:
        return 1


def _retries_for_role(role: str) -> int:
    """Max retry attempts (after the first try) for one role's hop."""
    return _cfg.DISPATCH_RETRIES_PER_ROLE.get(role, _cfg.DISPATCH_RETRIES_DEFAULT)


def _lead_meta_timeout(project: str, field_name: str) -> int | None:
    """Read a positive-int timeout field from the pod's Lead meta, if set validly."""
    lead_id = _pod.member_id(project, "lead")
    raw = _fleet.meta_get(lead_id, field_name, "")
    if not raw:
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    return value if value > 0 else None


def pod_turn_timeout(project: str) -> int | None:
    """The pod's configured agent-turn timeout (Lead's ``turnTimeoutS``), if set."""
    return _lead_meta_timeout(project, "turnTimeoutS")


def pod_verify_timeout(project: str) -> int | None:
    """The pod's configured verifyCmd timeout (Lead's ``verifyTimeoutS``), if set."""
    return _lead_meta_timeout(project, "verifyTimeoutS")


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
        totals = _utils.aggregate_cost(mid)
        if totals.input_tokens == 0 and totals.output_tokens == 0:
            continue
        model = str(_fleet.meta_get(mid, "model", "") or "")
        est = _utils.estimate_cost_usd(model, totals)
        if est is not None:
            total_est += est
            any_estimate = True
    return round(total_est, 6), any_estimate


def _pause_lead_for_budget(project: str) -> None:
    """Mark the pod's Lead paused once budget is reached, so ``_claim_next_task`` refuses
    every further claim (one write here, not a per-hop recheck) until an operator clears it
    (``docket profile <lead-id> --resume``). Idempotent."""
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


def _hop_message(
    task: dict[str, Any],
    role: str,
    prior: list[HopResult],
    rework_hop: HopResult | None = None,
) -> tuple[str, _HopComposition]:
    """Build one role's message via ``core/context.py``'s token-budget compiler (see
    pod-dispatch.spec.md, "Bounded hop prompts"). The task description is never truncated;
    each prior artifact is fit to a per-role share, shedding ``DROP_ORDER`` fields before
    ``summary``, which is only ever truncated with a marker, never silently dropped.
    *rework_hop* gets the implementer's full carryover budget in its own section, deliberately
    excluded from the generic per-hop loop (not left to recency ranking) since it addresses
    what the rework hop exists for. Returns the message plus a ``_HopComposition``."""
    from docket.core import context as _ctx

    desc = str(task.get("description", "")).strip()
    if role == "lead":
        message = (
            f"You are the pod Lead. Decompose this task into a concrete plan for "
            f"the Implementer (you never edit code yourself):\n\n{desc}"
        )
        comp = _HopComposition(
            description_bytes=len(desc.encode("utf-8")), total_bytes=len(message.encode("utf-8"))
        )
        return message, comp

    if role == "implementer":
        instructions = (
            "You are the Implementer. Address the reviewer's REQUEST-CHANGES "
            "above, then implement the change in the workspace."
            if rework_hop is not None
            else "You are the Implementer. Implement the change in the workspace."
        )
    elif role == "reviewer":
        instructions = (
            "You are the Reviewer. Review the diff (read-only). Start exactly one "
            "output line with APPROVE or REQUEST-CHANGES (case-insensitive); "
            "reasons may come before or after that marker line."
        )
    elif role == "tester":
        instructions = (
            "You are the Tester. Validate behaviour only. Start exactly one output "
            "line with PASS or FAIL (case-insensitive); evidence may come before or "
            "after that marker line."
        )
    else:
        instructions = ""

    # The role's total token budget, minus what the immutable task
    # description and this role's own fixed instruction footer already cost
    # — what's left is what the carryover (rework note + prior hops) may
    # spend. This is what makes "the composed message fits its role's
    # budget" a real, checkable property rather than an aspiration: the two
    # pieces that are never shed are accounted for before anything
    # sheddable is given a share.
    total_budget = _ctx.budget_for_role(role)
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


def _implementer_diff_probe(member_id: str, role: str) -> tuple[list[str], str | None]:
    """Real ``files_changed``/``diff_ref`` for an Implementer hop (every other role gets
    ``([], None)``); resolves the same working tree the verify gate uses via
    ``core.pod.resolve_member_cwd`` so the two can never disagree, degrading to ``([], None)``
    rather than raising when git is missing or unavailable. See pod-dispatch.spec.md."""
    if role != "implementer":
        return [], None
    worktree_dir = str(_fleet.meta_get(member_id, "worktreeDir", "") or "")
    member_codebase = str(_fleet.meta_get(member_id, "codebase", "") or "")
    cwd = _pod.resolve_member_cwd(member_id, worktree_dir, member_codebase)
    if not _sys.git_available() or not _sys.git_is_repo(cwd):
        return [], None
    files_changed = _sys.git_changed_files(cwd)
    diff_ref = _sys.git_current_branch(cwd) or None
    return files_changed, diff_ref


def _prior_implementer_worktree(prior: list[HopResult]) -> str:
    """Effective checkout produced by the latest successful Implementer hop."""
    for hop in reversed(prior):
        if hop.role == "implementer" and hop.ok:
            return str(_fleet.meta_get(hop.member_id, "worktreeDir", "") or "")
    return ""


def _hop_record(h: HopResult) -> dict[str, Any]:
    """Persisted shape of one hop (round-trips via ``_hop_from_record``; pod-dispatch.spec.md,
    "Structured handoff artifacts"). ``artifact`` is persisted alongside legacy ``output``, never
    replacing it; ``verification_skipped`` stays unpersisted -- an in-memory signal for ``cli/``."""
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
    }


def _hop_from_record(rec: dict[str, Any]) -> HopResult:
    """Reconstruct a HopResult from a persisted hop record (for resume). A legacy record with
    no (or invalid) ``artifact`` degrades via ``HandoffArtifact.from_legacy_output``, treating
    raw ``output`` as ``summary`` -- see pod-dispatch.spec.md ("Structured handoff artifacts")."""
    output = str(rec.get("output", ""))
    artifact_raw = rec.get("artifact")
    artifact: _handoff.HandoffArtifact | None = None
    if isinstance(artifact_raw, dict):
        try:
            artifact = _handoff.HandoffArtifact.model_validate(artifact_raw)
        except Exception:
            artifact = None
    if artifact is None:
        artifact = _handoff.HandoffArtifact.from_legacy_output(output)
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
    )


@dataclass
class _ResumePosition:
    """Where a (possibly resumed) run should continue: ``pipeline_index`` into
    ``runtime_steps``; ``rework_counts`` (cycles consumed, keyed by gated step id);
    ``rework_hop`` (set only when resuming into a rework target)."""

    pipeline_index: int
    rework_counts: dict[str, int]
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
    is decided/persisted synchronously in the same ``dispatch_task`` call, and a plain-``failed``
    task is never reclaimed for resume (only ``stale_claim``-tagged)."""
    id_to_index = {node.step_id: i for i, node in enumerate(runtime_steps)}
    pi = 0
    rework_counts: dict[str, int] = {}
    rework_hop: HopResult | None = None
    for hop in prior:
        step_id = hop.step_id or hop.role
        idx = id_to_index.get(step_id)
        if idx is None:
            continue  # a parallel-group child's hop — handled by the trailing check below
        node = runtime_steps[idx]
        gate = node.gate if isinstance(node, _orch.PlannedUnit) else None
        if isinstance(gate, _pipeline.VerdictGate) and gate.rework is not None:
            verdict = hop.artifact.verdict if hop.artifact is not None else None
            if verdict is None:
                # New-format records persist the normalized verdict in the
                # artifact. Legacy/malformed records have no usable value and
                # retain their pre-artifact raw-output fallback.
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
    return _ResumePosition(pipeline_index=pi, rework_counts=rework_counts, rework_hop=rework_hop)


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
    """What happened running one ``PlannedUnit``'s hop. ``kind`` is one of ``"advance" |
    "rework" | "blocked" | "waiting_approval" | "failed" | "cancelled"``; ``hops`` is empty
    for ``blocked``/``waiting_approval`` (the gate stopped before any turn ran)."""

    kind: str
    hops: list[HopResult] = field(default_factory=list)
    reason: str = ""
    rework_target_index: int | None = None
    approval_token: str = ""
    pending_approval_index: int | None = None


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
    message, composition = _hop_message(ctx.task, role, prior_snapshot, rework_hop)
    pipeline_worktree = ""
    if role not in {"lead", "implementer"}:
        pipeline_worktree = _prior_implementer_worktree(prior_snapshot)
        if pipeline_worktree:
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
    ``retries``/``timeout`` override wins over the pod's role-based budget and turn timeout."""
    retry_budget = node.retries if node.retries is not None else _retries_for_role(role)
    hop_timeout = node.timeout if node.timeout is not None else ctx.resolved_turn_timeout

    # Record the production driver's spawned pid as in-flight for
    # `docket runs cancel` — only while the subprocess is actually
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
                }
            ),
        )
        # A retry means the dispatcher is alive and making forward progress,
        # not crashed — refresh the claim before the backoff sleep so a
        # concurrent dispatcher's stale-claim sweep never mistakes it for one
        # (see the module docstring / _touch_claim).
        if ctx.on_retry is not None:
            ctx.on_retry()
        ctx.do_sleep(_cfg.DISPATCH_RETRY_BACKOFF_S * attempt)
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
                _json.dumps(
                    {"hook": "pre_output", "policy": hit.policy_id, "action": hit.policy_id}
                ),
            )
            if hop_ok:
                hop_ok = False
                hop_error = f"blocked by guardrail policy '{hit.policy_id}'"
    return hop_output, hop_ok, hop_error


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
    if hop_ok:
        files_changed, diff_ref = _implementer_diff_probe(member_id, role)
    artifact = _handoff.HandoffArtifact(
        summary=hop_output,
        verdict=verdict,
        files_changed=files_changed,
        diff_ref=diff_ref,
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
    )


def _persist_hop_and_trace(
    ctx: _UnitContext,
    role: str,
    hop: HopResult,
    run_res: _rd.TurnResult,
    hop_ok: bool,
    hop_error: str,
) -> _UnitOutcome | None:
    """Persist this hop and trace its result; short-circuit a failed hop. Persisted
    immediately, not deferred to a group join, so a crash in a sibling child never loses an
    already-completed hop. Returns the terminal outcome, or ``None`` to proceed to the gate."""
    if ctx.on_hop is not None:
        ctx.on_hop(hop)

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

    if not hop_ok:
        if run_res.failure_kind == "run_cancelled":
            return _UnitOutcome(
                kind="cancelled",
                hops=[hop],
                reason="run cancellation requested",
            )
        return _UnitOutcome(
            kind="failed",
            hops=[hop],
            reason=f"{role} hop failed: {hop_error or 'no result'}",
        )
    return None


def _evaluate_mechanical_gate(
    ctx: _UnitContext,
    gate: _pipeline.MechanicalGate,
    role: str,
    member_id: str,
    hop: HopResult,
) -> _UnitOutcome:
    """A ``MechanicalGate``: run ``verifyCmd`` (or the gate's own command) and gate on its
    exit, in the dir from ``core.pod.resolve_member_cwd`` (shared with cli/_pod.py so the two
    never disagree). See pod-dispatch.spec.md ("Implementer verification gate")."""
    verify_cmd = gate.command or str(_fleet.meta_get(member_id, "verifyCmd", "") or "")
    if not verify_cmd:
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

    worktree_dir = str(_fleet.meta_get(member_id, "worktreeDir", "") or "")
    member_codebase = str(_fleet.meta_get(member_id, "codebase", "") or "")
    cwd = _pod.resolve_member_cwd(member_id, worktree_dir, member_codebase)
    # The verify command gets its own timeout, decoupled from the agent-turn
    # timeout above — a 20-minute test suite and a hung LLM turn are no longer
    # forced to share one budget.
    mech_timeout = gate.timeout or ctx.resolved_verify_timeout
    passed, raw_output = _sys.run_verify_cmd(verify_cmd, cwd, mech_timeout)
    redacted = _trace.redact(raw_output)
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
    return _UnitOutcome(kind="advance", hops=[hop])


def _evaluate_verdict_gate(
    ctx: _UnitContext,
    gate: _pipeline.VerdictGate,
    node: _orch.PlannedUnit,
    role: str,
    hop: HopResult,
) -> _UnitOutcome:
    """A ``VerdictGate``: pass/rework/fail on the hop's already-parsed verdict (reused from
    the hop's own artifact, never reparsed from ``run_res.output`` -- single source of truth).
    """
    assert hop.artifact is not None
    verdict = hop.artifact.verdict
    hop_output = hop.output
    pass_set = _orch.normalize_values(gate.pass_values, gate.case_sensitive)
    if verdict is not None and verdict in pass_set:
        return _UnitOutcome(kind="advance", hops=[hop])

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
        return _evaluate_mechanical_gate(ctx, gate, role, member_id, hop)

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
    run_res, attempt = _run_hop_turn(ctx, node, role, member_id, history_session_key, message, env)

    hop_output, hop_ok, hop_error = _apply_output_guardrails(ctx, role, run_res)

    hop = _build_hop_result(
        ctx, node, role, member_id, run_res, hop_output, hop_ok, hop_error, attempt
    )

    early_outcome = _persist_hop_and_trace(ctx, role, hop, run_res, hop_ok, hop_error)
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
) -> tuple[tuple[_orch.PlannedNode, ...], dict[str, int]]:
    """Resolve *spec* (or this pod's default pipeline) against the pod's live roster into
    this run's ordered, runnable steps. Assumes the caller already validated the pod/Lead
    exist; this only builds the plan, it does not itself raise for a missing pod."""
    effective_spec = effective_pipeline(project, spec)
    registry = _archetypes.load_registry()
    roster = pod_full_roster(project)
    plan = _orch.resolve_plan(effective_spec, roster, registry=registry)
    runtime_steps = plan.runnable_nodes()
    id_to_index = {node.step_id: i for i, node in enumerate(runtime_steps)}
    return runtime_steps, id_to_index


def _resolve_resume_state(
    runtime_steps: tuple[_orch.PlannedNode, ...], resume_from: list[HopResult] | None
) -> tuple[list[HopResult], int, dict[str, int], dict[int, HopResult]]:
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
    return prior, resume_pos.pipeline_index, dict(resume_pos.rework_counts), pending_rework_by_index


def _resolve_gate_override(task: dict[str, Any]) -> int | None:
    """A granted approval's single-use override for this one claim (see
    ``_claim_next_task``), consumed the first time this run reaches that pipeline position,
    so a later hop at the same position (a rework cycle) still gates normally."""
    override_index = task.get("gateOverridePipelineIndex")
    return override_index if isinstance(override_index, int) else None


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
    ``_persist_hop_and_trace``). The only backward move is a bounded rework cycle, jumping
    back to the gate's declared target."""
    while pipeline_index < len(runtime_steps):
        node = runtime_steps[pipeline_index]

        if isinstance(node, _orch.PlannedGroup):
            outcome = _run_group_node(ctx, node, prior, pipeline_index)
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
) -> TaskResult:
    """Drive one task through the pod pipeline, hop by hop. Full contract: pod-dispatch.spec.md
    ("Pipeline order and participation", "Per-hop incremental persistence and crash recovery",
    "Retries and the failure-kind taxonomy", "Generalized gate execution", "Parallel step
    groups"). Budget is checked before each hop; a failed hop stops the pipeline except for a
    bounded rework loop re-running a verdict gate's declared target up to its own cycle budget.
    *spec* ``None`` resolves the pod's zero-migration pipeline; *resume_from* seeds hops
    completed before a crash (skipped, not re-invoked); *turn_timeout*/*verify_timeout* override
    the pod Lead's meta then ``DEFAULT_TIMEOUT``, unless a step declares its own. *on_retry*
    fires before each retry so the caller can refresh the task's claim before it goes stale."""
    run = runner or _dr.default_driver().run_turn
    # pid tracking (for `docket runs cancel`) only makes sense for a real
    # OS process, i.e. the production driver — never an injected test
    # runner/fake, none of which accept an `on_spawn` kwarg (and none of which
    # have a process to report anyway). Gating on `runner is None` (rather
    # than duck-typing) keeps every existing 5-arg-Callable test double
    # working completely unchanged.
    track_pid = runner is None
    do_sleep = sleep or _time.sleep
    task_id = str(task.get("id", "task"))
    session_id = f"agent:{project}:{task_id}"
    pod_pipeline(project)  # validates pod/lead up front (raises DispatchError otherwise)
    cap = pod_budget(project)
    resolved_turn_timeout = _resolve_timeout(turn_timeout, pod_turn_timeout(project))
    resolved_verify_timeout = _resolve_timeout(verify_timeout, pod_verify_timeout(project))

    runtime_steps, id_to_index = _resolve_pipeline_steps(project, spec)
    prior, pipeline_index, rework_counts, pending_rework_by_index = _resolve_resume_state(
        runtime_steps, resume_from
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
    )

    _trace.trace_event(
        project,
        session_id,
        "lead",
        "session_start",
        _json.dumps({"source": "dispatch", "task": task_id, "resumed": bool(prior)}),
    )

    result = TaskResult(task_id=task_id, status="done", hops=list(prior))

    _run_pipeline(ctx, runtime_steps, pipeline_index, pending_rework_by_index, result, prior)

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
    "blocked and terminal-failure re-entry"). ``blocked``/``waiting_approval`` are never
    rewritten to ``pending`` here, only via ``unblock_pod``/``retry_task``/
    ``resolve_waiting_approval``. Stays pure -- HEARTBEAT.md sync lives in ``_finalize_task``."""
    task["status"] = res.status
    task["reason"] = res.reason
    task["hops"] = [_hop_record(h) for h in res.hops]
    task["costUsd"] = res.cost_usd
    task["claimId"] = None
    if res.status == "blocked":
        task["blockedReason"] = res.reason
    elif res.status == "waiting_approval":
        task["approvalToken"] = res.approval_token
        task["pendingApprovalIndex"] = res.pending_approval_index
    else:
        task["completedAt"] = _now()
        task.pop("failureKind", None)  # a fresh terminal result supersedes any stale-claim marker


def _eligible_for_claim(t: dict[str, Any], *, resume: bool) -> bool:
    """Whether *t* can be claimed by this dispatch run. See pod-dispatch.spec.md ("Claiming"):
    ``pending`` always is; a ``stale_claim``-tagged ``failed`` only when *resume* is set;
    ``waiting_approval`` never."""
    status = t.get("status")
    if status == "pending":
        return True
    return bool(resume and status == "failed" and t.get("failureKind") == "stale_claim")


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


def retry_task(project: str, task_id: str) -> bool:
    """Un-block a single ``blocked`` task: a locked ``blocked`` -> ``pending`` flip. The only
    other re-entry path is a pod-wide budget change (``unblock_pod``). Returns False if the
    task doesn't exist or isn't currently blocked."""
    found = False

    def _fn(doc: dict[str, Any]) -> dict[str, Any] | None:
        nonlocal found
        tasks_raw = doc.get("tasks")
        tasks = tasks_raw if isinstance(tasks_raw, list) else []
        for t in tasks:
            if t.get("id") == task_id:
                _normalize_task(t)
                if t.get("status") != "blocked":
                    return None
                t["status"] = "pending"
                t.pop("blockedReason", None)
                found = True
                return {"tasks": tasks}
        return None

    _store.read_modify_write(pod_task_list_path(project), _fn)
    return found


def unblock_pod(project: str) -> int:
    """Un-block every ``blocked`` task in *project*'s queue. Wired to ``docket profile
    <lead-id> --budget ...`` -- the other sanctioned re-entry path besides ``retry_task``.
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


def resolve_waiting_approval(token: str, decision: str) -> bool:
    """React to a just-applied approval decision by mutating the dispatch task it gated, if
    any -- never mutates the approval record itself, only reacts to a transition
    ``core/approval.py`` already made. See pod-dispatch.spec.md ("require_approval gate and
    waiting_approval") for the grant (-> ``pending`` + gate override) and deny (-> ``failed``,
    ``failureKind: "approval_denied"``) outcomes. Returns ``False`` as a harmless no-op for an
    unrelated/already-resolved token or a mismatched task; ``True`` when updated."""
    try:
        rec = _ap.approval_get(token)
    except _ap.ApprovalError:
        return False
    context = rec.get("context")
    task_id = str(context.get("taskId", "")) if isinstance(context, dict) else ""
    project = str(rec.get("project", ""))
    if not task_id or not project:
        return False

    updated = False

    def _fn(doc: dict[str, Any]) -> dict[str, Any] | None:
        nonlocal updated
        tasks_raw = doc.get("tasks")
        tasks = tasks_raw if isinstance(tasks_raw, list) else []
        for t in tasks:
            if t.get("id") != task_id:
                continue
            if t.get("status") != "waiting_approval" or t.get("approvalToken") != token:
                return None
            pending_index = t.get("pendingApprovalIndex")
            t.pop("approvalToken", None)
            t.pop("pendingApprovalIndex", None)
            if decision == "granted":
                t["status"] = "pending"
                t["gateOverridePipelineIndex"] = pending_index
            else:
                t["status"] = "failed"
                t["reason"] = "approval denied"
                t["failureKind"] = "approval_denied"
                t["completedAt"] = _now()
                t["claimId"] = None
            updated = True
            return {"tasks": tasks}
        return None

    _store.read_modify_write(pod_task_list_path(project), _fn)
    if updated:
        _trace.trace_event(
            project,
            f"agent:{project}:{task_id}",
            "lead",
            "approval_resumed" if decision == "granted" else "approval_task_denied",
            _json.dumps({"task": task_id, "token": token}),
        )
    return updated


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
) -> list[TaskResult]:
    """Dispatch a pod's pending tasks through the pipeline (highest priority first), looping
    ``dispatch_task`` over locked claims until none remain or *max_tasks* is hit --
    see ``dispatch_task`` and pod-dispatch.spec.md for the full claiming/crash-recovery/retry
    contract. A stale ``running`` claim is swept first; pass *resume* to also reclaim those
    and continue from the last persisted hop. Returns one TaskResult per task attempted.
    Raises DispatchError if the pod has no Lead."""
    pod_pipeline(project)  # validates pod/lead up front
    _sweep_stale_claims(project)

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
    data assembly for ``docket mcp serve``'s ``pods`` tool, mirroring ``cli/_pod.py``'s
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
