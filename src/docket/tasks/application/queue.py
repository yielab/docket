from __future__ import annotations

import json as _json
from dataclasses import replace
from pathlib import Path
from typing import Any

from pydantic import ValidationError as _ValidationError

from docket.governance import approval as _ap
from docket.governance import audit as _audit
from docket.governance import policy as _policy
from docket.governance import secrets as _secrets
from docket.kernel import brief as _brief
from docket.kernel import clock as _clock
from docket.kernel import handoff as _handoff
from docket.kernel import ids as _ids
from docket.kernel import text as _text
from docket.kernel.errors import DispatchError
from docket.kernel.home import current_home
from docket.kernel.ids import step_session_key
from docket.kernel.ports import jail as _jail
from docket.observability import trace as _trace
from docket.tasks.application import transitions as _transitions
from docket.tasks.application.repository import Claim, TaskRepository, claimable
from docket.tasks.application.runs import get_run, list_runs
from docket.tasks.domain import options as _task_options
from docket.tasks.domain import state as _state
from docket.tasks.domain.parts import Prepared, Worktree
from docket.tasks.domain.refs import LEAD_STEP_ID, TaskRef, TaskRefError
from docket.tasks.domain.task import TaskRecord, TaskRestrictionError, TaskResult
from docket.teams import fleet as _fleet
from docket.teams import isolation_posture as _isolation_posture
from docket.teams import models as _models
from docket.teams import pod as _pod
from docket.teams.settings import builtin_tool_names, load_pod_settings, pod_task_list_path
from docket.teams.workspace import prepare as _prepare
from docket.teams.workspace.worktree import ensure_task_worktree


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
    rules = _task_options.OptionRules(
        known_tools=builtin_tool_names(),
        check_policy=_policy.task_policy_document,
        check_prepare=_text.check_command,
    )
    try:
        return _task_options.validate_task_options(rules=rules, **raw)
    except _task_options.TaskRestrictionError as exc:
        raise TaskRestrictionError(str(exc)) from exc
    except _task_options.TaskOptionsError as exc:
        raise DispatchError(str(exc)) from exc


def enqueue_task_once(
    project: str,
    description: str,
    priority: str = "normal",
    *,
    channel: str,
    trusted: bool | None = None,
    brief: dict[str, Any] | None = None,
    **options: Any,
) -> tuple[TaskRecord, bool]:
    """Locked read-modify-write returning ``(task, created)``; DispatchError persists nothing.
    A queued ``idempotency_key`` returns that task with ``created`` False; *options* are the
    addressable-task fields. *channel* (cli|http|telegram|mcp) is recorded, never trusted."""
    path = pod_task_list_path(project)
    if not path.parent.is_dir():
        raise DispatchError(f"no pod for '{project}' (run from its directory: docket init)")
    parsed_options = validate_task_options(**options)
    key = parsed_options.idempotency_key
    repo = TaskRepository.for_pod(project)
    if key is not None:
        queued = next((r for r in repo.list() if r.idempotency_key == key), None)
        if queued is not None:
            return queued, False

    # *brief*, when given, is a pre-brief the operator already knows: validated as a
    # TaskBrief (invalid raises DispatchError, nothing persisted), folded into the enqueued
    # description under its own heading -- so the pre_input screen below covers it like any
    # other human-sent string, and the Lead's first hop sees it -- and stored on the task's
    # own `brief` field.
    parsed_brief: _brief.TaskBrief | None = None
    if brief is not None:
        try:
            parsed_brief = _brief.TaskBrief.model_validate(brief)
        except _ValidationError as exc:
            raise DispatchError(f"invalid brief: {exc}") from exc
        description = f"{description}\n\n## Pre-brief\n{_handoff.render_brief(parsed_brief)}"

    task_id = _ids.new_id("task")
    session_id = f"agent:{project}:{task_id}"
    effective_trusted = True if trusted is None else trusted

    hit = _enqueue_pre_input_gate(
        project, session_id, task_id, description, trusted=effective_trusted
    )
    if hit.action == "block":
        raise DispatchError(
            f"task rejected by guardrail policy '{hit.policy_id}' at enqueue"
            + (f": {hit.message}" if hit.message else "")
        )

    record = TaskRecord(
        id=task_id,
        description=_secrets.redact(description) if hit.action == "redact" else description,
        priority=priority if priority in ("high", "normal", "low") else "normal",
        channel=channel,
        brief=parsed_brief,
        **parsed_options.model_dump(),
    )

    if hit.action == "require_approval":
        action_text = f"pod dispatch — task enqueue for '{project}': {description}"[:1000]
        token = _ap.approval_create(
            project, "lead", action_text, context={"taskId": task_id, "pipelineIndex": 0}
        )
        _transitions.apply_to_task(
            record, _state.Status.waiting_approval, approval_token=token, pending_index=0
        )
        _trace.trace_event(
            project,
            session_id,
            "lead",
            "approval_required",
            _json.dumps(
                {"role": "lead", "token": token, "pipelineIndex": 0, "policy": hit.policy_id}
            ),
        )

    stored, created = repo.add(record)
    if not created:
        return stored, False
    _audit.audit_log("task.enqueue", f"project={project} task={task_id} channel={channel}")
    return stored, True


