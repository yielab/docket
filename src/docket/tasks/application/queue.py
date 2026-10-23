from __future__ import annotations

import json as _json
import os as _os
from dataclasses import replace
from pathlib import Path
from typing import Any

from pydantic import ValidationError as _ValidationError

from docket.agent import handoff as _handoff
from docket.agent import isolation_posture as _isolation_posture
from docket.agent import memory as _mem
from docket.governance import approval as _ap
from docket.governance import audit as _audit
from docket.governance import policy as _policy
from docket.hops.application.record import _hop_from_record
from docket.hops.workspace import prepare as _prepare
from docket.hops.workspace.worktree import _ensure_task_worktree
from docket.kernel import clock as _clock
from docket.kernel import ids as _ids
from docket.kernel.home import current_home
from docket.kernel.jail import jail as _jail
from docket.observability import trace as _trace
from docket.operator import contract as _oc
from docket.platform import read_json, read_modify_write
from docket.tasks.domain import options as _task_options
from docket.tasks.domain.task import (
    DispatchError,
    HopResult,
    TaskRestrictionError,
    TaskResult,
    _normalize_task,
)
from docket.teams import fleet as _fleet
from docket.teams import models as _models
from docket.teams import pod as _pod
from docket.teams.settings import _pod_settings, pod_task_list_path

# Priority sort key shared by task selection everywhere it matters.
_PRIORITY_RANK: dict[str, int] = {"high": 0, "normal": 1, "low": 2}

# `failed` task ``failureKind`` values ``--resume`` is allowed to reclaim (see
# ``_eligible_for_claim`` and pod-dispatch.spec.md "Claiming"): a swept crash
# (``stale_claim``) and a settled deterministic refusal (``dispatch_refused``,
# see ``dispatch_task``'s ``DispatchError`` handling). Neither is a graded
# hop/gate outcome, so neither is a "real gate/hop failure" in the sense
# "blocked and terminal-failure re-entry" uses that phrase for. Shared by
# ``interfaces/cli/commands/run.py``'s "anything to do?" gate so the two never drift apart.
RESUMABLE_FAILURE_KINDS: frozenset[str] = frozenset({"stale_claim", "dispatch_refused"})


def read_tasks(project: str) -> list[dict[str, Any]]:
    """Return the pod's task list ([] if the queue file is absent), normalized."""
    raw = read_json(pod_task_list_path(project))
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
    hit = _policy.policy_eval_detail(
        "lead", "pre_input", description, trusted=trusted, project=project
    )
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


def validate_task_options(**raw: Any) -> _task_options.TaskOptions:
    """Validate the addressable-task fields; a wrong shape raises DispatchError, a widening
    restriction its subclass TaskRestrictionError."""
    try:
        return _task_options.validate_task_options(**raw)
    except _task_options.TaskRestrictionError as exc:
        raise TaskRestrictionError(str(exc)) from exc
    except _task_options.TaskOptionsError as exc:
        raise DispatchError(str(exc)) from exc


def _queued_with_key(tasks: list[dict[str, Any]], key: str) -> dict[str, Any] | None:
    return next((t for t in tasks if t.get("idempotencyKey") == key), None)


def enqueue_task_once(
    project: str,
    description: str,
    priority: str = "normal",
    *,
    channel: str,
    trusted: bool | None = None,
    brief: dict[str, Any] | None = None,
    **options: Any,
) -> tuple[dict[str, Any], bool]:
    """Locked read-modify-write returning ``(task, created)``; DispatchError persists nothing.
    A queued ``idempotency_key`` returns that task with ``created`` False; *options* are the
    addressable-task fields. *channel* (cli|http|telegram|mcp) is recorded, never trusted."""
    path = pod_task_list_path(project)
    if not path.parent.is_dir():
        raise DispatchError(f"no pod for '{project}' (run from its directory: docket init)")
    parsed_options = validate_task_options(**options)
    key = parsed_options.idempotency_key
    if key is not None and (queued := _queued_with_key(read_tasks(project), key)) is not None:
        return queued, False

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

    task_id = _ids.new_id("task")
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
        "created": _clock.iso(),
        "startedAt": None,
        "completedAt": None,
        "source": source,
        "channel": channel,
        "hops": [],
        "reason": "",
        "costUsd": 0.0,
        "claimId": None,
        "claimedAt": None,
    }
    if parsed_brief is not None:
        task["brief"] = parsed_brief.model_dump(by_alias=True)
    task.update(parsed_options.as_record())

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

    existing: list[dict[str, Any]] = []

    def _fn(doc: dict[str, Any]) -> dict[str, Any]:
        tasks_raw = doc.get("tasks")
        tasks = (
            [_normalize_task(t) for t in tasks_raw if isinstance(t, dict)]
            if isinstance(tasks_raw, list)
            else []
        )
        if key is not None and (queued := _queued_with_key(tasks, key)) is not None:
            existing.append(queued)
            return doc
        tasks.append(task)
        return {"tasks": tasks}

    read_modify_write(path, _fn)
    if existing:
        return existing[0], False
    _audit.audit_log("task.enqueue", f"project={project} task={task_id} channel={channel}")
    return task, True


