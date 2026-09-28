"""Resolve one operator answer against a task's parked ``input`` pipeline step (ADR 0016 SS8).

``answer_task`` is the one place an answer becomes real: it validates *content* against the
question's own schema (``operator_contract.validate_answer``), screens every string through the
same ``pre_input`` evaluator ``core/telegram.py``'s ``/delegate`` uses, appends the answer to the
task's durable ``answers[]``, and resumes the pipeline at the step's own ``on:`` route -- mirroring
exactly what a live routed hop does inside ``core.dispatch._run_pipeline``, since answering happens
outside any live dispatch call. ``sweep_expired_questions`` is the fail-closed-but-never-fails
counterpart: an unanswered question past its deadline blocks the task, it never fails it.
"""

from __future__ import annotations

import json as _json
from typing import Any, cast

from pydantic import ValidationError

from docket.core import dispatch as _dispatch
from docket.core import fleet as _fleet
from docket.core import orchestrator as _orch
from docket.core import pod as _pod
from docket.core import policy as _policy
from docket.core import trace as _trace
from docket.core.audit import audit_log
from docket.core.handoff import HandoffArtifact
from docket.core.operator_contract import AnswerResult, Question, validate_answer
from docket.edges import store as _store

__all__ = ["AnswerError", "AnswerRejected", "answer_task", "sweep_expired_questions"]


class AnswerError(Exception):
    """*task_id* has no live question to answer: not found, not ``waiting_input``, its parked
    question does not match the pipeline position, or *content* fails schema validation."""


class AnswerRejected(Exception):
    """An answer's *content* was screened by ``pre_input`` and blocked. Nothing is written."""

    def __init__(self, policy_id: str) -> None:
        self.policy_id = policy_id
        super().__init__(f"answer blocked by policy {policy_id!r}")


def _all_projects() -> list[str]:
    """Every project with at least one registered pod member -- the same enumeration
    ``core.inbox`` uses, copied rather than imported to avoid a cycle risk."""
    all_ids = [a.id for a in _fleet.list_agents()]
    return sorted({p for aid in all_ids if (p := _pod.pod_of(aid))})


def _resolve_route(
    on: dict[str, Any] | None,
    label: str,
    route_counts: dict[tuple[str, str], int],
    id_to_index: dict[str, int],
    step_id: str,
    pipeline_index: int,
) -> tuple[str | None, str]:
    """Resolve *label* against *on* like ``core.dispatch._route_outcome`` does for a live hop,
    minus its tracing. Returns ``(next_step, terminal)``; *terminal* is
    ``"failed"``/``"done"``/``""`` (ordinary advance)."""
    route = _dispatch._match_on_route(on, label)
    if route is None:
        return None, ""
    if isinstance(route, dict):
        target: Any = route.get("goto")
        max_cycles = route.get("max")
    else:
        target = route
        max_cycles = None
    target_str = target if isinstance(target, str) else "stop"
    if target_str == "fail":
        return None, "failed"
    if target_str == "stop":
        return None, "done"
    target_index = id_to_index.get(target_str)
    if target_index is None:
        return None, "failed"
    if target_index <= pipeline_index:
        key = (step_id, label)
        cap = max_cycles if isinstance(max_cycles, int) else 1
        if route_counts.get(key, 0) >= cap:
            return None, "failed"
    return target_str, ""


def _load_parked_question(t: dict[str, Any], task_id: str) -> Question:
    """The task's persisted ``question``, validated -- raises ``AnswerError`` when missing or
    malformed."""
    question_raw = t.get("question")
    if not isinstance(question_raw, dict):
        raise AnswerError(f"task {task_id!r} has no pending question")
    try:
        return Question.model_validate(question_raw)
    except ValidationError as exc:
        raise AnswerError(str(exc)) from exc


def _validate_and_screen(question: Question, result: AnswerResult) -> None:
    """Validate *result* against *question*'s schema, then screen every string value in its
    content through ``pre_input``. Raises ``AnswerError``/``AnswerRejected``; writes nothing."""
    try:
        validate_answer(question, result)
    except ValueError as exc:
        raise AnswerError(str(exc)) from exc
    for value in (result.content or {}).values():
        if isinstance(value, str):
            hit = _policy.policy_eval_detail("lead", "pre_input", value, trusted=False)
            if hit.action == "block":
                raise AnswerRejected(hit.policy_id)


