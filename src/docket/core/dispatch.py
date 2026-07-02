"""Pod pipeline dispatch — drives queued tasks through the lead → implementer → reviewer → tester pipeline.

One real agent turn per present role (via the ACL's ``agent_run``), with a trace event and budget
check per hop. Dispatch is always within a single pod — no code path sends one pod's work to
another pod's agents. Invoked only from an explicit trigger or the opt-in ``serve --dispatch`` loop.
"""

from __future__ import annotations

import datetime as _dt
import json as _json
import re as _re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import docket.config as _cfg
from docket.core import pod as _pod
from docket.core import trace as _trace
from docket.core import utils as _utils
from docket.edges import store as _store
from docket.edges.adapters import openclaw as _oc
from docket.edges.adapters import system as _sys

# Only roles the pod actually has run — lean pod (lead + implementer) = 2 hops; full pod = 4.
PIPELINE_ORDER: tuple[str, ...] = ("lead", "implementer", "reviewer", "tester")

# Injectable runner for tests (matches the ACL ``agent_run`` signature).
Runner = Callable[[str, str, str, int], _oc.AgentRunResult]

DEFAULT_TIMEOUT = 300

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


def pod_task_list_path(project: str) -> Path:
    """The pod's task queue lives in its Lead's workspace.

    One queue per pod (keyed by the Lead), so pods never share a task list — part
    of the no-cross-pod guarantee.
    """
    lead_id = _pod.member_id(project, "lead")
    return _cfg.workspace_dir(lead_id) / "TASK_LIST.json"


def read_tasks(project: str) -> list[dict[str, Any]]:
    """Return the pod's task list ([] if the queue file is absent)."""
    raw = _store.read_json(pod_task_list_path(project))
    tasks = raw.get("tasks") if isinstance(raw, dict) else None
    return tasks if isinstance(tasks, list) else []


def write_tasks(project: str, tasks: list[dict[str, Any]]) -> None:
    _store.write_json(pod_task_list_path(project), {"tasks": tasks})


def enqueue_task(project: str, description: str, priority: str = "normal") -> dict[str, Any]:
    """Append a pending task to the pod's queue and return it.

    Raises DispatchError if the project has no Lead workspace (no pod yet).
    """
    if not pod_task_list_path(project).parent.is_dir():
        raise DispatchError(f"no pod for '{project}' (run: docket add {project})")
    import time as _time

    task: dict[str, Any] = {
        "id": f"task-{int(_time.time() * 1000)}",
        "description": description,
        "priority": priority if priority in ("high", "normal", "low") else "normal",
        "status": "pending",
        "created": _now(),
        "startedAt": None,
        "completedAt": None,
        "source": "operator",
        "hops": [],
    }
    tasks = read_tasks(project)
    tasks.append(task)
    write_tasks(project, tasks)
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


def _hop_message(task: dict[str, Any], role: str, prior: list[HopResult]) -> str:
    """Build the message handed to one role, threading prior hops' output."""
    desc = str(task.get("description", "")).strip()
    if role == "lead":
        return (
            f"You are the pod Lead. Decompose this task into a concrete plan for "
            f"the Implementer (you never edit code yourself):\n\n{desc}"
        )
    lines = [f"Task: {desc}", ""]
    for h in prior:
        if h.output:
            lines.append(f"--- {h.role} output ---\n{h.output}\n")
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
    return "\n".join(lines)


def dispatch_task(
    project: str,
    task: dict[str, Any],
    *,
    runner: Runner | None = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> TaskResult:
    """Drive one task through the pod pipeline, hop by hop.

    Budget is checked before EACH hop (every hop is a real costed turn). A failed
    hop stops the pipeline (later roles only matter if earlier ones succeed). All
    dispatch targets belong to this project's pod — asserted per hop.
    """
    run = runner or _oc.agent_run
    task_id = str(task.get("id", "task"))
    session_id = f"agent:{project}:{task_id}"
    pipeline = pod_pipeline(project)
    cap = pod_budget(project)

    _trace.trace_event(
        project,
        session_id,
        "lead",
        "session_start",
        _json.dumps({"source": "dispatch", "task": task_id}),
    )

    result = TaskResult(task_id=task_id, status="done")
    prior: list[HopResult] = []

    for role, member_id in pipeline:
        # No-cross-pod guarantee: never dispatch to an id outside this pod.
        if _pod.pod_of(member_id) != project:
            raise DispatchError(
                f"refusing cross-pod dispatch: '{member_id}' is not in pod '{project}'"
            )

        # Budget gate BEFORE the hop — the spend is recorded by the daemon, so we
        # check the accumulated pod cost against the cap and stop if we're over.
        if cap > 0.0:
            spent = pod_recorded_cost(project)
            if spent >= cap:
                _trace.trace_event(
                    project,
                    session_id,
                    role,
                    "budget_exceeded",
                    _json.dumps({"spent": round(spent, 6), "cap": round(cap, 6), "role": role}),
                )
                result.status = "blocked"
                result.reason = f"pod budget reached (${spent:.2f} ≥ ${cap:.2f}) before {role}"
                break

        message = _hop_message(task, role, prior)
        _trace.trace_event(
            project,
            session_id,
            role,
            "tool_call",
            _json.dumps({"hop": role, "agent": member_id}),
        )
        run_res = run(member_id, session_id, message, timeout)
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
                impl_codebase = str(_oc.meta_get(member_id, "codebase", "") or "")
                cwd = impl_codebase or str(_cfg.PROJECTS_DIR / member_id)
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
    """Fold a TaskResult back onto the stored task dict."""
    task["status"] = res.status
    task["reason"] = res.reason
    task["hops"] = [
        {
            "role": h.role,
            "member": h.member_id,
            "ok": h.ok,
            "costUsd": round(h.cost_usd, 6),
            "error": h.error,
        }
        for h in res.hops
    ]
    task["costUsd"] = res.cost_usd
    if res.status == "blocked":
        task["status"] = "pending"  # left queued; retried when budget allows
        task["blockedReason"] = res.reason
    else:
        task["completedAt"] = _now()


def dispatch_pod(
    project: str,
    *,
    runner: Runner | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    max_tasks: int | None = None,
) -> list[TaskResult]:
    """Dispatch a pod's pending tasks through the pipeline (highest priority first).

    Persists each task's status + per-hop record back to the queue. A "blocked"
    (budget) task is left pending for a later run. Returns one TaskResult per task
    attempted. Raises DispatchError if the pod has no Lead.
    """
    pod_pipeline(project)  # validates pod/lead up front
    tasks = read_tasks(project)
    pri = {"high": 0, "normal": 1, "low": 2}
    pending_idx = [i for i, t in enumerate(tasks) if t.get("status") == "pending"]
    pending_idx.sort(key=lambda i: pri.get(str(tasks[i].get("priority", "normal")), 1))
    if max_tasks is not None:
        pending_idx = pending_idx[:max_tasks]

    results: list[TaskResult] = []
    for i in pending_idx:
        task = tasks[i]
        task["startedAt"] = _now()
        res = dispatch_task(project, task, runner=runner, timeout=timeout)
        _apply_result(task, res)
        results.append(res)
        write_tasks(project, tasks)  # persist after each task (crash-safe)
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