def pod_full_roster(project: str) -> dict[str, str]:
    """Every role this pod has, first member per role (``role -> member_id``). Unlike
    :func:`pod_pipeline` (fixed to ``PIPELINE_ORDER``), this covers every role name so a
    custom :class:`~docket.pipeline.domain.spec.PipelineSpec` can target a role outside the default four."""
    all_ids = [a.id for a in _fleet.list_agents()]
    by_role: dict[str, str] = {}
    for mid, role, _idx in _pod.members_of(all_ids, project):
        by_role.setdefault(role, mid)
    return by_role


def _eligible_for_claim(t: dict[str, Any], *, resume: bool) -> bool:
    """Whether *t* can be claimed by this dispatch run. See pod-dispatch.spec.md ("Claiming"):
    ``pending`` always is; a ``failed`` task tagged with a RESUMABLE_FAILURE_KINDS reason only
    when *resume* is set (a swept crash, or a settled deterministic refusal -- neither waited
    out for staleness here, since a refusal's claim was already cleanly settled, not crashed);
    ``waiting_approval``/``waiting_input`` never -- neither status is ``pending`` or ``failed``,
    so both are already excluded by construction; a parked question re-enters only through
    ``tasks.application.answers.answer_task`` (-> ``pending``) or expiry (-> ``blocked``, retried like any
    other blocked task)."""
    status = t.get("status")
    if status == "pending":
        return True
    return bool(resume and status == "failed" and t.get("failureKind") in RESUMABLE_FAILURE_KINDS)


def _refuse_claimed_task(
    project: str, task: dict[str, Any], failure_kind: str, reason: str
) -> TaskResult:
    """Settle a just-claimed task ``failed`` with ``failure_kind`` and ``reason`` before any hop
    runs: clear the claim, keep the recorded hops, and trace ``dispatch_refused``."""
    task_id = str(task.get("id", "task"))

    def _fn(doc: dict[str, Any]) -> dict[str, Any] | None:
        tasks_raw = doc.get("tasks")
        tasks = tasks_raw if isinstance(tasks_raw, list) else []
        for t in tasks:
            if isinstance(t, dict) and t.get("id") == task_id:
                t["status"] = "failed"
                t["failureKind"] = failure_kind
                t["reason"] = reason
                t["completedAt"] = _clock.iso()
                t["claimId"] = None
                t.pop("claimPid", None)
                return {"tasks": tasks}
        return None

    doc = read_modify_write(pod_task_list_path(project), _fn)
    _trace.trace_event(
        project,
        f"agent:{project}:{task_id}",
        "lead",
        "dispatch_refused",
        _json.dumps({"reason": reason, "failureKind": failure_kind}),
    )
    tasks_after = doc.get("tasks")
    _mem.sync_dispatch_tasks(
        current_home().workspace_dir(_pod.member_id(project, "lead")),
        tasks_after if isinstance(tasks_after, list) else [],
    )
    return TaskResult(task_id=task_id, status="failed", reason=reason, failure_kind=failure_kind)


def _run_prepare_command(project: str, cmd: str, cwd: str) -> tuple[int | None, str]:
    """Run a task's install command: in the pod's jail with the network open for this launch
    only when isolation is on, on the host like a ``verifyCmd`` otherwise."""
    jail, refusal = _isolation_posture.resolve_command_jail(project, "prepare")
    if refusal is not None:
        return None, f"[prepare not run: {refusal}]"
    if jail is None:
        return _jail.run_command(cmd, cwd, current_home().prepare_timeout_s)
    return _jail.run_command(
        cmd, cwd, current_home().prepare_timeout_s, jail=replace(jail, network=True)
    )


def _prepare_reason(command: str, outcome: _prepare.PrepareOutcome) -> str:
    status = f"exit {outcome.exit_code}" if outcome.exit_code is not None else "no exit status"
    tail = _trace.redact(outcome.output)[-current_home().verify_evidence_tail_chars :]
    return f"prepare failed: {command} ({status}): {tail}"


def _trace_prepare(
    project: str, task_id: str, spec: _prepare.PrepareSpec, outcome: _prepare.PrepareOutcome
) -> None:
    payload = {
        "command": spec.command,
        "source": spec.source,
        "cacheHit": outcome.cache_hit,
        "seconds": round(outcome.seconds, 3),
        "exit": outcome.exit_code,
    }
    _trace.trace_event(
        project,
        f"agent:{project}:{task_id}",
        "lead",
        "prepare",
        _json.dumps(payload),
        duration_ms=int(outcome.seconds * 1000),
        task_id=task_id,
    )