def _append_answer(
    t: dict[str, Any],
    question: Question,
    result: AnswerResult,
    *,
    channel: str,
    actor: str,
    ts: str,
) -> None:
    """Append one entry to the task's durable ``answers[]`` and clear its ``question``."""
    answers_raw = t.get("answers")
    answers = list(answers_raw) if isinstance(answers_raw, list) else []
    answers.append(
        {
            "questionId": question.id,
            "step": question.step,
            "message": question.message,
            "action": result.action,
            "content": result.content,
            "channel": channel,
            "actor": actor,
            "answeredAt": ts,
        }
    )
    t["answers"] = answers
    t.pop("question", None)


def _locate_parked_step(
    t: dict[str, Any],
    question: Question,
    task_id: str,
    runtime_steps: tuple[Any, ...],
    id_to_index: dict[str, int],
) -> tuple[Any, int, dict[tuple[str, str], int]]:
    """The ``PlannedUnit`` the task is actually parked at, its pipeline index, and the
    ``route_counts`` rebuilt from its persisted hops -- raises ``AnswerError`` when the
    persisted position no longer matches *question*'s own step."""
    hops_raw = t.get("hops")
    prior_hops = [
        _dispatch._hop_from_record(h)
        for h in (hops_raw if isinstance(hops_raw, list) else [])
        if isinstance(h, dict)
    ]
    _prior, pipeline_index, _rework, route_counts, _pending = _dispatch._resolve_resume_state(
        runtime_steps, prior_hops
    )
    node = runtime_steps[pipeline_index] if pipeline_index < len(runtime_steps) else None
    if node is None or not isinstance(node, _orch.PlannedUnit) or node.step_id != question.step:
        raise AnswerError(f"task {task_id!r} is not parked at step {question.step!r}")
    return node, pipeline_index, route_counts


def _apply_route_outcome(
    t: dict[str, Any],
    node: Any,
    target_str: str | None,
    terminal: str,
    outcome_label: str,
    question: Question,
    ts: str,
) -> None:
    """Persist the synthetic ``role="operator"`` hop and fold *terminal* onto *t*: a
    ``"failed"``/``"done"`` target settles the task right here (no live dispatch context
    exists to do it for it); anything else reopens it ``pending``."""
    hop = _dispatch.HopResult(
        role="operator",
        member_id="operator",
        ok=True,
        output=f"answered: {question.id}",
        # `verdict` carries the outcome label ("answered"/"declined"), not a real verdict
        # marker -- `_replay_pipeline_position`'s own route_counts rebuild keys a backward/
        # self route by `hop.artifact.verdict` (see its handling of `hop.next_step`), the
        # same field a verdict gate's routed hop already relies on; without this a resumed
        # cap check would key on the wrong label.
        artifact=HandoffArtifact(summary=f"answered: {question.id}", verdict=outcome_label),
        step_id=node.step_id,
        next_step=target_str,
    )
    hops_raw = t.get("hops")
    new_hops = list(hops_raw) if isinstance(hops_raw, list) else []
    new_hops.append(_dispatch._hop_record(hop))
    t["hops"] = new_hops

    if terminal in ("failed", "done"):
        t["status"] = terminal
        target_word = "fail" if terminal == "failed" else "stop"
        t["reason"] = (
            f"step {node.step_id!r} outcome {outcome_label.upper()} routed to {target_word}"
        )
        t["completedAt"] = ts
        t["claimId"] = None
        t.pop("failureKind", None)
    else:
        t["status"] = "pending"
        t.pop("blockedReason", None)


