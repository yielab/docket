"""Pod pipeline dispatch — drives queued tasks through the lead → implementer → reviewer → tester pipeline.

One real agent turn per present role (via the ACL's ``agent_run``), with a trace event and budget
check per hop. Dispatch is always within a single pod — no code path sends one pod's work to
another pod's agents. Invoked only from an explicit trigger or the opt-in ``serve --dispatch`` loop.

R-1 (task state machine v2): a task is **claimed** (a locked read-modify-write flipping
``pending`` → ``running`` and persisting ``startedAt``/``claimId``/``claimedAt`` before the first
hop runs) rather than read unlocked and mutated in memory — this is what makes two concurrent
``dispatch_pod`` calls on the same pod unable to double-run the same task (they may each claim and
run *different* tasks concurrently; that is fine). Hops persist to the queue file as they complete
(not only at task end), so a crash mid-task loses at most the in-flight hop. A stale ``running``
claim is swept to ``failed`` (``failureKind: "stale_claim"``) and is resumable — ``dispatch_pod(...,
resume=True)`` re-claims it and continues from the last persisted hop instead of hop 0. A
``blocked`` (budget) task is never silently rewritten to ``pending``; it re-enters the queue only
via ``unblock_pod`` (pod-wide budget change) or ``retry_task`` (single task, explicit).

R-2 (retries + decoupled timeouts): a hop whose agent turn fails with a *retryable*
``TurnResult.failure_kind`` (``timeout``/``daemon_error`` — a daemon hiccup, not a real
answer) is retried in place, up to a per-role budget (``config.DISPATCH_RETRIES_PER_ROLE``) with
linear backoff, before the hop is finally marked failed. ``attempts`` is persisted per hop.
Retrying can make a single hop take meaningfully longer than before, so every retry (and every
completed hop) refreshes the task's ``claimedAt`` — otherwise a legitimately in-progress retry
loop could exceed ``CLAIM_STALE_TIMEOUT`` and a *different* concurrent dispatcher's stale-claim
sweep would wrongly steal it (see ``_touch_claim``). The agent-turn timeout and the verifyCmd
timeout are now independent (``turnTimeoutS``/``verifyTimeoutS``), resolved per call: an explicit
override (e.g. ``docket pod <p> dispatch --timeout``) wins, then the pod Lead's meta, then
``DEFAULT_TIMEOUT``.
R-5 (budget honesty): the per-hop budget gate now actually pauses the pod once its cap is
reached (``_pause_lead_for_budget`` writes the Lead's ``paused``/``pausedReason`` — previously
nothing ever set that flag, see ``core/models.py``'s ``AgentMeta.paused``), and
``_claim_next_task`` refuses every further claim for a paused pod outright (a ``paused_refused``
trace event, no claim write, no wasted turn) until ``docket profile <lead-id> --resume`` clears
it. Gating also tolerates a daemon that never records a ``usage.cost.total`` at all — see
``pod_gating_cost``'s token-based estimate fallback, used for gating/warning only and always
labelled, never presented as recorded spend.

G-1 (approval-gated dispatch): a sixth task status, ``waiting_approval``, sits between a
gated hop and the rest of the pipeline. Pre-hop (after the budget gate, before the hop's
message is composed), ``_hop_requires_approval`` checks whether this role's turn needs a
human decision — today, the pod Lead's ``requireApprovalRoles`` meta list, or a pipeline-step
source (see ``_pod_requires_approval``/``_pipeline_step_requires_approval``; the third,
policy-match source is G-2's ``enqueue_task`` gate below, not this per-hop check — see its own
paragraph for why). A fired gate creates a real ``core/approval.py`` record (previously
``approval_create`` had no production caller at all — this is that missing producer), persists
the task as ``waiting_approval`` with the token and the exact pipeline position it stopped at,
and stops the hop — never claimable again by a plain dispatch run (``_eligible_for_claim`` only
recognizes ``pending`` and a ``stale_claim``-tagged ``failed``). ``docket approve``/``docket
deny`` and the HTTP ``POST /approvals/<token>`` endpoint call ``resolve_waiting_approval`` right
after the underlying grant/deny (and the expiry sweep does the same on a fail-closed timeout): a
grant flips the task back to ``pending`` and hands the exact stopped-at position back to the
*next* claim as a single-use gate override (so a resumed run continues past that one hop without
re-prompting, while a later hop at the same role — e.g. a Reviewer rework cycle — still gates
normally); a deny fails the task immediately and terminally (``failureKind:
"approval_denied"``) — no agent turn is needed to kill a task that never ran its gated hop.

G-2 (policy engine on the live path): ``core/policy.py``'s ``pre_input``/``pre_output`` hooks
are now real producers, not just the CLI's own dry-run printer. ``pre_input`` is evaluated
**once, at enqueue** (``enqueue_task``, role ``"lead"`` — the pipeline's fixed entry point) —
deliberately *not* re-evaluated before every hop the way the pod-level ``requireApprovalRoles``
gate is, because the same task text would otherwise re-trip a ``"*"``-scoped policy at every
single hop, demanding a fresh human approval per role for what is really one piece of incoming
text. A ``block`` verdict rejects the task before it ever reaches the queue (``DispatchError``,
nothing persisted); a ``require_approval`` verdict persists the task straight into
``waiting_approval`` with a real ``approval_create`` record — the exact same resolution path
(grant → ``pending`` + a hop-0 gate override; deny → terminal ``failureKind:
"approval_denied"``) G-1 already built, just fed from a second source. ``pre_output`` is
evaluated on **every** hop's real output, inside ``_execute_unit`` right after the agent turn
returns and before that text is embedded in the carried-forward ``HandoffArtifact`` or the
persisted ``HopResult`` — ``redact`` scrubs the text in place, ``block`` fails the hop the same
way a failed agent turn does, ``warn`` only logs. Every non-``allow`` verdict on either hook
emits a ``guardrail_check`` trace event; a ``block`` verdict additionally emits
``guardrail_block`` with the tripped policy's id as its ``action`` field — the shape
``cli/_metrics.py``'s reader already keys its "Guardrail trips" tally on. In-turn
``pre_tool_call`` stays daemon-gated (ROADMAP §4.5: docket is not inside a turn to intercept a
tool call) and is never evaluated here.
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

import docket.config as _cfg
from docket.core import approval as _ap
from docket.core import archetypes as _archetypes
from docket.core import conversations as _conv
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
from docket.edges.adapters import openclaw as _oc
from docket.edges.adapters import system as _sys

# Only roles the pod actually has run — lean pod (lead + implementer) = 2 hops; full pod = 4.
PIPELINE_ORDER: tuple[str, ...] = ("lead", "implementer", "reviewer", "tester")

# Injectable runner for tests (matches the ACL ``agent_run`` signature). The 4th
# positional arg is always the *agent-turn* timeout (never the verify timeout).
# W-5/Phase 18 CL-1: spells the canonical ``core.runtime_driver.TurnResult`` name
# directly — ``edges.adapters.openclaw.AgentRunResult`` (the alias this used to
# read, kept only because this exact line bound it at import time) has been
# retired now that every call site across the test suite has been swept too.
Runner = Callable[[str, str, str, int, dict[str, str] | None], _rd.TurnResult]

DEFAULT_TIMEOUT = 300

# R-2: only these TurnResult.failure_kind values are worth retrying — a
# transient daemon/CLI hiccup. A non-zero exit or an unparseable/failing
# verdict is a real answer and must never be retried (retrying would risk
# masking a genuine failure as a transient one, and burns budget for nothing).
_RETRYABLE_FAILURE_KINDS: frozenset[str] = frozenset({"timeout", "daemon_error"})

# Priority sort key shared by task selection everywhere it matters.
_PRIORITY_RANK: dict[str, int] = {"high": 0, "normal": 1, "low": 2}

# W-8: the Reviewer/Tester verdict regexes and their marker parsers used to be
# hardcoded here (`_REVIEWER_VERDICT_RE`/`_TESTER_VERDICT_RE`,
# `_parse_reviewer_verdict`/`_parse_tester_verdict`) — dispatch's own private,
# independent copy of what `core/pipeline.py`'s `default_pipeline()` already
# declares as real `VerdictGate`s. Gate execution now reads a step's *resolved*
# gate generically (see `_execute_unit`'s `isinstance(gate, _pipeline.VerdictGate)`
# branch and `core.orchestrator.parse_verdict`) instead of one hardcoded regex
# per named role, so that second, drift-prone copy is gone — the single source
# of truth for these two patterns is now `core/pipeline.py`'s
# `default_pipeline()` (see `tests/python/test_w1_pipeline_spec.py`).


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
    # R-2: total agent-turn attempts made for this hop (1 = succeeded or failed on
    # the first try, no retry). Only retryable failures (see
    # ``_RETRYABLE_FAILURE_KINDS``) ever push this above 1.
    attempts: int = 1
    # W-2: the pipeline-spec step id this hop ran for. Defaults to "" when
    # constructed without one; ``_hop_record``/``_hop_from_record`` backfill it
    # to ``role`` on both write and read, so a legacy queue record with no
    # persisted ``stepId`` (or a hand-built HopResult in an existing test)
    # replays exactly as before — the built-in default pipeline's step ids
    # equal their role names, so this is never a behavior change for the four
    # built-in roles, only a real distinction for a custom pipeline whose
    # step id differs from its target role (see ``_replay_pipeline_position``).
    step_id: str = ""
    # W-5: this hop's structured handoff artifact. ``None`` at construction
    # time backfills in ``__post_init__`` to
    # ``HandoffArtifact.from_legacy_output(output)`` — every ``HopResult``
    # therefore always carries a real artifact once constructed, whether built
    # explicitly with one (a live hop — see ``_execute_unit``) or reconstructed
    # from a pre-W-5 persisted record with no ``artifact`` key at all
    # (``_hop_from_record``'s backward-compatibility path), or simply
    # hand-built by an existing test that only ever passed ``output=``.
    artifact: _handoff.HandoffArtifact | None = None
    # CL-1 (Phase 18 dead-code register, W-5 owns it): a mechanical gate whose
    # command was unset — a real, intentional "no check configured" state, not
    # a failure. ``core/`` never prints (the layering rule this replaces a
    # violation of); this flag is this run's own in-memory signal only (not
    # persisted — see ``_hop_record``) for ``cli/``'s dispatch renderer to
    # print the same notice this used to ``print()`` directly.
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
    status: str  # "done" | "failed" | "blocked" | "waiting_approval"
    reason: str = ""
    hops: list[HopResult] = field(default_factory=list)
    # G-1: only meaningful when status == "waiting_approval" — the token the
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
    """The pod's task queue lives in its Lead's workspace.

    One queue per pod (keyed by the Lead), so pods never share a task list — part
    of the no-cross-pod guarantee.
    """
    lead_id = _pod.member_id(project, "lead")
    return _cfg.workspace_dir(lead_id) / "TASK_LIST.json"


# Fields a v2 task record may lack when loaded from a pre-R-1 TASK_LIST.json.
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
    # G-1: set together when a require_approval gate fires (status ->
    # "waiting_approval"); cleared on resolution (grant or deny) — see
    # `_apply_result`/`resolve_waiting_approval`.
    "approvalToken": None,
    "pendingApprovalIndex": None,
    # G-1: single-use gate-override handoff from a grant to the *next* claim
    # of this task — captured then cleared from storage atomically inside
    # `_claim_next_task` so it can never leak into an unrelated later claim.
    "gateOverridePipelineIndex": None,
}


def _normalize_task(task: dict[str, Any]) -> dict[str, Any]:
    """Backfill v2 fields onto a task dict (mutates in place; returns it).

    Every read path funnels through this so a legacy queue file — written
    before claims/resume/uuid ids existed — loads and dispatches with no
    separate migration step (R-1 backward-compat requirement).
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
    """G-2: evaluate the ``pre_input`` policy hook once, at enqueue time.

    Emits ``guardrail_check`` for any non-``allow`` verdict, and — only for ``block`` — a
    self-contained ``session_start``/``guardrail_block``/``session_end`` triple: a task rejected
    here is never dispatched, so nothing else will ever close out this session, and an
    unterminated trace file is invisible to ``cli/_metrics.py``'s terminal-session reader. A
    ``require_approval`` verdict deliberately does *not* synthesize a session_end — the task is
    still going to run for real (once granted), and that real ``dispatch_task`` call supplies the
    session's genuine start/end. Never raises; the caller decides what a ``block``/
    ``require_approval`` result means for the task being built.
    """
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


