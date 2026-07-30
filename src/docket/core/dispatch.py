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

R-5 (budget honesty): the per-hop budget gate now actually pauses the pod once its cap is
reached (``_pause_lead_for_budget`` writes the Lead's ``paused``/``pausedReason`` — previously
nothing ever set that flag, see ``core/models.py``'s ``AgentMeta.paused``), and
``_claim_next_task`` refuses every further claim for a paused pod outright (a ``paused_refused``
trace event, no claim write, no wasted turn) until ``docket profile <lead-id> --resume`` clears
it. Gating also tolerates a daemon that never records a ``usage.cost.total`` at all — see
``pod_gating_cost``'s token-based estimate fallback, used for gating/warning only and always
labelled, never presented as recorded spend.
"""

from __future__ import annotations

import datetime as _dt
import json as _json
import re as _re
import uuid as _uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import docket.config as _cfg
from docket.core import models as _models
from docket.core import pod as _pod
from docket.core import trace as _trace
from docket.core import utils as _utils
from docket.edges import store as _store
from docket.edges.adapters import openclaw as _oc
from docket.edges.adapters import system as _sys

# Only roles the pod actually has run — lean pod (lead + implementer) = 2 hops; full pod = 4.
PIPELINE_ORDER: tuple[str, ...] = ("lead", "implementer", "reviewer", "tester")

# Injectable runner for tests (matches the ACL ``agent_run`` signature).
Runner = Callable[[str, str, str, int, dict[str, str] | None], _oc.AgentRunResult]

DEFAULT_TIMEOUT = 300

# Priority sort key shared by task selection everywhere it matters.
_PRIORITY_RANK: dict[str, int] = {"high": 0, "normal": 1, "low": 2}

# FD-2: the Tester's documented contract (see cli/_pod.py's Tester SOUL.md body) is a
# binary PASS/FAIL first line. Matched case-insensitively; anything else is unparseable.
_TESTER_VERDICT_RE = _re.compile(r"^\s*(PASS|FAIL)\b", _re.IGNORECASE)


def _parse_tester_verdict(output: str) -> str | None:
    """Parse the Tester hop's first non-blank line for a PASS/FAIL marker.

    Returns ``"pass"``/``"fail"`` (lowercased) on a match, or ``None`` if the
    output doesn't start with one of those markers (unparseable — treated as
    distinct from an explicit FAIL, see ``dispatch_task``).
    """
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        match = _TESTER_VERDICT_RE.match(stripped)
        return match.group(1).lower() if match else None
    return None


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


@dataclass
class TaskResult:
    """Outcome of driving one task through the whole pipeline."""

    task_id: str
    status: str  # "done" | "failed" | "blocked"
    reason: str = ""
    hops: list[HopResult] = field(default_factory=list)

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


def enqueue_task(project: str, description: str, priority: str = "normal") -> dict[str, Any]:
    """Append a pending task to the pod's queue and return it.

    Raises DispatchError if the project has no Lead workspace (no pod yet). The
    append is a locked read-modify-write (``store.read_modify_write``) so two
    concurrent ``delegate`` calls can never clobber each other's task.
    """
    path = pod_task_list_path(project)
    if not path.parent.is_dir():
        raise DispatchError(f"no pod for '{project}' (run: docket add {project})")

    task: dict[str, Any] = {
        "id": f"task-{_uuid.uuid4()}",
        "description": description,
        "priority": priority if priority in ("high", "normal", "low") else "normal",
        "status": "pending",
        "created": _now(),
        "startedAt": None,
        "completedAt": None,
        "source": "operator",
        "hops": [],
        "reason": "",
        "costUsd": 0.0,
        "claimId": None,
        "claimedAt": None,
    }

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


def pod_gating_cost(project: str) -> tuple[float, bool]:
    """The pod's spend for budget-**gating** purposes: recorded, or estimated.

    Prefers ``pod_recorded_cost`` (the daemon's own ``usage.cost.total``,
    summed across the pod's members). Daemon v2026.2.23 may never write that
    field at all (see ``edges/adapters/openclaw.py``'s ``AgentRunResult.cost_usd``
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


_TRUNCATION_MARKER = "\n[... truncated {n} bytes ...]\n"


def _hop_carryover_budget(rank: int, total_budget: int) -> int:
    """Byte budget for one prior hop's output, by recency ``rank`` (0 = most recent).

    R-7's safety-cap policy, deliberately simple: each hop one step further into
    the past gets half the budget of the one before it (``total_budget >> (rank+1)``).
    That halving series never sums to more than ``total_budget`` no matter how many
    prior hops exist (a partial geometric series with ratio 1/2), so the *total*
    carryover threaded into a prompt is bounded regardless of pipeline length —
    while the most recent (most relevant) hop is always squeezed the least.
    """
    return total_budget >> (rank + 1)


def _truncate_carryover(output: str, budget: int) -> tuple[str, bool, int]:
    """Truncate *output* to at most *budget* UTF-8 bytes, head + tail.

    Returns ``(text, truncated, sent_bytes)``. If *output* already fits within
    *budget* it is returned unchanged (``truncated=False`` — this is what keeps
    small tasks byte-identical to pre-cap behaviour). Otherwise the head and
    tail are kept in roughly equal shares of the remaining room (after
    reserving space for the marker itself, so the result never exceeds
    *budget*) and the omitted middle is replaced with an explicit
    ``[... truncated N bytes ...]`` marker recording exactly how many bytes
    were dropped.
    """
    encoded = output.encode("utf-8")
    if len(encoded) <= budget:
        return output, False, len(encoded)

    # Reserve room for the marker using the *total* length as a safe upper
    # bound for its digit width — the real omitted count can only be smaller,
    # so the marker built from it below never ends up longer than reserved.
    reserved = _TRUNCATION_MARKER.format(n=len(encoded))
    remaining = max(budget - len(reserved.encode("utf-8")), 0)
    head_len = remaining // 2
    tail_len = remaining - head_len
    omitted = len(encoded) - head_len - tail_len
    marker = _TRUNCATION_MARKER.format(n=omitted)
    head = encoded[:head_len].decode("utf-8", errors="ignore")
    tail = encoded[len(encoded) - tail_len :].decode("utf-8", errors="ignore") if tail_len else ""
    text = f"{head}{marker}{tail}"
    return text, True, len(text.encode("utf-8"))


@dataclass
class _HopComposition:
    """Per-hop prompt-composition stats, recorded via the ``context_composed`` trace event."""

    description_bytes: int
    sections: list[dict[str, Any]] = field(default_factory=list)
    total_bytes: int = 0
    truncated: bool = False


def _hop_message(
    task: dict[str, Any], role: str, prior: list[HopResult]
) -> tuple[str, _HopComposition]:
    """Build the message handed to one role, threading prior hops' output.

    The task description is never truncated. Each prior hop's output is capped
    per ``_hop_carryover_budget`` (newest hop least-truncated) and truncated
    head+tail via ``_truncate_carryover`` when it doesn't fit. Returns the
    composed message plus a ``_HopComposition`` recording what was sent, for
    the ``context_composed`` trace event — a measured baseline for Phase 17's
    context compiler, not a compiler itself.
    """
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

    budget = _cfg.HOP_CARRYOVER_BYTES
    lines = [f"Task: {desc}", ""]
    comp = _HopComposition(description_bytes=len(desc.encode("utf-8")))
    last_index = len(prior) - 1
    # Iterate in the original chronological order (oldest first) — unchanged
    # from pre-cap behaviour, so message *layout* never changes, only content.
    # Only the per-hop budget is recency-aware: rank counts back from the most
    # recent hop (rank 0), so `_hop_carryover_budget` gives it the biggest share.
    for i, h in enumerate(prior):
        if not h.output:
            continue
        rank = last_index - i
        hop_budget = _hop_carryover_budget(rank, budget)
        original_bytes = len(h.output.encode("utf-8"))
        text, truncated, sent_bytes = _truncate_carryover(h.output, hop_budget)
        comp.sections.append(
            {
                "role": h.role,
                "original_bytes": original_bytes,
                "sent_bytes": sent_bytes,
                "truncated": truncated,
            }
        )
        comp.truncated = comp.truncated or truncated
        lines.append(f"--- {h.role} output ---\n{text}\n")
    if role == "implementer":
        lines.append("You are the Implementer. Implement the change in the workspace.")
    elif role == "reviewer":
        lines.append(
            "You are the Reviewer. Review the diff (read-only). Approve or request changes."
        )
    elif role == "tester":
        lines.append(
            "You are the Tester. Validate behaviour only. Your reply's first "
            "non-blank line must be exactly PASS or FAIL (case-insensitive), "
            "followed by evidence."
        )
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


def _hop_record(h: HopResult) -> dict[str, Any]:
    """The persisted-queue-file shape of one hop (round-trips via ``_hop_from_record``)."""
    return {
        "role": h.role,
        "member": h.member_id,
        "ok": h.ok,
        "output": h.output,
        "costUsd": round(h.cost_usd, 6),
        "error": h.error,
    }


def _hop_from_record(rec: dict[str, Any]) -> HopResult:
    """Reconstruct a HopResult from a persisted hop record (for resume)."""
    return HopResult(
        role=str(rec.get("role", "")),
        member_id=str(rec.get("member", "")),
        ok=bool(rec.get("ok", False)),
        output=str(rec.get("output", "")),
        cost_usd=float(rec.get("costUsd", 0.0) or 0.0),
        error=str(rec.get("error", "")),
    )


def dispatch_task(
    project: str,
    task: dict[str, Any],
    *,
    runner: Runner | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    resume_from: list[HopResult] | None = None,
    on_hop: Callable[[HopResult], None] | None = None,
) -> TaskResult:
    """Drive one task through the pod pipeline, hop by hop.

    Budget is checked before EACH hop (every hop is a real costed turn). A failed
    hop stops the pipeline (later roles only matter if earlier ones succeed). All
    dispatch targets belong to this project's pod — asserted per hop.

    *resume_from* seeds hops that already completed before a crash (role +
    output preserved) so the roles still to come see the same context an
    uninterrupted run would have produced; those roles are skipped rather than
    re-invoked. *on_hop* — if given — fires with each new HopResult right after
    it completes, so the caller can persist per-hop progress incrementally
    instead of only when the whole task finishes (R-1 crash-safety).
    """
    run = runner or _oc.agent_run
    task_id = str(task.get("id", "task"))
    session_id = f"agent:{project}:{task_id}"
    pipeline = pod_pipeline(project)
    cap = pod_budget(project)

    prior: list[HopResult] = list(resume_from) if resume_from else []
    done_roles = {h.role for h in prior}

    _trace.trace_event(
        project,
        session_id,
        "lead",
        "session_start",
        _json.dumps({"source": "dispatch", "task": task_id, "resumed": bool(prior)}),
    )

    result = TaskResult(task_id=task_id, status="done", hops=list(prior))

    for role, member_id in pipeline:
        if role in done_roles:
            continue  # already completed before a crash — resuming, not re-running

        # No-cross-pod guarantee: never dispatch to an id outside this pod.
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
                _trace.trace_event(
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
                result.status = "blocked"
                result.reason = f"pod budget reached ({spent_label} ≥ ${cap:.2f}) before {role}"
                _pause_lead_for_budget(project)
                break

        message, composition = _hop_message(task, role, prior)
        _trace.trace_event(
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
        _trace.trace_event(
            project,
            session_id,
            role,
            "tool_call",
            _json.dumps({"hop": role, "agent": member_id}),
        )
        env = _hop_env(member_id, role)
        run_res = run(member_id, session_id, message, timeout, env)
        hop = HopResult(
            role=role,
            member_id=member_id,
            ok=run_res.ok,
            output=run_res.output,
            cost_usd=run_res.cost_usd,
            error=run_res.error,
        )
        result.hops.append(hop)
        prior.append(hop)
        if on_hop is not None:
            on_hop(hop)

        _trace.trace_event(
            project,
            session_id,
            role,
            "tool_result" if run_res.ok else "error",
            run_res.output or run_res.error or "",
            cost_usd=run_res.cost_usd or None,
        )
        if run_res.cost_usd:
            _trace.trace_event(
                project,
                session_id,
                role,
                "cost_charged",
                _json.dumps({"role": role}),
                cost_usd=run_res.cost_usd,
            )

        if not run_res.ok:
            result.status = "failed"
            result.reason = f"{role} hop failed: {run_res.error or 'no result'}"
            break

        # Structural Tester gate (FD-2): the Tester's whole contract is a binary
        # PASS/FAIL report (see cli/_pod.py's Tester SOUL.md body) — a successful
        # subprocess call (run_res.ok) says nothing about *what* the Tester found,
        # so parse the marker convention here and block advancement on FAIL or on
        # output that doesn't follow the convention at all.
        if role == "tester":
            verdict = _parse_tester_verdict(run_res.output)
            if verdict != "pass":
                redacted = _trace.redact(run_res.output)
                _trace.trace_event(
                    project,
                    session_id,
                    role,
                    "tester_verdict_failed",
                    _json.dumps({"verdict": verdict or "unparseable", "output": redacted}),
                )
                result.status = "failed"
                if verdict == "fail":
                    result.reason = "tester reported FAIL"
                else:
                    result.reason = "tester output unparseable (expected a PASS/FAIL first line)"
                break

        # Verification gate: run after a successful Implementer hop, before reviewer/tester.
        if role == "implementer":
            verify_cmd = str(_oc.meta_get(member_id, "verifyCmd", "") or "")
            if verify_cmd:
                # R-6: verify in the implementer's own worktree when it has one —
                # else the shared codebase root — else its workspace dir. Shared
                # with cli/_pod.py's _regenerate_member_tools via core/pod.py so
                # the two can't disagree about which tree is being checked.
                worktree_dir = str(_oc.meta_get(member_id, "worktreeDir", "") or "")
                impl_codebase = str(_oc.meta_get(member_id, "codebase", "") or "")
                cwd = _pod.resolve_member_cwd(member_id, worktree_dir, impl_codebase)
                passed, raw_output = _sys.run_verify_cmd(verify_cmd, cwd, timeout)
                redacted = _trace.redact(raw_output)
                if not passed:
                    _trace.trace_event(
                        project,
                        session_id,
                        role,
                        "verification_failed",
                        _json.dumps({"cmd": verify_cmd, "output": redacted}),
                    )
                    result.status = "failed"
                    result.reason = f"verifyCmd failed: {verify_cmd!r}"
                    break
                _trace.trace_event(
                    project,
                    session_id,
                    role,
                    "tool_result",
                    _json.dumps({"verification": "passed", "cmd": verify_cmd}),
                )
            else:
                # Honesty rule: never silently skip — a missing verifyCmd is visible.
                print(f"[dispatch] verification skipped — verifyCmd not set for {member_id}")

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
    """
    task["status"] = res.status
    task["reason"] = res.reason
    task["hops"] = [_hop_record(h) for h in res.hops]
    task["costUsd"] = res.cost_usd
    task["claimId"] = None
    if res.status == "blocked":
        task["blockedReason"] = res.reason
    else:
        task["completedAt"] = _now()
        task.pop("failureKind", None)  # a fresh terminal result supersedes any stale-claim marker


def _eligible_for_claim(t: dict[str, Any], *, resume: bool) -> bool:
    """Whether *t* can be claimed by this dispatch run.

    A plain ``pending`` task always is. A ``failed`` task whose failure was a
    swept stale claim (a prior dispatcher crashed mid-task) is claimable only
    when *resume* is set — crash recovery is opt-in, never an automatic retry.
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
        return {"tasks": tasks}

    _store.read_modify_write(pod_task_list_path(project), _fn)
    if claimed is None:
        return None
    resume_hops = [_hop_from_record(h) for h in claimed.get("hops", []) if isinstance(h, dict)]
    return claimed, resume_hops


def _persist_hop(project: str, task_id: str, hop: HopResult) -> None:
    """Append one just-completed hop to the task's persisted record.

    Called after every hop, not only at task end — a crash mid-task then loses
    at most the in-flight hop, never the ones that already finished.
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
                return {"tasks": tasks}
        return None  # task no longer in the queue — nothing to persist

    _store.read_modify_write(pod_task_list_path(project), _fn)


def _finalize_task(project: str, task_id: str, res: TaskResult) -> None:
    """Persist a task's terminal outcome (status/reason/hops/cost) and clear its claim."""

    def _fn(doc: dict[str, Any]) -> dict[str, Any] | None:
        tasks_raw = doc.get("tasks")
        tasks = tasks_raw if isinstance(tasks_raw, list) else []
        for t in tasks:
            if t.get("id") == task_id:
                _apply_result(t, res)
                return {"tasks": tasks}
        return None

    _store.read_modify_write(pod_task_list_path(project), _fn)


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


def dispatch_pod(
    project: str,
    *,
    runner: Runner | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    max_tasks: int | None = None,
    resume: bool = False,
) -> list[TaskResult]:
    """Dispatch a pod's pending tasks through the pipeline (highest priority first).

    Each task is claimed under a filelock before its first hop runs (see
    ``_claim_next_task``) rather than read unlocked and mutated in memory, and
    hops persist to the queue as they complete (see ``_persist_hop``) rather
    than only when the whole task finishes — the R-1 fixes for the concurrent-
    dispatch race and crash-mid-task re-run. A stale ``running`` claim is swept
    to ``failed`` first (``_sweep_stale_claims``); pass *resume* to also
    reclaim those tasks and continue them from their last persisted hop
    instead of hop 0. A ``blocked`` (budget) task is left ``blocked`` — never
    silently retried.

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

        res = dispatch_task(
            project,
            task,
            runner=runner,
            timeout=timeout,
            resume_from=resume_hops,
            on_hop=_persist,
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


def dispatch_all_pods(
    *,
    runner: Runner | None = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> dict[str, list[TaskResult]]:
    """Dispatch every pod's queue once (used by the opt-in `serve --dispatch` loop).

    Best-effort per pod: one pod failing to dispatch never blocks the others.
    Never auto-resumes a crashed pod's stale-claim failures — that stays an
    explicit, operator-driven action (``docket pod <p> dispatch --resume``).
    """
    out: dict[str, list[TaskResult]] = {}
    for project in dispatchable_pods():
        try:
            res = dispatch_pod(project, runner=runner, timeout=timeout)
        except DispatchError:
            continue
        if res:
            out[project] = res
    return out