def _store_prepared(project: str, task: dict[str, Any], prepared: dict[str, Any]) -> None:
    task["prepared"] = prepared
    task_id = task.get("id")

    def _fn(doc: dict[str, Any]) -> dict[str, Any] | None:
        tasks = doc.get("tasks")
        if not isinstance(tasks, list):
            return None
        for t in tasks:
            if isinstance(t, dict) and t.get("id") == task_id:
                t["prepared"] = prepared
        return {"tasks": tasks}

    read_modify_write(pod_task_list_path(project), _fn)


def _prepare_claimed_task(project: str, task: dict[str, Any]) -> TaskResult | None:
    """Prepare a claimed task's own worktree before its first hop (pod-dispatch.spec.md, "Task
    preparation"); the refusing ``TaskResult`` when the install fails, else ``None``."""
    worktree = task.get("worktree")
    root = str(worktree.get("dir") or "") if isinstance(worktree, dict) else ""
    if not root:
        return None
    try:
        pod_prepare = _pod_settings(project).prepare
    except DispatchError as exc:
        return _refuse_claimed_task(project, task, "prepare", str(exc))
    spec = _prepare.resolve(Path(root), task_prepare=task.get("prepare"), pod_prepare=pod_prepare)
    if spec is None or not _prepare.needs_prepare(Path(root), task.get("prepared"), spec):
        return None
    codebase = str(_fleet.meta_get(_pod.member_id(project, "implementer"), "codebase", "") or "")
    outcome = _prepare.prepare_worktree(
        spec,
        Path(root),
        codebase,
        str(worktree.get("commonDir") or "") if isinstance(worktree, dict) else "",
        lambda cmd: _run_prepare_command(project, cmd, root),
    )
    _trace_prepare(project, str(task.get("id", "")), spec, outcome)
    if not outcome.ok:
        return _refuse_claimed_task(
            project, task, "prepare", _prepare_reason(spec.command, outcome)
        )
    _store_prepared(project, task, _prepare.record(spec, outcome))
    return None


def _claim_next_task(
    project: str, *, resume: bool, skip: frozenset[str] = frozenset()
) -> tuple[dict[str, Any], list[HopResult]] | None:
    """Locked claim of the pod's next eligible task (highest priority first; pod-dispatch.spec.md,
    "Claiming", "Mechanical HEARTBEAT ledger"). One filelocked read-pick-flip-write so two
    concurrent callers can never claim the same task; a paused pod refuses every claim outright,
    checked outside the queue lock since pause changes are rare and operator-driven. Returns
    the claimed task and any recorded hops, or ``None``; also syncs the HEARTBEAT.md ledger.
    A task id in *skip* (one this run already claimed) is never picked again."""
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
        candidates = [
            i
            for i, t in enumerate(tasks)
            if t.get("id") not in skip and _eligible_for_claim(t, resume=resume)
        ]
        if not candidates:
            return None
        candidates.sort(
            key=lambda i: _PRIORITY_RANK.get(str(tasks[i].get("priority", "normal")), 1)
        )
        t = tasks[candidates[0]]
        t["status"] = "running"
        t["startedAt"] = _clock.iso()
        t["claimId"] = _ids.new_uuid()
        t["claimedAt"] = _clock.iso()
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

    doc = read_modify_write(pod_task_list_path(project), _fn)
    if claimed is None:
        return None
    _ensure_task_worktree(project, claimed)
    resume_hops = [_hop_from_record(h) for h in claimed.get("hops", []) if isinstance(h, dict)]
    tasks_after = doc.get("tasks")
    _mem.sync_dispatch_tasks(
        current_home().workspace_dir(lead_id), tasks_after if isinstance(tasks_after, list) else []
    )
    return claimed, resume_hops


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
                t["claimedAt"] = _clock.iso()
                return {"tasks": tasks}
        return None

    doc = read_modify_write(pod_task_list_path(project), _fn)
    tasks_after = doc.get("tasks")
    lead_id = _pod.member_id(project, "lead")
    _mem.sync_dispatch_tasks(
        current_home().workspace_dir(lead_id), tasks_after if isinstance(tasks_after, list) else []
    )


def _task_record(project: str, task_id: str) -> dict[str, Any] | None:
    return next((t for t in read_tasks(project) if t.get("id") == task_id), None)


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
    data assembly for ``docket start --mcp``'s ``pods`` tool, mirroring the CLI's pod list; lives here (not ``teams/pod.py``) to keep that module I/O-free."""
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