def enqueue_task(project: str, description: str, priority: str = "normal") -> dict[str, Any]:
    """Append a pending task to the pod's queue and return it.

    Raises DispatchError if the project has no Lead workspace (no pod yet), or if a
    ``pre_input`` guardrail policy (G-2) matches this description with a ``block`` action
    (nothing is persisted in that case). The append itself is a locked read-modify-write
    (``store.read_modify_write``) so two concurrent ``delegate`` calls can never clobber each
    other's task.
    """
    path = pod_task_list_path(project)
    if not path.parent.is_dir():
        raise DispatchError(f"no pod for '{project}' (run: docket add {project})")

    task_id = f"task-{_uuid.uuid4()}"
    source = "operator"
    session_id = f"agent:{project}:{task_id}"

    hit = _enqueue_pre_input_gate(
        project, session_id, task_id, description, trusted=source == "operator"
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
    """Present pod roles in pipeline order, as ``(role, member_id)``.

    Only roles the pod actually has appear. A pod must have a Lead; raises
    DispatchError otherwise. Duplicate implementers collapse to the first one for
    v1 (a single doer per role per task).
    """
    all_ids = [a.id for a in _oc.list_agents()]
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
    """Every role this pod actually has, first member per role (``role -> member_id``).

    Unlike :func:`pod_pipeline` (which only ever considers the four legacy
    roles, in ``PIPELINE_ORDER``, for the default pipeline's own use), this
    considers every role name the pod's members actually carry — needed so a
    custom :class:`~docket.core.pipeline.PipelineSpec` (``docket pipeline
    run``/``plan``, W-2) can target a non-legacy role (e.g. a starter-library
    ``researcher``) and have it resolve against the pod's real roster. Same
    "first member of a role wins" convention as ``pod_pipeline``.
    """
    all_ids = [a.id for a in _oc.list_agents()]
    by_role: dict[str, str] = {}
    for mid, role, _idx in _pod.members_of(all_ids, project):
        by_role.setdefault(role, mid)
    return by_role


def effective_pipeline(project: str, spec: _pipeline.PipelineSpec | None) -> _pipeline.PipelineSpec:
    """The PipelineSpec this dispatch actually runs (W-2).

    A caller-supplied *spec* (a real pipeline file, e.g. ``docket pipeline
    run --file``) is used exactly as given — never patched. ``None`` (the
    zero-migration case) resolves ``load_pipeline(None)``'s built-in default,
    patched so its Reviewer step's rework budget reflects *this pod's own*
    configured ``maxReworkCycles`` (:func:`pod_max_rework_cycles`).

    This patch exists only to keep that pre-existing, tested, per-pod
    override working now that gate execution reads a verdict gate's own
    ``rework.max_cycles`` instead of a separate ``max_rework`` value threaded
    through the hop loop — ``core/pipeline.py``'s ``default_pipeline()``
    necessarily hardcodes a fixed ``max_cycles`` in the data format itself
    (there is no such thing as a "pod" at that layer), so reconciling the two
    is dispatch's job, not the format's. ``maxReworkCycles`` stays a
    zero-migration compatibility shim; it is never applied to a real
    caller-supplied spec.

    Public (not ``_``-prefixed) because ``cli/_pipeline.py``'s ``docket
    pipeline plan`` needs this exact resolved spec too — it renders from the
    same code path the real executor runs, never a second interpretation.
    """
    if spec is not None:
        return spec
    builtin = _pipeline.load_pipeline(None).spec
    assert builtin is not None  # load_pipeline(None) always succeeds
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
    """Sum the daemon-recorded spend across all of the pod's members."""
    all_ids = [a.id for a in _oc.list_agents()]
    total = 0.0
    for mid, _role, _idx in _pod.members_of(all_ids, project):
        total += float(_utils.aggregate_cost(mid).cost_usd)
    return round(total, 6)


def pod_budget(project: str) -> float:
    """The pod's USD budget cap (Lead's ``budgetUsd``), 0.0 = unlimited."""
    lead_id = _pod.member_id(project, "lead")
    raw = _oc.meta_get(lead_id, "budgetUsd", "")
    try:
        return float(raw) if raw else 0.0
    except ValueError:
        return 0.0


def pod_max_rework_cycles(project: str) -> int:
    """Bounded rework budget for a REQUEST-CHANGES review (R-4).

    Configured per-pod via the Lead's ``maxReworkCycles`` meta field (same
    convention as ``pod_budget``'s ``budgetUsd`` read — no dedicated CLI setter
    exists yet; set it with the internal ``meta-set`` path if a pod needs a
    non-default value). Default is ``1``: exactly one rework cycle runs before
    a second REQUEST-CHANGES fails the task. ``0`` disables rework entirely —
    the Reviewer becomes a hard gate with no retry.
    """
    lead_id = _pod.member_id(project, "lead")
    raw = _oc.meta_get(lead_id, "maxReworkCycles", "")
    if not raw:
        return 1
    try:
        return max(0, int(raw))
    except ValueError:
        return 1


def _retries_for_role(role: str) -> int:
    """Max retry attempts (after the first try) for one role's hop (R-2 policy)."""
    return _cfg.DISPATCH_RETRIES_PER_ROLE.get(role, _cfg.DISPATCH_RETRIES_DEFAULT)


def _lead_meta_timeout(project: str, field_name: str) -> int | None:
    """Read a positive-int timeout field from the pod's Lead meta, if set validly."""
    lead_id = _pod.member_id(project, "lead")
    raw = _oc.meta_get(lead_id, field_name, "")
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
    config, else ``DEFAULT_TIMEOUT`` (the fallback of last resort — R-2)."""
    if explicit is not None:
        return explicit
    if pod_value is not None:
        return pod_value
    return DEFAULT_TIMEOUT


def pod_gating_cost(project: str) -> tuple[float, bool]:
    """The pod's spend for budget-**gating** purposes: recorded, or estimated.

    Prefers ``pod_recorded_cost`` (the daemon's own ``usage.cost.total``,
    summed across the pod's members). Daemon v2026.2.23 may never write that
    field at all (see ``core/runtime_driver.py``'s ``TurnResult.cost_usd``
    note) — when recorded spend reads exactly 0, a real cap could otherwise
    never trip, so this falls back to a per-member token x ``MODEL_PRICING``
    estimate (``core/utils.estimate_cost_usd``).

    Returns ``(amount, estimated)`` — ``estimated`` is True only when
    *amount* came from that fallback. This value is for gating/warning
    **only**; it must never be presented as, or mixed into, recorded spend
    (``docket cost`` stays exactly the daemon's own figure — see
    ``cli/_cost.py`` and the no-unfalsifiable-cost-claims discipline in
    CLAUDE.md / cost-tracking.spec.md).
    """
    recorded = pod_recorded_cost(project)
    if recorded > 0.0:
        return recorded, False

    all_ids = [a.id for a in _oc.list_agents()]
    total_est = 0.0
    any_estimate = False
    for mid, _role, _idx in _pod.members_of(all_ids, project):
        totals = _utils.aggregate_cost(mid)
        if totals.input_tokens == 0 and totals.output_tokens == 0:
            continue
        model = str(_oc.meta_get(mid, "model", "") or "")
        est = _utils.estimate_cost_usd(model, totals)
        if est is not None:
            total_est += est
            any_estimate = True
    return round(total_est, 6), any_estimate


def _pause_lead_for_budget(project: str) -> None:
    """R-5: mark the pod's Lead paused once its budget cap is reached.

    The Lead owns the pod's ``budgetUsd`` cap (``pod_budget`` reads only the
    Lead's field), so pausing the Lead is exactly what ``_claim_next_task``
    checks to refuse every further claim for this pod — one write here, not
    a per-hop recheck. Writing the same values again is harmless (idempotent)
    though it shouldn't normally recur: once paused, this pod's tasks stop
    being claimed at all (see ``_claim_next_task``), so ``dispatch_task``'s
    budget gate — the only caller of this function — won't run again for it
    until an operator clears the pause (``docket profile <lead-id>
    --resume``).
    """
    lead_id = _pod.member_id(project, "lead")
    _oc.meta_set(lead_id, "paused", True)
    _oc.meta_set(lead_id, "pausedReason", "budget")


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
    """Build the message handed to one role, threading prior hops' output.

    ROADMAP Phase 17 C-1: composed via ``core/context.py``'s token-budget
    compiler, which supersedes Phase 14 R-7's blind byte cap (R-7's
    ``_hop_carryover_budget``/``_truncate_carryover`` helpers and the
    ``HOP_CARRYOVER_BYTES`` constant were deleted when C-1 merged — the two
    mechanisms are never layered, and only one now exists). The task
    description is still never truncated — there is nothing sensible to shed
    from the actual task. Each prior hop's rendered ``HandoffArtifact`` is fit
    to a share of the role's own token budget
    (``core/archetypes.py``'s ``RoleArchetype.token_budget``) via
    ``core.context.compile_artifact``: less-valuable fields
    (``HandoffArtifact.DROP_ORDER`` — ``notes``, ``diff_ref``,
    ``files_changed``, ``verdict``) are shed first, one at a time, and only
    ``summary`` itself is truncated (with a visible marker) once nothing else
    is left to shed — never silently dropped. Returns the composed message
    plus a ``_HopComposition`` recording what was sent, for the
    ``context_composed`` trace event.

    *rework_hop* (R-4) is the Reviewer hop whose REQUEST-CHANGES verdict is
    driving this call — only meaningful for ``role == "implementer"``. Its
    artifact is rendered as its own prominently-labeled section sized off the
    role's *full* carryover budget rather than the generic recency-ranked
    share the loop below gives every other prior hop, and it is excluded from
    that loop so it is never rendered (and never budgeted) twice. This is
    deliberate, not just relying on it already being the most recent hop:
    recency-based ranking is an emergent property of *when* the rework
    happens to run, not a structural guarantee, and the one thing a rework
    implementer hop must not lose is exactly the review it exists to address.
    """
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
            "You are the Reviewer. Review the diff (read-only). Your reply's first "
            "non-blank line must be exactly APPROVE or REQUEST-CHANGES "
            "(case-insensitive), followed by your reasons."
        )
    elif role == "tester":
        instructions = (
            "You are the Tester. Validate behaviour only. Your reply's first "
            "non-blank line must be exactly PASS or FAIL (case-insensitive), "
            "followed by evidence."
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
        # W-5: rendered from the hop's *artifact*, not its raw output — when
        # the artifact carries nothing beyond `summary` (true for every
        # rework-driving hop today; a rework target is always a role with a
        # VerdictGate whose own `render()` may add a "Verdict: ..." line, see
        # below) this is byte-identical to the pre-W-5 raw-text behaviour.
        # W-8: attributed to whichever step actually drove the rework — for
        # the built-in pipeline this is always the reviewer, so the rendered
        # text is byte-identical to the pre-W-8 hardcoded "reviewer requested
        # changes" wording; a custom pipeline's rework source (any role with
        # a verdict gate's `rework` edge) is named correctly too.
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
    # Iterate in the original chronological order (oldest first) — unchanged
    # from pre-C-1 behaviour, so message *layout* never changes, only
    # content. Only the per-hop budget is recency-aware: rank counts back
    # from the most recent hop (rank 0), so `context.hop_share` gives it the
    # biggest share.
    for i, h in enumerate(prior):
        if not h.output or h is rework_hop:
            continue
        rank = last_index - i
        hop_budget = _ctx.hop_share(rank, carryover_budget)
        # W-5: the *artifact* is what gets carried forward and budgeted — not
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
    """Build the subprocess env override for a hop, if any (FD-0).

    Only an **implementer** hop that has an allocated pod port range gets an
    override — the pod's port range + scratch dir become real env vars in that
    subprocess, not just prose in TOOLS.md. Every other hop (lead/reviewer/tester,
    or an implementer with no allocation) returns ``None`` — no override, today's
    inherit-the-parent-env behaviour.
    """
    if role != "implementer":
        return None
    port_start = _oc.meta_get(member_id, "portRangeStart", "")
    if not port_start:
        return None
    port_count = _oc.meta_get(member_id, "portRangeCount", "")
    scratch_dir = _oc.meta_get(member_id, "scratchDir", "")
    return {
        "DOCKET_PORT_BASE": port_start,
        "DOCKET_PORT_COUNT": port_count,
        "DOCKET_SCRATCH_DIR": scratch_dir,
    }


def _implementer_diff_probe(member_id: str, role: str) -> tuple[list[str], str | None]:
    """Real `files_changed`/`diff_ref` for an Implementer hop's artifact (W-5b).

    Closes the seam ROADMAP Phase 16 card W-5 declared: `HandoffArtifact`
    shipped both fields real but unpopulated because the git shell-out
    surface belonged to a different in-flight card that wave (see
    `core/handoff.py`'s module docstring).

    Only meaningful for ``role == "implementer"`` — every other role returns
    ``([], None)``, the same empty default `HandoffArtifact` already ships.
    Resolves the member's working tree exactly the way the MechanicalGate
    verify branch below does (worktree -> shared codebase -> the member's own
    docket workspace dir, via ``core.pod.resolve_member_cwd``) so the two can
    never disagree about which tree is being inspected. Every shell-out goes
    through ``edges/adapters/system.py``; this function itself never calls
    git directly. Degrades to ``([], None)`` — never raises — when git is
    missing, the resolved directory is not a git repository (a ``workdir``
    pod with no codebase resolves to its plain workspace dir, which is not a
    repo), or the underlying git calls otherwise fail.
    """
    if role != "implementer":
        return [], None
    worktree_dir = str(_oc.meta_get(member_id, "worktreeDir", "") or "")
    member_codebase = str(_oc.meta_get(member_id, "codebase", "") or "")
    cwd = _pod.resolve_member_cwd(member_id, worktree_dir, member_codebase)
    if not _sys.git_available() or not _sys.git_is_repo(cwd):
        return [], None
    files_changed = _sys.git_changed_files(cwd)
    diff_ref = _sys.git_current_branch(cwd) or None
    return files_changed, diff_ref


def _hop_record(h: HopResult) -> dict[str, Any]:
    """The persisted-queue-file shape of one hop (round-trips via ``_hop_from_record``).

    W-5: ``artifact`` is the hop's ``HandoffArtifact`` dumped to a plain dict
    so ``--resume`` recovers the exact same structured record, not just its
    raw text — persisted alongside the legacy ``output`` field (never
    replacing it) so a pre-W-5 reader of this same JSON still finds what it
    always found. ``verification_skipped`` is deliberately **not** persisted
    — it is this run's own in-memory signal for ``cli/``'s renderer, not part
    of the durable record (see ``HopResult``'s own docstring).
    """
    return {
        "role": h.role,
        "member": h.member_id,
        "ok": h.ok,
        "output": h.output,
        "costUsd": round(h.cost_usd, 6),
        "error": h.error,
        "attempts": h.attempts,
        # W-2: falls back to `role` when unset — see HopResult.step_id.
        "stepId": h.step_id or h.role,
        "artifact": h.artifact.model_dump() if h.artifact is not None else None,
    }


def _hop_from_record(rec: dict[str, Any]) -> HopResult:
    """Reconstruct a HopResult from a persisted hop record (for resume).

    W-5 backward compatibility: a record persisted before this card has no
    ``artifact`` key at all — that (and any record whose ``artifact`` value
    fails to validate, e.g. hand-edited JSON) degrades via
    ``HandoffArtifact.from_legacy_output``, treating the persisted raw
    ``output`` text as the artifact's ``summary``, exactly as the card
    requires. A record written by this version of dispatch round-trips its
    artifact exactly (every field, not just ``summary``).
    """
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
    """Where a (possibly resumed) dispatch run should continue (R-4, generalized W-2).

    ``pipeline_index`` is the index into the resolved run's ``runtime_steps``
    (top-level ``PlannedUnit``/``PlannedGroup`` nodes) of the next position to
    run. ``rework_counts`` is how many rework cycles have already been
    consumed, keyed by the *gated* step's id (a pipeline may declare more than
    one independent rework-capable verdict gate; the built-in pipeline only
    ever has one — the Reviewer's — so this dict always has at most one entry
    in practice today). ``rework_hop`` — set only when ``pipeline_index``
    points back at a rework target — is the ``HopResult`` whose text drives
    that rework hop's message.
    """

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
    """Replay a hop history to find where dispatch should continue.

    Before R-4, resuming a crashed task only needed to know *which roles* had
    already completed (a role either ran once or hadn't run at all, since the
    pipeline was a straight line) — a simple ``{h.role for h in prior}`` set
    was enough. Rework breaks that: a role can legitimately appear more than
    once in ``hops[]`` (the Implementer runs again after a REQUEST-CHANGES,
    the Reviewer re-reviews it), so "has this role's hop happened" is no
    longer the right question — "where in the pipeline are we, and how many
    rework cycles have we already spent" is. This replays the same decision
    the live loop makes for a fresh verdict-gated hop (a matching ``rework``
    marker with budget left ⇒ jump back to the declared target; anything else
    ⇒ advance) against the *persisted* hop sequence, so a crash recorded
    mid-rework resumes into the correct next hop — carrying the same review
    text a live run would have carried — rather than skipping straight past
    the gated step's slot. (W-2: generalized from a hardcoded
    reviewer/implementer role check to an arbitrary verdict gate's own
    ``rework`` edge, matched by step id — the built-in pipeline's step ids
    equal their role names, so this is not a behavior change for it.)

    A hop whose ``step_id`` names something *inside* a parallel group (a
    child, never a valid rework target per the pipeline format's own
    validator) does not by itself advance the top-level position — see the
    trailing loop below, which instead checks whether a whole group's
    children are all accounted for. **Known, deliberate limitation:** a crash
    partway through a group's fan-out is not resumed child-by-child — the
    *entire* group re-runs from scratch (every already-completed child
    included) once resume determines the group itself isn't fully done.

    This is only ever asked to replay a *non-terminal* history: a hop whose
    outcome would end the task (a plain failure, an exhausted rework budget,
    unparseable output, a passed pipeline) is decided and persisted
    synchronously within the same ``dispatch_task`` call that ran it — the
    task reaches a terminal ``status`` before that call returns, and a
    terminal task is never claimed for resume in the first place
    (``_eligible_for_claim`` only resumes a ``failed`` task tagged
    ``failureKind: "stale_claim"``, never a plain ``failed`` outcome). So
    every hop this function ever actually sees left the pipeline *running*,
    which is exactly the set of decisions it knows how to replay.
    """
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
    """G-1's pod-level require_approval source: the Lead's ``requireApprovalRoles`` meta.

    A comma-separated, case-insensitive role list (e.g. ``"implementer,reviewer"``)
    read the same way ``pod_max_rework_cycles`` reads ``maxReworkCycles`` — only the
    Lead's value is consulted, and there is no dedicated CLI setter yet (set it via
    the internal ``meta-set <lead-id> requireApprovalRoles "<roles>"`` path). Blank
    or missing → no pod-level gate for any role.
    """
    lead_id = _pod.member_id(project, "lead")
    raw = _oc.meta_get(lead_id, "requireApprovalRoles", "")
    if not raw:
        return False
    roles = {r.strip().lower() for r in raw.split(",") if r.strip()}
    return role.lower() in roles


def _policy_requires_approval(project: str, role: str, task: dict[str, Any]) -> bool:
    """Deliberately stays ``False`` — G-2 gates policy-driven approval at enqueue, not per hop.

    This was originally documented as "the one place G-2 needs to change," under the
    assumption that a policy-driven require_approval source would be checked pre-hop, the same
    way ``_pod_requires_approval`` is. G-2 chose not to wire it that way: the only thing this
    function has to evaluate against is the task's own (fixed, already-enqueued) description, so
    checking it again before *every* hop would re-trip the same ``"*"``-scoped ``pre_input``
    policy match at every role in the pipeline — one incoming piece of text demanding a fresh
    human approval for the Lead, then again for the Implementer, then again for the Reviewer,
    etc. Real per-hop policy gating belongs on what the hop *produces* (``pre_output``, scanned
    in ``_execute_unit`` for every hop unconditionally) or on what a future in-turn tool call
    attempts (``pre_tool_call`` — daemon-gated, not this module's to enforce). ``pre_input``'s
    one meaningful evaluation point is enqueue time, before the task ever becomes a queued
    ``dict`` — see ``enqueue_task``'s ``_enqueue_pre_input_gate``, which creates the exact same
    ``waiting_approval`` state a pre-hop gate does, just from a single source instead of N.
    Kept as an explicit, always-``False`` function (rather than deleted) so
    ``_hop_requires_approval``'s three-source shape stays intact for a genuinely new *per-hop*
    policy source, should one ever be designed.
    """
    return False


def _pipeline_step_requires_approval(gate: _pipeline.Gate | None) -> bool:
    """The pipeline-defined ``approval`` step source (ROADMAP Phase 16 W-1/W-2).

    Previously a permanently-``False`` stub (no task record had an explicit
    per-step gate to consult) — **W-2 fills this seam**: *gate* is the
    current pipeline position's own resolved gate (its declared ``gate``, or
    its archetype's ``gateContract`` fallback — see
    ``core.orchestrator.resolve_gate``). A step whose resolved gate is an
    ``approval`` gate now genuinely requires a human decision before its hop
    runs, the same as the pod-level ``requireApprovalRoles`` source.
    """
    return isinstance(gate, _pipeline.ApprovalGate)


def _hop_requires_approval(
    project: str,
    role: str,
    task: dict[str, Any],
    pipeline_index: int,
    gate: _pipeline.Gate | None,
) -> bool:
    """Whether the require_approval gate fires before this hop (G-1).

    Three independent sources may demand a human decision; **any** one firing is
    enough to gate (a veto, not unanimous consent):
      1. the pod-level ``requireApprovalRoles`` Lead-meta list (G-1, wired today)
      2. a per-hop policy match (G-2 — deliberately stays ``False``; G-2's
         ``pre_input`` policy source gates once, at enqueue, instead — see
         ``_policy_requires_approval``'s docstring for why)
      3. a pipeline ``approval`` step (W-1/W-2 — wired: see
         ``_pipeline_step_requires_approval``)
    """
    return (
        _pod_requires_approval(project, role)
        or _policy_requires_approval(project, role, task)
        or _pipeline_step_requires_approval(gate)
    )


def _approval_action_text(role: str, task: dict[str, Any]) -> str:
    """Human-readable description recorded on the approval record (G-1).

    Redacted by ``core/approval.py``'s own ``_redact`` before it's persisted —
    this just composes the text, it doesn't need to scrub secrets itself.
    """
    desc = str(task.get("description", "")).strip()
    task_id = str(task.get("id", "task"))
    return f"pod dispatch — {role} hop for task {task_id}: {desc}"[:1000]


def _trace_locked(*args: Any, **kwargs: Any) -> _trace.TraceStatus:
    """``trace.trace_event``, serialized against ``orchestrator.trace_write_lock``.

    ``core/trace.py``'s append is not itself filelocked (D-12's documented
    exemption for an append-only log) — safe across *different* session
    files (R-1's concurrent-dispatch guarantee already relies on that), but a
    parallel group's children share one task's session id/tracefile, so
    their trace writes need to be serialized against each other specifically
    (W-2). Cheap when uncontended (the ordinary, non-parallel case), so used
    unconditionally rather than special-cased per call site.
    """
    with _orch.trace_write_lock:
        return _trace.trace_event(*args, **kwargs)


def _verdict_event_names(role: str) -> tuple[str, str, str]:
    """(rework_event, rejected_event, unparseable_event) trace event type names
    for a verdict gate's three possible non-pass outcomes (W-8).

    Preserves the exact legacy event names the two built-in verdict roles
    have always emitted (``reviewer``/``tester`` — pinned by
    ``tests/python/test_r4_reviewer_gate.py``/``test_cd2_verify.py``) so gate
    *decision logic* can go fully generic (driven by the gate's own type and
    config, not a role-name branch) without changing what an operator sees in
    ``docket trace``. Any other role/archetype gets the new, generic W-8
    event names (registered in ``core/trace.py``'s ``EVENT_TYPES``).
    """
    if role == "reviewer":
        return "rework_started", "review_rejected", "reviewer_verdict_unparseable"
    if role == "tester":
        return "verdict_rework_started", "tester_verdict_failed", "tester_verdict_failed"
    return "verdict_rework_started", "verdict_rejected", "verdict_unparseable"


@dataclass
class _UnitOutcome:
    """What happened running one ``PlannedUnit``'s hop (W-2/W-8).

    ``kind`` is one of ``"advance" | "rework" | "blocked" | "waiting_approval"
    | "failed"``. ``hops`` holds the hop this call produced (empty for
    ``blocked``/``waiting_approval`` — the gate stopped the pipeline before
    any agent turn ran).
    """

    kind: str
    hops: list[HopResult] = field(default_factory=list)
    reason: str = ""
    rework_target_index: int | None = None
    approval_token: str = ""
    pending_approval_index: int | None = None


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
    """Drive one task through the pod pipeline, hop by hop (ROADMAP W-2/W-8).

    Budget is checked before EACH hop (every hop is a real costed turn). A failed
    hop stops the pipeline (later steps only matter if earlier ones succeed). All
    dispatch targets belong to this project's pod — asserted per hop. The one
    exception to "the pipeline only moves forward" is a bounded rework loop: a
    verdict-gated hop's rework-triggering marker re-runs the gate's declared
    ``rework.to`` target (carrying the gating hop's text) and then the gate
    again, up to that gate's own configured cycle budget before it becomes a
    terminal failure.

    *spec* (W-2) is the :class:`~docket.core.pipeline.PipelineSpec` to run;
    ``None`` (the default) resolves this pod's zero-migration pipeline (see
    ``effective_pipeline``) — behaviorally identical to the pre-W-2 hardcoded
    ``PIPELINE_ORDER`` walk for every existing caller that never passes one.
    Gate execution (W-8) reads each step's *resolved* gate — its own declared
    ``gate``, or (only when a step omits one) its archetype's ``gateContract``
    — via ``core.orchestrator.resolve_gate``, rather than branching on a
    hardcoded role name; a ``parallel`` step's children run concurrently via
    ``core.orchestrator.run_group`` and are joined before the pipeline
    advances past that position.

    *resume_from* seeds hops that already completed before a crash (role +
    output preserved) so the steps still to come see the same context an
    uninterrupted run would have produced; those steps are skipped rather than
    re-invoked (a step can legitimately have completed more than once, if the
    crash happened mid-rework — see ``_replay_pipeline_position``). *on_hop* —
    if given — fires with each new HopResult right after it completes (from
    whichever thread produced it, for a parallel group's children), so the
    caller can persist per-hop progress incrementally instead of only when the
    whole task finishes (R-1 crash-safety); this includes every rework hop, so
    the persisted ``hops[]`` history stays honest about what actually ran.

    R-2: *turn_timeout*/*verify_timeout* are per-call overrides (e.g. from
    ``docket pod <p> dispatch --timeout``); ``None`` (the default) falls back to
    the pod Lead's meta (``turnTimeoutS``/``verifyTimeoutS``), then
    ``DEFAULT_TIMEOUT`` (see ``_resolve_timeout``) — unless a step declares its
    own ``timeout``/``retries`` override, which always wins for that step. A
    hop whose agent turn fails with a retryable ``failure_kind`` is retried in
    place (linear backoff via *sleep*, real ``time.sleep`` unless a test
    injects a fake) up to the role's retry budget; *on_retry* — if given —
    fires before each retry sleep so the caller can refresh the task's claim
    timestamp (see ``_touch_claim``) before it goes stale.
    """
    run = runner or _oc.default_driver().run_turn
    # W-2: pid tracking (for `docket runs cancel`) only makes sense for a real
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

    effective_spec = effective_pipeline(project, spec)
    registry = _archetypes.load_registry()
    roster = pod_full_roster(project)
    plan = _orch.resolve_plan(effective_spec, roster, registry=registry)
    runtime_steps = plan.runnable_nodes()
    id_to_index = {node.step_id: i for i, node in enumerate(runtime_steps)}

    prior: list[HopResult] = list(resume_from) if resume_from else []
    # A step can now legitimately run more than once (a rework cycle re-runs
    # its gate's declared target, then re-runs the gating step), so "where do
    # we continue" is a pipeline position + per-gate rework counts, not a set
    # of already-seen role names — see `_replay_pipeline_position`'s
    # docstring for why this matters for a task resumed mid-rework.
    resume_pos = _replay_pipeline_position(runtime_steps, prior)
    pipeline_index = resume_pos.pipeline_index
    rework_counts: dict[str, int] = dict(resume_pos.rework_counts)
    pending_rework_by_index: dict[int, HopResult] = {}
    if resume_pos.rework_hop is not None:
        pending_rework_by_index[pipeline_index] = resume_pos.rework_hop

    # G-1: a granted approval hands the exact pipeline position it stopped at
    # back to this one claim as a single-use override (see
    # `_claim_next_task`'s claim-time handoff) — consumed the first time this
    # run reaches that position, so a later hop at the same position (a
    # rework cycle revisiting it) still gates normally.
    override_index = task.get("gateOverridePipelineIndex")
    if not isinstance(override_index, int):
        override_index = None

    _trace.trace_event(
        project,
        session_id,
        "lead",
        "session_start",
        _json.dumps({"source": "dispatch", "task": task_id, "resumed": bool(prior)}),
    )

    result = TaskResult(task_id=task_id, status="done", hops=list(prior))

    def _execute_unit(
        node: _orch.PlannedUnit,
        *,
        prior_snapshot: list[HopResult],
        rework_hop: HopResult | None,
        check_approval: bool,
        index_for_context: int,
    ) -> _UnitOutcome:
        """Run one PlannedUnit's hop end to end: budget/approval gates, the
        agent turn (with retries), and its post-hop gate. Shared by both a
        top-level step and a parallel group's children — *check_approval*
        is False for a child (an `approval` gate inside a fan-out is treated
        as a configuration error, not a mid-group human-approval wait; see
        the module-level parallel-group note in `core.orchestrator`).
        """
        role = node.role or node.agent or node.step_id
        member_id = node.member_id
        assert member_id is not None  # runnable_nodes() already filtered out skipped units

        if _pod.pod_of(member_id) != project:
            raise DispatchError(
                f"refusing cross-pod dispatch: '{member_id}' is not in pod '{project}'"
            )

        # Budget gate BEFORE the hop. Prefer the daemon's recorded pod spend;
        # R-5: fall back to a token-based estimate when the daemon has
        # recorded none at all (see pod_gating_cost) so a real cap can still
        # trip, and mark the Lead paused so future dispatch attempts are
        # refused at claim time instead of re-running this same check.
        if cap > 0.0:
            spent, estimated = pod_gating_cost(project)
            if spent >= cap:
                spent_label = (
                    f"~${spent:.2f} (estimated — daemon recorded no cost)"
                    if estimated
                    else f"${spent:.2f}"
                )
                _trace_locked(
                    project,
                    session_id,
                    role,
                    "budget_exceeded",
                    _json.dumps(
                        {
                            "spent": round(spent, 6),
                            "cap": round(cap, 6),
                            "role": role,
                            "estimated": estimated,
                        }
                    ),
                )
                return _UnitOutcome(
                    kind="blocked",
                    reason=f"pod budget reached ({spent_label} ≥ ${cap:.2f}) before {role}",
                )

        # G-1/W-2: require_approval gate — pre-hop, after budget (affordability)
        # and before the hop actually runs (permission).
        nonlocal override_index
        if check_approval:
            if index_for_context == override_index:
                override_index = None
            elif _hop_requires_approval(project, role, task, index_for_context, node.gate):
                action = _approval_action_text(role, task)
                token = _ap.approval_create(
                    project,
                    role,
                    action,
                    context={"taskId": task_id, "pipelineIndex": index_for_context},
                )
                _trace_locked(
                    project,
                    session_id,
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

        message, composition = _hop_message(task, role, prior_snapshot, rework_hop)
        _trace_locked(
            project,
            session_id,
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
            project,
            session_id,
            role,
            "tool_call",
            _json.dumps({"hop": role, "agent": member_id}),
        )
        env = _hop_env(member_id, role)

        # R-2: retry only a retryable failure (a transient daemon/CLI hiccup) —
        # a non-zero exit or a bad verdict is a real answer and stops here, same
        # as before this card. `attempt` ends as the total number of tries made.
        # A step's own `retries`/`timeout` override always wins; otherwise the
        # pod's role-based retry budget and the resolved agent-turn timeout.
        retry_budget = node.retries if node.retries is not None else _retries_for_role(role)
        hop_timeout = node.timeout if node.timeout is not None else resolved_turn_timeout

        # W-2: record the production driver's spawned pid as in-flight for
        # `docket runs cancel` — only while the subprocess is actually
        # running; removed again the moment this attempt returns, so a long
        # multi-hop task never accumulates stale pids from finished hops.
        run_id_for_pids = _runs.current_run_id() if track_pid else None
        spawned_pid: list[int] = []

        def _on_spawn(pid: int) -> None:
            spawned_pid.append(pid)
            if run_id_for_pids is not None:
                _runs.add_hop_pid(run_id_for_pids, pid)

        attempt = 1
        while True:
            spawned_pid.clear()
            if track_pid:
                # `run` is typed as the plain 5-arg `Runner` Callable (every
                # test double's exact shape); calling the concrete production
                # driver directly here (rather than through `run`) is what
                # lets it take the extra `on_spawn` kwarg type-safely.
                run_res = _oc.default_driver().run_turn(
                    member_id, session_id, message, hop_timeout, env, on_spawn=_on_spawn
                )
            else:
                run_res = run(member_id, session_id, message, hop_timeout, env)
            if run_id_for_pids is not None and spawned_pid:
                _runs.remove_hop_pid(run_id_for_pids, spawned_pid[-1])
            if run_res.ok or run_res.failure_kind not in _RETRYABLE_FAILURE_KINDS:
                break
            if attempt > retry_budget:
                break
            _trace_locked(
                project,
                session_id,
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
            if on_retry is not None:
                on_retry()
            do_sleep(_cfg.DISPATCH_RETRY_BACKOFF_S * attempt)
            attempt += 1

        # G-2: pre_output guardrail scan — every hop's real output, scanned once,
        # before it is embedded in the carried-forward artifact or persisted hop
        # record. Only `redact`/`block` change what gets carried forward
        # (`warn`/`allow` pass the text through unchanged); `require_approval` is
        # not a pre_output outcome (ROADMAP §4.5/Phase 15 G-2) — a hop has
        # already run by the time its output exists, so there is no "before the
        # hop" moment left to gate the way the pre-hop require_approval sources
        # above do; a policy author who wants a human in the loop before this
        # role runs uses `_pod_requires_approval`/enqueue's pre_input gate
        # instead. pre_tool_call (in-turn) stays daemon-gated, never evaluated
        # here.
        hop_output = run_res.output
        hop_ok = run_res.ok
        hop_error = run_res.error
        if hop_output:
            hit = _policy.policy_eval_detail(role, "pre_output", hop_output)
            # G-3: also classify the hop's real output against the built-in
            # high-risk action classes (core/security.py's HIGH_RISK_PATTERNS),
            # independently of the JSON policy engine above. The shipped
            # high-risk-*.json templates are hooked on pre_tool_call, which
            # docket never evaluates (D-15 — it is not inside a running turn to
            # intercept a tool call), so without this, a hop that reports
            # having run a money-movement or secret-access command trips
            # nothing at all on this path. A match never downgrades an
            # already-stronger policy_eval_detail verdict — redact/block/
            # require_approval all outrank a bare "allow" — it only raises a
            # plain "allow" to "warn". It cannot go further than "warn": there
            # is no live approver to "ask" post-hoc (the hop already ran, the
            # same reasoning behind pre_output's require_approval-behaves-
            # like-warn rule), and HIGH_RISK_PATTERNS is a built-in Python
            # list, not an installed, operator-authored JSON policy (FD-3 —
            # not yet user-configurable) — so this only ever adds visibility,
            # it never redacts or blocks on the operator's behalf the way a
            # real installed policy can.
            risk_cls = _sec.match_high_risk(hop_output)
            if risk_cls is not None and hit.action == "allow":
                hit = _policy.PolicyHit(
                    action="warn",
                    policy_id=f"high-risk:{risk_cls.name}",
                    message=risk_cls.description,
                )
            if hit.action != "allow":
                _trace_locked(
                    project,
                    session_id,
                    role,
                    "guardrail_check",
                    _json.dumps(
                        {"hook": "pre_output", "policy": hit.policy_id, "action": hit.action}
                    ),
                )
            if hit.action == "redact":
                hop_output = _trace.redact(hop_output)
            elif hit.action == "block":
                _trace_locked(
                    project,
                    session_id,
                    role,
                    "guardrail_block",
                    _json.dumps(
                        {"hook": "pre_output", "policy": hit.policy_id, "action": hit.policy_id}
                    ),
                )
                if hop_ok:
                    hop_ok = False
                    hop_error = f"blocked by guardrail policy '{hit.policy_id}'"

        # W-5: the verdict is parsed up front (rather than inside the
        # VerdictGate branch below, as it was pre-W-5) so it can be embedded
        # in the hop's own artifact *before* `on_hop` persists it — one
        # source of truth, computed once. Guarded on `hop_ok`: a failed
        # subprocess call (or a pre_output block) never reaches gate
        # evaluation either (see the early return just below), so there is no
        # meaningful verdict to report for it.
        verdict: str | None = None
        if hop_ok and isinstance(node.gate, _pipeline.VerdictGate):
            verdict = _orch.parse_verdict(node.gate, hop_output)
        # W-5b: real files_changed/diff_ref for a successful Implementer hop —
        # closes the seam W-5 declared (see core/handoff.py's module
        # docstring). `_implementer_diff_probe` degrades to ([], None) for
        # every other role, a workdir pod, a non-repo workspace, or a host
        # with no git binary, so this never raises mid-dispatch.
        #
        # Gated on `hop_ok`, not `run_res.ok`: G-2's pre_output policy hook can
        # fail an otherwise-successful subprocess call, and a hop the guardrail
        # blocked must not hand a "here is what I changed" artifact downstream.
        files_changed: list[str] = []
        diff_ref: str | None = None
        if hop_ok:
            files_changed, diff_ref = _implementer_diff_probe(member_id, role)
        # `hop_output`, never `run_res.output`: pre_output's `redact` action
        # rewrites the hop's text, and the artifact is what the next hop reads.
        # Sourcing the raw subprocess output here would silently undo the
        # redaction the policy engine just applied.
        artifact = _handoff.HandoffArtifact(
            summary=hop_output,
            verdict=verdict,
            files_changed=files_changed,
            diff_ref=diff_ref,
        )

        hop = HopResult(
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
        # Persisted immediately (not deferred to a parallel group's join) so a
        # crash in a *sibling* child never loses a hop that already completed —
        # R-1's crash-safety guarantee, generalized to a concurrent fan-out.
        if on_hop is not None:
            on_hop(hop)

        _trace_locked(
            project,
            session_id,
            role,
            "tool_result" if hop_ok else "error",
            hop_output or hop_error or "",
            cost_usd=run_res.cost_usd or None,
        )
        if run_res.cost_usd:
            _trace_locked(
                project,
                session_id,
                role,
                "cost_charged",
                _json.dumps({"role": role}),
                cost_usd=run_res.cost_usd,
            )

        if not hop_ok:
            return _UnitOutcome(
                kind="failed",
                hops=[hop],
                reason=f"{role} hop failed: {hop_error or 'no result'}",
            )

        gate = node.gate
        if gate is None:
            return _UnitOutcome(kind="advance", hops=[hop])

        if isinstance(gate, _pipeline.MechanicalGate):
            verify_cmd = gate.command or str(_oc.meta_get(member_id, "verifyCmd", "") or "")
            if verify_cmd:
                # R-6/W-8: verify in the member's own worktree when it has one —
                # else the shared codebase root — else its workspace dir. Shared
                # with cli/_pod.py's _regenerate_member_tools via core/pod.py so
                # the two can't disagree about which tree is being checked — now
                # applied to any mechanically-gated step, not just "implementer".
                worktree_dir = str(_oc.meta_get(member_id, "worktreeDir", "") or "")
                member_codebase = str(_oc.meta_get(member_id, "codebase", "") or "")
                cwd = _pod.resolve_member_cwd(member_id, worktree_dir, member_codebase)
                # R-2: the verify command gets its own timeout, decoupled from the
                # agent-turn timeout above — a 20-minute test suite and a hung LLM
                # turn are no longer forced to share one budget.
                mech_timeout = gate.timeout or resolved_verify_timeout
                passed, raw_output = _sys.run_verify_cmd(verify_cmd, cwd, mech_timeout)
                redacted = _trace.redact(raw_output)
                if not passed:
                    _trace_locked(
                        project,
                        session_id,
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
                    project,
                    session_id,
                    role,
                    "tool_result",
                    _json.dumps({"verification": "passed", "cmd": verify_cmd}),
                )
            else:
                # Honesty rule: never silently skip — a missing verifyCmd is
                # visible via a trace event (parity with the "passed" case
                # above) and the hop's own `verification_skipped` flag, which
                # `cli/`'s dispatch renderer prints. CL-1 (Phase 18 dead-code
                # register): `core/` never prints directly — that was a
                # layering violation this replaces.
                _trace_locked(
                    project,
                    session_id,
                    role,
                    "tool_result",
                    _json.dumps({"verification": "skipped", "member": member_id}),
                )
                hop.verification_skipped = True
            return _UnitOutcome(kind="advance", hops=[hop])

        if isinstance(gate, _pipeline.VerdictGate):
            # W-5: reuse the verdict already parsed above (and carried on the
            # hop's own artifact) rather than parsing `run_res.output` a
            # second time — single source of truth.
            verdict = artifact.verdict
            pass_set = _orch.normalize_values(gate.pass_values, gate.case_sensitive)
            if verdict is not None and verdict in pass_set:
                return _UnitOutcome(kind="advance", hops=[hop])

            rework = gate.rework
            if rework is not None and verdict is not None:
                when_set = _orch.normalize_values(rework.when, gate.case_sensitive)
                if verdict in when_set:
                    cycles_so_far = rework_counts.get(node.step_id, 0)
                    target_index = id_to_index.get(rework.to)
                    if cycles_so_far < rework.max_cycles and target_index is not None:
                        rework_counts[node.step_id] = cycles_so_far + 1
                        rework_event, _unused1, _unused2 = _verdict_event_names(role)
                        redacted = _trace.redact(hop_output)
                        _trace_locked(
                            project,
                            session_id,
                            role,
                            rework_event,
                            _json.dumps({"cycle": rework_counts[node.step_id], "output": redacted}),
                        )
                        return _UnitOutcome(
                            kind="rework", hops=[hop], rework_target_index=target_index
                        )
                    # Rework budget exhausted (or, defensively, no valid target) —
                    # this verdict is now terminal.
                    _unused3, rejected_event, _unused4 = _verdict_event_names(role)
                    redacted = _trace.redact(hop_output)
                    _trace_locked(
                        project,
                        session_id,
                        role,
                        rejected_event,
                        _json.dumps({"cycles": cycles_so_far, "output": redacted}),
                    )
                    return _UnitOutcome(
                        kind="failed",
                        hops=[hop],
                        reason=(
                            f"{role} rejected after {cycles_so_far} rework "
                            f"cycle(s): {verdict.upper()}"
                        ),
                    )

            # Anything else is either truly unparseable (no match at all) or a
            # real, parsed marker that's simply neither a pass nor a
            # rework-trigger — distinct outcomes, mirroring the pre-W-8
            # Tester gate's FAIL-vs-unparseable distinction (which, for the
            # tester role specifically, share one event name — see
            # `_verdict_event_names`).
            _unused5, rejected_event2, unparseable_event = _verdict_event_names(role)
            redacted = _trace.redact(hop_output)
            if verdict is None:
                _trace_locked(
                    project,
                    session_id,
                    role,
                    unparseable_event,
                    _json.dumps({"verdict": "unparseable", "output": redacted}),
                )
                return _UnitOutcome(
                    kind="failed",
                    hops=[hop],
                    reason=f"{role} output unparseable (expected a recognized verdict marker "
                    "on the first line)",
                )
            _trace_locked(
                project,
                session_id,
                role,
                rejected_event2,
                _json.dumps({"verdict": verdict, "output": redacted}),
            )
            return _UnitOutcome(
                kind="failed", hops=[hop], reason=f"{role} reported {verdict.upper()}"
            )

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

    def _run_group_node(node: _orch.PlannedGroup, index_for_context: int) -> _UnitOutcome:
        """Run a parallel group's children concurrently; join before advancing.

        Priority when merging children's outcomes: blocked > failed > advance
        (a rework outcome is impossible here — the pipeline format's own
        validator forbids a rework edge on a step nested inside a group).
        """
        prior_snapshot = list(prior)
        child_outcomes = _orch.run_group(
            node.children,
            lambda child: _execute_unit(
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
            if oc.kind == "blocked":
                merged.kind, merged.reason = "blocked", oc.reason
                break
        else:
            for oc in child_outcomes:
                if oc.kind == "failed":
                    merged.kind, merged.reason = "failed", oc.reason
                    break
        return merged

    while pipeline_index < len(runtime_steps):
        node = runtime_steps[pipeline_index]

        if isinstance(node, _orch.PlannedGroup):
            outcome = _run_group_node(node, pipeline_index)
        else:
            rework_hop = pending_rework_by_index.pop(pipeline_index, None)
            outcome = _execute_unit(
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
            _pause_lead_for_budget(project)
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
        if outcome.kind == "rework":
            assert outcome.rework_target_index is not None
            pending_rework_by_index[outcome.rework_target_index] = outcome.hops[0]
            pipeline_index = outcome.rework_target_index
            continue
        pipeline_index += 1

    _trace.trace_event(
        project,
        session_id,
        "lead",
        "session_end",
        _json.dumps({"status": result.status}),
    )
    return result


def _apply_result(task: dict[str, Any], res: TaskResult) -> None:
    """Fold a TaskResult back onto the stored task dict (terminal state).

    R-1: a ``blocked`` task stays ``blocked`` — it is never rewritten to
    ``pending`` here (that rewrite was the bug letting a budget-capped task
    retry forever on every sweep). It re-enters ``pending`` only through
    ``unblock_pod`` (pod-wide budget change) or ``retry_task`` (single task).

    G-1: a ``waiting_approval`` task is likewise left exactly there — it
    re-enters ``pending`` only through ``resolve_waiting_approval`` (a grant),
    never automatically. Its ``approvalToken``/``pendingApprovalIndex`` are
    persisted so a grant/deny later in time can find and resolve it.

    C-3: this function is pure (no *project*, no workspace access) and stays
    that way — the HEARTBEAT.md dispatch-ledger sync this terminal state
    triggers lives in the caller (``_finalize_task``), which is the one that
    has *project* and can resolve the pod Lead's workspace.
    """
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
    """Whether *t* can be claimed by this dispatch run.

    A plain ``pending`` task always is. A ``failed`` task whose failure was a
    swept stale claim (a prior dispatcher crashed mid-task) is claimable only
    when *resume* is set — crash recovery is opt-in, never an automatic retry.
    A ``waiting_approval`` task is never claimable here at all (G-1) — it
    re-enters ``pending`` only via a granted approval's ``resolve_waiting_approval``
    call, never a plain dispatch run.
    """
    status = t.get("status")
    if status == "pending":
        return True
    return bool(resume and status == "failed" and t.get("failureKind") == "stale_claim")


def _claim_next_task(
    project: str, *, resume: bool
) -> tuple[dict[str, Any], list[HopResult]] | None:
    """Locked claim of the pod's next eligible task (highest priority first).

    The whole read → pick → flip-to-``running`` → write happens under one
    filelock (``store.read_modify_write``), so two concurrent callers can never
    claim the same task — each sees the other's claim already applied and picks
    a different one (or finds nothing left). ``startedAt``/``claimId``/
    ``claimedAt`` are persisted before this function returns, so a crash right
    after claiming still shows ``running`` on disk, never ``pending`` again.

    Returns the claimed task (a normalized copy) and any hops already recorded
    for it (empty for a fresh ``pending`` task, the pre-crash hops for a
    resumed one) — or ``None`` if nothing is claimable.

    R-5: a paused pod (its Lead's ``paused`` flag — set by
    ``_pause_lead_for_budget`` once the budget cap is reached) refuses every
    claim outright — no task in its queue is even flipped to ``running``, let
    alone run. This is checked here (a plain read, outside the queue file's
    lock — pause changes are rare, operator-driven events, not something
    concurrent claims race over) rather than inside ``dispatch_task``'s
    per-hop gate, so a paused pod costs nothing further to *not* dispatch: no
    claim write, no wasted turn. A ``paused_refused`` trace event records the
    refusal every time it happens.

    C-3: a successful claim also mechanically syncs the pod Lead's
    HEARTBEAT.md dispatch ledger (``core/memory.py``'s ``sync_dispatch_tasks``)
    from the just-written queue state — so the durable ledger shows this task
    as in flight *before* its first hop ever runs, whether or not the agent
    would have written that down itself.
    """
    lead_id = _pod.member_id(project, "lead")
    if _models.AgentMeta.coerce_paused(_oc.meta_get(lead_id, "paused", "")):
        _trace.trace_event(
            project,
            f"agent:{project}:dispatch",
            "lead",
            "paused_refused",
            _json.dumps({"reason": _oc.meta_get(lead_id, "pausedReason", "") or "budget"}),
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
        # G-1: a granted approval's gate-override is single-use — captured
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
    """Append one just-completed hop to the task's persisted record.

    Called after every hop, not only at task end — a crash mid-task then loses
    at most the in-flight hop, never the ones that already finished. R-2: also
    refreshes ``claimedAt`` — a completed hop is forward progress, same as a
    retry (see ``_touch_claim``), so it resets the stale-claim clock too.

    C-3: re-syncs the pod Lead's HEARTBEAT.md dispatch ledger — this hop just
    changed the task's persisted hop count, and the ledger's entry for it
    should show that. C-5: if *hop*'s own agent (``hop.member_id``) has a
    tracked conversation (``core/conversations.py``), refreshes its
    ``last_message``/``task_ref`` from this hop — real dispatch activity a
    human watching that channel thread should see, not just whatever
    ``docket wire`` seeded once at binding time. A no-op for an unwired
    member (``touch_for_hop`` never fabricates a conversation).
    """

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

    reg = _conv.load()
    updated_reg = _conv.touch_for_hop(
        reg, agent_id=hop.member_id, task_ref=task_id, last_message=hop.output, now=_now()
    )
    if updated_reg is not reg:  # touch_for_hop is a no-op (same object) for an unwired agent
        _conv.save(updated_reg)


def _touch_claim(project: str, task_id: str) -> None:
    """Refresh a ``running`` task's ``claimedAt`` without touching anything else.

    R-2's subtle correctness point: retries add a backoff sleep plus another
    agent-turn timeout to a single hop's wall-clock time, on top of whatever the
    earlier hops already took. Before this card, ``claimedAt`` was set once at
    claim time and never touched again until the *next* hop finished — so a long
    enough retry run (or just a long enough pipeline) could push the elapsed time
    since ``claimedAt`` past ``CLAIM_STALE_TIMEOUT`` even though the task is very
    much alive. ``_sweep_stale_claims`` runs at the top of every ``dispatch_pod``
    call, including ones from a *different* thread dispatching the same pod
    concurrently (the whole reason R-1's claims are locked in the first place) —
    without a refresh, that concurrent sweep would see a stale-looking
    ``claimedAt`` and fail the task out from under the dispatcher still actively
    retrying it, mid-hop. Called before every retry attempt (``dispatch_task``'s
    ``on_retry``); hop completion is separately covered by ``_persist_hop`` above.
    A no-op if the task isn't ``running`` (e.g. it raced to a terminal state).

    C-3: also re-syncs the pod Lead's HEARTBEAT.md dispatch ledger so its
    entry's displayed claim time doesn't go stale across a long retry loop —
    a no-op write when the task wasn't ``running`` (``_fn`` returns ``None``,
    so ``doc`` below is just the unmodified current queue, same tasks the
    ledger already reflects).
    """

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
    """Persist a task's terminal outcome (status/reason/hops/cost) and clear its claim.

    C-3: also re-syncs the pod Lead's HEARTBEAT.md dispatch ledger —
    ``_apply_result`` just moved this task out of ``running`` (to ``done``,
    ``failed``, ``blocked``, or ``waiting_approval``), so no hop is in flight
    for it any more and its ledger entry is cleared. This is the only trigger
    that ever *removes* an entry (``_claim_next_task``/``_persist_hop``/
    ``_touch_claim`` only ever add one or keep it current).
    """

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
    """Crash recovery: fail a ``running`` task whose claim has gone stale.

    A task claimed (flipped to ``running``) longer than ``CLAIM_STALE_TIMEOUT``
    ago without reaching a terminal status is presumed to belong to a
    dispatcher that crashed mid-hop. Swept to ``failed`` with
    ``failureKind: "stale_claim"`` and a ``stale_claim`` trace event; its
    already-persisted ``hops`` are left untouched so a later
    ``dispatch_pod(..., resume=True)`` can continue from the last one instead
    of hop 0. Runs at the top of every ``dispatch_pod`` call.
    """
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
    """Un-block a single ``blocked`` task: a locked ``blocked`` → ``pending`` flip.

    The only other way a blocked task re-enters the queue is a pod-wide budget
    change (see ``unblock_pod``). Returns False (no-op) if the task doesn't
    exist or isn't currently blocked.
    """
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
    """Un-block every ``blocked`` task in *project*'s queue.

    Wired to ``docket profile <lead-id> --budget ...`` (cli/__init__.py) when
    the changed agent is that pod's Lead — a pod-wide budget change is the
    other sanctioned way (besides ``retry_task``) for a blocked task to become
    pending again. Returns the number of tasks unblocked (0 if the pod has no
    queue file yet, or nothing was blocked).
    """
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
    """React to a just-applied approval decision by mutating the dispatch task
    it gated, if any (G-1 — the other half of the approval store's missing
    producer: making a grant/deny actually move a task, not just the approval
    record).

    *decision* is ``"granted"`` or ``"denied"`` — the state ``core/approval.py``'s
    own ``approval_grant``/``approval_deny`` (or its expiry sweep) already
    transitioned the approval record *to*; this function only reacts to that,
    it never mutates the approval record itself. Called from every surface
    that can resolve an approval: ``cli/_approve.py``, ``cli/_deny.py``,
    ``serve.py``'s ``POST /approvals/<token>``, and ``core/approval.py``'s own
    ``approval_sweep_expired`` (the fail-closed timeout path).

    Returns ``False`` (a harmless no-op) when *token* was never created by
    this module's require_approval gate (no ``context.taskId``/``project`` on
    the approval record — e.g. some other, non-dispatch approval), when the
    approval record itself no longer exists, or when the named task is no
    longer ``waiting_approval`` on this exact token (already resolved by a
    concurrent caller, or the queue no longer has it). Returns ``True`` when a
    task was found and updated.

    Granted: the task moves ``waiting_approval`` -> ``pending``, its persisted
    ``hops[]`` untouched, and the exact pipeline position it stopped at is
    handed to the *next* claim as a single-use gate override (see
    ``_claim_next_task``) — "the next dispatch continues from that hop." No
    agent turn runs here; resuming genuinely requires a real dispatch
    invocation later.

    Denied: the task moves ``waiting_approval`` -> ``failed`` immediately —
    ``failureKind: "approval_denied"``, terminal, never auto-retried by a
    later ``dispatch_pod`` call (``--resume`` only ever reclaims a
    ``stale_claim`` failure). No agent turn is needed to fail a task that
    never ran its gated hop, so — unlike a grant — this happens synchronously.
    """
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
    """Dispatch a pod's pending tasks through the pipeline (highest priority first).

    *spec* (W-2) is forwarded to every ``dispatch_task`` call this makes;
    ``None`` (the default, used by every pre-W-2 caller) resolves this pod's
    zero-migration pipeline — see ``dispatch_task``.

    Each task is claimed under a filelock before its first hop runs (see
    ``_claim_next_task``) rather than read unlocked and mutated in memory, and
    hops persist to the queue as they complete (see ``_persist_hop``) rather
    than only when the whole task finishes — the R-1 fixes for the concurrent-
    dispatch race and crash-mid-task re-run. A stale ``running`` claim is swept
    to ``failed`` first (``_sweep_stale_claims``); pass *resume* to also
    reclaim those tasks and continue them from their last persisted hop
    instead of hop 0. A ``blocked`` (budget) task is left ``blocked`` — never
    silently retried.

    *turn_timeout*/*verify_timeout* (R-2) are per-call overrides; ``None`` (the
    default) falls back to the pod Lead's meta, then ``DEFAULT_TIMEOUT`` (see
    ``dispatch_task``/``_resolve_timeout``). A retryable hop failure is retried
    in place (see ``dispatch_task``); every retry and every completed hop
    refreshes the claimed task's ``claimedAt`` (``_touch_claim``/``_persist_hop``)
    so a legitimately-still-running retry loop never looks like a stale claim to
    a concurrent dispatcher's sweep. *sleep* — if given — replaces the real
    ``time.sleep`` used for retry backoff (tests only; production callers never
    need to pass this).

    Returns one TaskResult per task attempted. Raises DispatchError if the pod
    has no Lead.
    """
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
    all_ids = [a.id for a in _oc.list_agents()]
    projects: list[str] = []
    for aid in all_ids:
        proj = _pod.pod_of(aid)
        if proj and aid == _pod.member_id(proj, "lead") and proj not in projects:
            projects.append(proj)
    return projects


def pod_roster() -> list[dict[str, Any]]:
    """Every provisioned pod (grouped by project, alphabetical) with its member roster.

    Pure data assembly for a read-only "list every pod" view — the same
    registered-agent grounding ``dispatchable_pods()`` uses, extended with each
    member's role and model (mirrors what ``cli/_pod.py``'s ``_pod_list``
    renders per-project, just across every pod at once). No printing, no side
    effects beyond the ACL reads. Used by ``docket mcp serve``'s ``pods`` tool
    (Phase 18 L-3); ``core/pod.py`` stays I/O-free, so this assembly lives here
    alongside ``dispatchable_pods()`` rather than there.
    """
    all_ids = [a.id for a in _oc.list_agents()]
    projects = sorted({p for aid in all_ids if (p := _pod.pod_of(aid))})

    out: list[dict[str, Any]] = []
    for project in projects:
        members = _pod.members_of(all_ids, project)
        out.append(
            {
                "project": project,
                "members": [
                    {"id": mid, "role": role, "model": _oc.meta_get(mid, "model", "")}
                    for mid, role, _idx in members
                ],
            }
        )
    return out


# W-5 (dead-code register): `dispatch_all_pods` — a "dispatch every pod in one
# sweep" helper — was flagged as having zero production callers. Investigated:
# it genuinely has none, and for a real reason, not an oversight. R-3 replaced
# its former one call site (`serve.py`'s sweep loop, which used to call this
# inside a bare `contextlib.suppress(Exception)`) with a loop over
# `dispatchable_pods()` calling `dispatch_pod()` per pod through
# `core.runs.execute` — see `tests/python/test_r3_no_suppressed_dispatch.py`'s
# `test_dispatch_all_pods_no_longer_called_unguarded_in_serve`, which pins
# both halves of that fact (this name gone from serve.py, `dispatchable_pods`
# present). The reason: this function's one-record-per-sweep, "best-effort,
# swallow DispatchError" shape loses exactly the per-pod granularity R-3 was
# about (an id in the run registry per pod, a real error surfaced instead of
# silently skipped). Re-wiring it would reintroduce the coarse-grained
# behaviour R-3 deliberately replaced, so it is deleted rather than wired.
