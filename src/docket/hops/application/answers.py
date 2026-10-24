"""Resolve one operator answer against a task's parked ``input`` pipeline step (ADR 0016 SS8).

``answer_task`` is the one place an answer becomes real: it validates *content* against the
question's own schema (``operator_contract.validate_answer``), screens every string through the
same ``pre_input`` evaluator ``interfaces/telegram/bot.py``'s ``/delegate`` uses, appends the answer to the
task's durable ``answers[]``, and resumes the pipeline at the step's own ``on:`` route -- mirroring
exactly what a live routed hop does inside ``hops.application.executor._run_pipeline``, since answering happens
outside any live dispatch call. ``sweep_expired_questions`` is the fail-closed-but-never-fails
counterpart: an unanswered question past its deadline blocks the task, it never fails it.
"""

from __future__ import annotations

import json as _json
from typing import Any, cast

from pydantic import ValidationError

from docket.governance import policy as _policy
from docket.governance.audit import audit_log
from docket.hops.application import executor as _executor
from docket.hops.application import steps as _steps
from docket.hops.gates import post_hop as _post_hop
from docket.kernel import clock as _clock
from docket.kernel.errors import Conflict, Refused
from docket.kernel.handoff import HandoffArtifact
from docket.kernel.operator_contract import (
    AnswerResult,
    AnswerResultV11,
    Question,
    QuestionV11,
    validate_answer,
    validate_answer_v11,
)
from docket.observability import trace as _trace
from docket.pipeline.domain import plan as _orch
from docket.platform import read_modify_write
from docket.tasks.application import consult as _consult
from docket.tasks.application import corrections as _corrections
from docket.tasks.application import queue as _queue
from docket.tasks.application import record as _record
from docket.tasks.application import transitions as _transitions
from docket.tasks.domain import state as _state
from docket.tasks.domain import task as _task
from docket.teams import fleet as _fleet
from docket.teams import pod as _pod
from docket.teams import settings as _settings

__all__ = ["AnswerError", "AnswerRejected", "answer_task", "sweep_expired_questions"]


class AnswerError(Conflict):
    """*task_id* has no live question to answer: not found, not ``waiting_input``, its parked
    question does not match the pipeline position, or *content* fails schema validation."""


class AnswerRejected(Refused):
    """An answer's *content* was screened by ``pre_input`` and blocked. Nothing is written."""

    def __init__(self, policy_id: str) -> None:
        self.policy_id = policy_id
        super().__init__(f"answer blocked by policy {policy_id!r}")


def _all_projects() -> list[str]:
    """Every project with at least one registered pod member -- the same enumeration
    ``operator.inbox`` uses, copied rather than imported to avoid a cycle risk."""
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
    """Resolve *label* against *on* like ``hops.application.executor._route_outcome`` does for a live hop,
    minus its tracing. Returns ``(next_step, terminal)``; *terminal* is
    ``"failed"``/``"done"``/``""`` (ordinary advance)."""
    route = _post_hop._match_on_route(on, label)
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


def _validate_and_screen(project: str, question: Question, result: AnswerResult) -> None:
    """Validate *result* against *question*'s schema, then screen every string value in its
    content through ``pre_input`` with *project*'s own policies. Raises ``AnswerError``/
    ``AnswerRejected``; writes nothing."""
    try:
        validate_answer(question, result)
    except ValueError as exc:
        raise AnswerError(str(exc)) from exc
    _screen_content(project, result)


def _screen_content(project: str, result: AnswerResult) -> None:
    """Screen every string in *result*'s content through ``pre_input`` with *project*'s own
    policies (``AnswerRejected``)."""
    for value in (result.content or {}).values():
        if isinstance(value, str):
            hit = _policy.policy_eval_detail(
                "lead", "pre_input", value, trusted=False, project=project
            )
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
    option_id: str | None = None,
) -> None:
    """Append one entry to the task's durable ``answers[]`` and clear its ``question``. The entry
    keeps the question's ``kind`` and ``createdAt``, which nothing else retains once it is cleared."""
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
            # The question is cleared below; the metrics read its kind and age from here.
            "kind": getattr(question, "kind", "clarification"),
            "createdAt": question.created_at,
            **({"optionId": option_id} if option_id else {}),
        }
    )
    t["answers"] = answers
    t.pop("question", None)