def answer_task(
    project: str,
    task_id: str,
    action: str,
    content: dict[str, Any] | None,
    *,
    channel: str,
    actor: str,
    now: str | None = None,
) -> AnswerResult:
    """Answer *task_id*'s parked ``input`` step: validate, screen, append to ``answers[]``, and
    resume -- a terminal route settles the task right here; any other target reopens it
    ``pending`` behind a synthetic ``role="operator"`` hop the resume builder follows."""
    ts = now or _dispatch._now()
    try:
        # *action* is caller-supplied raw text (CLI/HTTP); AnswerResult's own Literal field
        # is what actually rejects anything else, at runtime, via the ValidationError below.
        result = AnswerResult(action=cast("Any", action), content=content)
    except ValidationError as exc:
        raise AnswerError(str(exc)) from exc

    path = _dispatch.pod_task_list_path(project)
    outcome: dict[str, str] = {}
    # Resolved *before* the locked read-modify-write below: it reads the pod Lead's own
    # `.docket-meta.json`, which shares a per-directory lock with the task list itself
    # (`pod_task_list_path` lives in the Lead's own workspace) -- calling it from inside
    # the closure would try to acquire that same lock a second time and deadlock. The
    # pipeline's *shape* does not change task to task, only the persisted `hops` do, and
    # those are re-read fresh, under the lock, by `_locate_parked_step` below (pure, no I/O
    # of its own).
    runtime_steps, id_to_index, _instr = _dispatch._resolve_pipeline_steps(project, None)

    def _fn(doc: dict[str, Any]) -> dict[str, Any] | None:
        tasks_raw = doc.get("tasks")
        tasks = tasks_raw if isinstance(tasks_raw, list) else []
        for t in tasks:
            if t.get("id") != task_id:
                continue
            if t.get("status") != "waiting_input":
                raise AnswerError(f"task {task_id!r} is not waiting_input")
            question = _load_parked_question(t, task_id)
            _validate_and_screen(question, result)
            _append_answer(t, question, result, channel=channel, actor=actor, ts=ts)

            node, pipeline_index, route_counts = _locate_parked_step(
                t, question, task_id, runtime_steps, id_to_index
            )
            outcome_label = "answered" if result.action == "accept" else "declined"
            target_str, terminal = _resolve_route(
                node.on, outcome_label, route_counts, id_to_index, node.step_id, pipeline_index
            )
            _apply_route_outcome(t, node, target_str, terminal, outcome_label, question, ts)

            outcome["step"] = question.step
            outcome["question_id"] = question.id
            return {"tasks": tasks}
        raise AnswerError(f"task {task_id!r} not found in pod {project!r}")

    _store.read_modify_write(path, _fn)
    _record_answer_audit_and_trace(
        project, task_id, outcome, channel=channel, actor=actor, result=result
    )
    return result


def _record_answer_audit_and_trace(
    project: str,
    task_id: str,
    outcome: dict[str, str],
    *,
    channel: str,
    actor: str,
    result: AnswerResult,
) -> None:
    """The audit line (never carries *content*) and the ``input_answered`` trace event."""
    audit_log(
        "task.answer",
        f"project={project} task={task_id} step={outcome.get('step', '')} "
        f"channel={channel} actor={actor} action={result.action}",
    )
    _trace.trace_event(
        project,
        f"agent:{project}:{task_id}",
        "lead",
        "input_answered",
        _json.dumps(
            {
                "task": task_id,
                "step": outcome.get("step", ""),
                "questionId": outcome.get("question_id", ""),
                "action": result.action,
            }
        ),
    )


def sweep_expired_questions(now: str | None = None) -> int:
    """Expire every ``waiting_input`` task past its question's ``expiresAt``: fails closed but
    never fails -- moves it to ``blocked``/``"input_expired"``, never ``failed``.
    ``retry_task``/``unblock_pod`` reopen it; returns the number of tasks expired."""
    now_dt = _dispatch._parse_iso(now or _dispatch._now())
    if now_dt is None:
        return 0
    count = 0
    for project in _all_projects():
        path = _dispatch.pod_task_list_path(project)
        expired: list[tuple[str, str]] = []

        def _fn(
            doc: dict[str, Any], _expired: list[tuple[str, str]] = expired
        ) -> dict[str, Any] | None:
            tasks_raw = doc.get("tasks")
            tasks = tasks_raw if isinstance(tasks_raw, list) else []
            changed = False
            for t in tasks:
                if t.get("status") != "waiting_input":
                    continue
                question = t.get("question")
                if not isinstance(question, dict):
                    continue
                expires_at = question.get("expiresAt")
                if not expires_at:
                    continue
                exp_dt = _dispatch._parse_iso(str(expires_at))
                if exp_dt is None or exp_dt > now_dt:
                    continue
                t["status"] = "blocked"
                t["blockedReason"] = "input_expired"
                t["reason"] = f"question {question.get('id', '')!r} expired unanswered"
                t.pop("question", None)
                _expired.append((str(t.get("id", "")), str(question.get("id", ""))))
                changed = True
            return {"tasks": tasks} if changed else None

        _store.read_modify_write(path, _fn)
        for task_id, question_id in expired:
            count += 1
            _trace.trace_event(
                project,
                f"agent:{project}:{task_id}",
                "lead",
                "input_expired",
                _json.dumps({"task": task_id, "questionId": question_id}),
            )
    return count