def has_claimable_work(project: str) -> bool:
    """Whether a resuming sweep of *project* could claim anything: a task it may claim, or a
    ``running`` one whose claim may be stale. A sweep with neither records no run."""
    return any(
        r.status == _state.Status.running or claimable(r, resume=True)
        for r in TaskRepository.for_pod(project).list()
    )


def apply_transition(
    project: str, task_id: str, to: _state.Status, **facts: Any
) -> TaskRecord | None:
    """Move one task of *project*'s queue to *to* under the queue lock (``decide``'s *facts*
    are the keywords) and return it, or ``None`` when it is not queued."""
    return TaskRepository.for_pod(project).update(
        task_id, lambda r: _transitions.apply_to_task(r, to, **facts)
    )


def refuse_claimed_task(
    project: str, task: TaskRecord, failure_kind: str, reason: str
) -> TaskResult:
    """Settle a just-claimed task ``failed`` with ``failure_kind`` and ``reason`` before any hop
    runs: clear the claim, keep the recorded hops, and trace ``dispatch_refused``."""
    task_id = task.id
    apply_transition(
        project,
        task_id,
        _state.Status.failed,
        now=_clock.iso(),
        reason=reason,
        failure_kind=failure_kind,
        keep_grants=True,
    )
    _trace.trace_event(
        project,
        f"agent:{project}:{task_id}",
        "lead",
        "dispatch_refused",
        _json.dumps({"reason": reason, "failureKind": failure_kind}),
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
    tail = _secrets.redact(outcome.output)[-current_home().verify_evidence_tail_chars :]
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


def _store_prepared(project: str, task: TaskRecord, prepared: dict[str, Any]) -> None:
    stored = Prepared.model_validate(prepared)
    task.prepared = stored
    TaskRepository.for_pod(project).update(task.id, lambda r: setattr(r, "prepared", stored))


def prepare_claimed_task(project: str, task: TaskRecord) -> TaskResult | None:
    """Prepare a claimed task's own worktree before its first hop (pod-dispatch.spec.md, "Task
    preparation"); the refusing ``TaskResult`` when the install fails, else ``None``."""
    worktree = task.worktree
    root = worktree.dir if worktree is not None else ""
    if worktree is None or not root:
        return None
    try:
        pod_prepare = load_pod_settings(project).prepare
    except DispatchError as exc:
        return refuse_claimed_task(project, task, "prepare", str(exc))
    spec = _prepare.resolve(Path(root), task_prepare=task.prepare, pod_prepare=pod_prepare)
    if spec is None or not _prepare.needs_prepare(Path(root), task.prepared, spec):
        return None
    codebase = str(_fleet.meta_get(_pod.member_id(project, "implementer"), "codebase", "") or "")
    outcome = _prepare.prepare_worktree(
        spec,
        Path(root),
        codebase,
        worktree.common_dir or "",
        lambda cmd: _run_prepare_command(project, cmd, root),
    )
    _trace_prepare(project, task.id, spec, outcome)
    if not outcome.ok:
        return refuse_claimed_task(project, task, "prepare", _prepare_reason(spec.command, outcome))
    _store_prepared(project, task, _prepare.record(spec, outcome))
    return None


def claim_next_task(
    project: str, *, resume: bool, skip: frozenset[str] = frozenset()
) -> Claim | None:
    """Locked claim of the pod's next eligible task (highest priority first; pod-dispatch.spec.md,
    "Claiming", "Mechanical HEARTBEAT ledger"). One locked read-pick-flip-write so two
    concurrent callers can never claim the same task; a paused pod refuses every claim outright,
    checked outside the queue lock since pause changes are rare and operator-driven. Returns
    the ``Claim`` (the task, its recorded hops, a granted approval's gate override), or ``None``.
    A task id in *skip* (one this run already claimed) is never picked again. A task without a
    worktree gets one after the claim; the ``Claim`` carries ``refusal`` when a ``baseRef`` could
    not be honoured."""
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

    repo = TaskRepository.for_pod(project)
    claim = repo.claim_next(resume=resume, skip=skip)
    if claim is None:
        return None
    record = claim.record
    if record.worktree is not None:
        return claim
    stored, refusal = ensure_task_worktree(project, record.id, record.base_ref or "")
    if stored is not None:
        worktree = Worktree.model_validate(stored)
        repo.update(record.id, lambda r: setattr(r, "worktree", worktree))
        record.worktree = worktree
    return replace(claim, refusal=refusal)


def touch_claim(project: str, task_id: str) -> None:
    """Refresh a ``running`` task's ``claimedAt``, called before every retry attempt --
    without this, a long retry could push elapsed time past ``CLAIM_STALE_TIMEOUT`` and a
    *concurrent* dispatcher's ``_sweep_stale_claims`` would fail the task out from under the
    one still retrying it. Also re-syncs HEARTBEAT.md. No-op if not ``running``."""

    def _touch(record: TaskRecord) -> bool:
        if record.id != task_id or record.status != _state.Status.running:
            return False
        record.claimed_at = _clock.iso()
        return True

    TaskRepository.for_pod(project).update_each(_touch)


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


def _build(project: str, record: TaskRecord) -> TaskRef:
    task_id = record.id
    run_ids = tuple(
        str(r["id"])
        for r in list_runs(project)
        if task_id in (r.get("taskIds") or []) and r.get("id")
    )
    lead = f"{project}-{LEAD_STEP_ID}"
    return TaskRef(
        task_id=task_id,
        project=project,
        session_key=step_session_key(lead, project, task_id, LEAD_STEP_ID),
        run_ids=run_ids,
        worktree=record.worktree_dir,
    )


def _resolve_run(ref: str) -> TaskRef | None:
    run = get_run(ref)
    if run is None:
        return None
    project = str(run.get("project", ""))
    task_ids = [str(t) for t in run.get("taskIds") or []]
    tasks = {t.id: t for t in TaskRepository.for_pod(project).list()}
    found = [tasks[t] for t in task_ids if t in tasks]
    if not found:
        raise TaskRefError(f"run {ref} (pod {project}) has no task on the queue")
    if len(found) > 1:
        listing = ", ".join(f"{t.id} (pod {project})" for t in found)
        raise TaskRefError(f"run {ref} dispatched more than one task: {listing}")
    return _build(project, found[0])


def resolve_task(project: str | None, ref: str) -> TaskRef:
    """Resolve *ref* within one pod, or every pod when *project* is ``None``.

    Raises ``TaskRefError`` listing candidates (ambiguous) or what was searched (unknown)."""
    ref = ref.strip()
    if not ref:
        raise TaskRefError("no task reference given")
    if ref.startswith("run-"):
        via_run = _resolve_run(ref)
        if via_run is not None:
            if project is not None and via_run.project != project:
                raise TaskRefError(f"run {ref} belongs to pod {via_run.project}, not {project}")
            return via_run

    pods = [project] if project is not None else sorted(dispatchable_pods())
    matches: list[tuple[str, TaskRecord]] = []
    for pod in pods:
        for task in TaskRepository.for_pod(pod).list():
            if task.id.startswith(ref):
                matches.append((pod, task))

    exact = [m for m in matches if m[1].id == ref]
    if exact:
        matches = exact
    if len(matches) == 1:
        return _build(*matches[0])
    if matches:
        listing = ", ".join(f"{t.id} (pod {p})" for p, t in matches)
        raise TaskRefError(f"{ref!r} is ambiguous: {listing}")
    searched = f"pod {project}" if project is not None else f"{len(pods)} pod(s)"
    names = f" ({', '.join(pods)})" if project is None and pods else ""
    raise TaskRefError(f"no task or run matches {ref!r}; searched {searched}{names}")