def _answer_consult(
    project: str,
    t: dict[str, Any],
    question_raw: dict[str, Any],
    result: AnswerResult,
    *,
    channel: str,
    actor: str,
    ts: str,
) -> QuestionV11:
    """Resolve a parked ``consult``: validate its ``optionId`` (in *content*), record the answer
    and reopen the task ``pending`` so the same role's step re-runs with the answer."""
    try:
        question = QuestionV11.model_validate(question_raw)
        body = dict(result.content or {})
        option_id = body.pop("optionId", None)
        answer = AnswerResultV11.model_validate(
            {"action": result.action, "content": body or None, "optionId": option_id}
        )
        validate_answer_v11(question, answer)
    except (ValidationError, ValueError) as exc:
        raise AnswerError(str(exc)) from exc
    _screen_content(project, answer)
    _append_answer(t, question, answer, channel=channel, actor=actor, ts=ts, option_id=option_id)
    t["consultAnswer"] = {
        "step": question.step,
        "questionId": question.id,
        "text": _consult.answer_text(question, answer, body),
    }
    _transitions.apply_to_task(t, _state.Status.pending)
    return question


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
        _record.hop_from_record(h)
        for h in (hops_raw if isinstance(hops_raw, list) else [])
        if isinstance(h, dict)
    ]
    _prior, pipeline_index, _rework, route_counts, _pending = _executor._resolve_resume_state(
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
    hop = _task.HopResult(
        role="operator",
        member_id="operator",
        ok=True,
        output=f"answered: {question.id}",
        # `verdict` carries the outcome label ("answered"/"declined"), not a real verdict
        # marker -- `replay_pipeline_position`'s own route_counts rebuild keys a backward/
        # self route by `hop.artifact.verdict` (see its handling of `hop.next_step`), the
        # same field a verdict gate's routed hop already relies on; without this a resumed
        # cap check would key on the wrong label.
        artifact=HandoffArtifact(summary=f"answered: {question.id}", verdict=outcome_label),
        step_id=node.step_id,
        next_step=target_str,
    )
    hops_raw = t.get("hops")
    new_hops = list(hops_raw) if isinstance(hops_raw, list) else []
    new_hops.append(_record.hop_record(hop))
    t["hops"] = new_hops

    if terminal in ("failed", "done"):
        target_word = "fail" if terminal == "failed" else "stop"
        _transitions.apply_to_task(
            t,
            _state.Status(terminal),
            now=ts,
            reason=f"step {node.step_id!r} outcome {outcome_label.upper()} routed to {target_word}",
            keep_grants=True,
        )
    else:
        _transitions.apply_to_task(t, _state.Status.pending)


def _parked_task_pipeline(project: str, task_id: str) -> Any:
    """The pipeline *task_id* was dispatched through: the one it names itself, else ``None``
    (the pod's own). A named pipeline that no longer resolves is an ``AnswerError``."""
    for t in _queue.read_tasks(project):
        if t.get("id") != task_id or not t.get("pipeline"):
            continue
        try:
            spec, _source = _steps._task_pipeline(
                project, t, _steps.effective_pipeline(project, None)
            )
        except _task.TaskRunRefusal as exc:
            raise AnswerError(str(exc)) from exc
        return spec
    return None


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
    ts = now or _clock.iso()
    try:
        # *action* is caller-supplied raw text (CLI/HTTP); AnswerResult's own Literal field
        # is what actually rejects anything else, at runtime, via the ValidationError below.
        result = AnswerResult(action=cast("Any", action), content=content)
    except ValidationError as exc:
        raise AnswerError(str(exc)) from exc

    path = _settings.pod_task_list_path(project)
    outcome: dict[str, str] = {}
    # Resolved *before* the locked read-modify-write below: it reads the pod Lead's own
    # `.docket-meta.json`, which shares a per-directory lock with the task list itself
    # (`pod_task_list_path` lives in the Lead's own workspace) -- calling it from inside
    # the closure would try to acquire that same lock a second time and deadlock. The
    # pipeline's *shape* does not change task to task, only the persisted `hops` do, and
    # those are re-read fresh, under the lock, by `_locate_parked_step` below (pure, no I/O
    # of its own).
    runtime_steps, id_to_index, _instr = _executor._resolve_pipeline_steps(
        project, _parked_task_pipeline(project, task_id)
    )

    def _fn(doc: dict[str, Any]) -> dict[str, Any] | None:
        tasks_raw = doc.get("tasks")
        tasks = tasks_raw if isinstance(tasks_raw, list) else []
        for t in tasks:
            if t.get("id") != task_id:
                continue
            if t.get("status") != "waiting_input":
                raise AnswerError(f"task {task_id!r} is not waiting_input")
            raw = t.get("question")
            if isinstance(raw, dict) and raw.get("kind") in ("clarification", "decision"):
                consulted = _answer_consult(
                    project, t, raw, result, channel=channel, actor=actor, ts=ts
                )
                outcome["step"] = consulted.step
                outcome["question_id"] = consulted.id
                return {"tasks": tasks}
            question = _load_parked_question(t, task_id)
            _validate_and_screen(project, question, result)
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

    read_modify_write(path, _fn)
    _record_answer_audit_and_trace(
        project, task_id, outcome, channel=channel, actor=actor, result=result
    )

    # Record declined answers to the corrections ledger
    if result.action == "decline":
        _corrections.record(
            project,
            "declined_answer",
            task_id=task_id,
            role="operator",
            text="(declined)",
            source="answer",
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
    now_dt = _clock.parse_iso(now or _clock.iso())
    if now_dt is None:
        return 0
    count = 0
    for project in _all_projects():
        path = _settings.pod_task_list_path(project)
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
                exp_dt = _clock.parse_iso(str(expires_at))
                if exp_dt is None or exp_dt > now_dt:
                    continue
                _transitions.apply_to_task(
                    t,
                    _state.Status.blocked,
                    reason=f"question {question.get('id', '')!r} expired unanswered",
                    blocked_reason="input_expired",
                )
                _expired.append((str(t.get("id", "")), str(question.get("id", ""))))
                changed = True
            return {"tasks": tasks} if changed else None

        read_modify_write(path, _fn)
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
