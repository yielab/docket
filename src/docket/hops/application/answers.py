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
from collections.abc import Callable
from typing import Any, cast

from pydantic import ValidationError

from docket.governance import escalation_expiry as _escalation_expiry
from docket.governance import policy as _policy
from docket.governance.audit import audit_log
from docket.hops.application import executor as _executor
from docket.hops.application import resolutions as _resolutions
from docket.hops.application import steps as _steps
from docket.kernel import clock as _clock
from docket.kernel.errors import Conflict, Refused
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
from docket.tasks.application import consult as _consult
from docket.tasks.application import corrections as _corrections
from docket.tasks.application import transitions as _transitions
from docket.tasks.application.repository import TaskRepository
from docket.tasks.domain import state as _state
from docket.tasks.domain import task as _task
from docket.tasks.domain.parts import Answer, ConsultAnswer
from docket.tasks.domain.resolution import (
    EscalationInvalid,
    EscalationNotFound,
    EscalationNotPending,
    EscalationRefused,
)
from docket.teams import fleet as _fleet
from docket.teams import pod as _pod

__all__ = [
    "AnswerError",
    "AnswerNotFound",
    "AnswerRejected",
    "AnswerStale",
    "QuestionAnswers",
    "answer_task",
    "record_answer",
    "sweep_expired_questions",
]


class AnswerError(Conflict):
    """*task_id* has no live question to answer: not found, not ``waiting_input``, its parked
    question does not match the pipeline position, or *content* fails schema validation."""


class AnswerNotFound(AnswerError):
    """The task is not in the pod's queue."""


class AnswerStale(AnswerError):
    """The task is in the queue but its question is gone: not ``waiting_input``, no question
    left, or parked at another step."""


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


def _load_parked_question(t: _task.TaskRecord, task_id: str) -> Question:
    """The task's persisted ``question`` -- raises ``AnswerError`` when it has none."""
    if t.question is None:
        raise AnswerStale(f"task {task_id!r} has no pending question")
    return t.question


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
    t: _task.TaskRecord,
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
    t.answers.append(
        Answer(
            question_id=question.id,
            step=question.step,
            message=question.message,
            action=result.action,
            content=result.content,
            channel=channel,
            actor=actor,
            answered_at=ts,
            # The question is cleared below; the metrics read its kind and age from here.
            kind=getattr(question, "kind", "clarification"),
            created_at=question.created_at,
            option_id=option_id or None,
        )
    )
    t.question = None


def _receive_consult(
    project: str,
    t: _task.TaskRecord,
    question: QuestionV11,
    result: AnswerResult,
    *,
    channel: str,
    actor: str,
    ts: str,
) -> tuple[AnswerResultV11, dict[str, Any]]:
    """Validate a parked ``consult``'s answer (its ``optionId`` rides in *content*), screen it and
    append it to ``answers[]``. Returns the answer and the content left once ``optionId`` is
    taken out."""
    try:
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
    return answer, body


def _answer_consult(
    project: str,
    t: _task.TaskRecord,
    question: QuestionV11,
    result: AnswerResult,
    *,
    channel: str,
    actor: str,
    ts: str,
) -> QuestionV11:
    """Resolve a parked ``consult`` in one call: receive the answer, set the note the same role's
    step re-runs with and reopen the task ``pending``."""
    answer, body = _receive_consult(
        project, t, question, result, channel=channel, actor=actor, ts=ts
    )
    t.consult_answer = ConsultAnswer(
        step=question.step,
        question_id=question.id,
        text=_consult.answer_text(question.id, question.options, answer, body),
    )
    _transitions.apply_to_task(t, _state.Status.pending)
    return question


def _locate_parked_step(
    t: _task.TaskRecord,
    question: Question,
    task_id: str,
    runtime_steps: tuple[Any, ...],
    id_to_index: dict[str, int],
) -> tuple[Any, int, dict[tuple[str, str], int]]:
    """The ``PlannedUnit`` the task is actually parked at, its pipeline index, and the
    ``route_counts`` rebuilt from its persisted hops -- raises ``AnswerError`` when the
    persisted position no longer matches *question*'s own step."""
    _prior, pipeline_index, _rework, route_counts, _pending = _executor._resolve_resume_state(
        runtime_steps, t.hops
    )
    node = runtime_steps[pipeline_index] if pipeline_index < len(runtime_steps) else None
    if node is None or not isinstance(node, _orch.PlannedUnit) or node.step_id != question.step:
        raise AnswerStale(f"task {task_id!r} is not parked at step {question.step!r}")
    return node, pipeline_index, route_counts


def _apply_route_outcome(
    t: _task.TaskRecord,
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
    hop = _resolutions.routed_hop(node.step_id, question.id, outcome_label, target_str)
    t.hops.append(hop)

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
    """The pipeline *task_id* was dispatched through: the one it names itself or the caller's
    file it kept, else ``None`` (the pod's own). One that no longer resolves is an
    ``AnswerError``."""
    record = TaskRepository.for_pod(project).get(task_id)
    if record is None or not (record.pipeline or record.pipeline_spec):
        return None
    try:
        spec, _source = _steps._task_pipeline(
            project, record, _steps.effective_pipeline(project, None)
        )
    except _task.TaskRunRefusal as exc:
        raise AnswerError(str(exc)) from exc
    return spec


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
    result = _answer_result(action, content)

    outcome: dict[str, str] = {}
    # Resolved *before* the locked read-modify-write below: it reads the pod Lead's own
    # `.docket-meta.json`, which shares a per-directory lock with the task list itself
    # (`pod_task_list_path` lives in the Lead's own workspace) -- calling it from inside
    # the closure would try to acquire that same lock a second time and deadlock. The
    # pipeline's *shape* does not change task to task, only the persisted `hops` do, and
    # those are re-read fresh, under the lock, by `_locate_parked_step` below (pure, no I/O
    # of its own).
    runtime_steps, id_to_index, _instr = _executor.resolve_pipeline_steps(
        project, _parked_task_pipeline(project, task_id)
    )

    def _fn(t: _task.TaskRecord) -> None:
        if t.status != _state.Status.waiting_input:
            raise AnswerStale(f"task {task_id!r} is not waiting_input")
        if isinstance(t.question, QuestionV11) and t.question_is_consultation:
            consulted = _answer_consult(
                project, t, t.question, result, channel=channel, actor=actor, ts=ts
            )
            outcome["step"] = consulted.step
            outcome["question_id"] = consulted.id
            return
        question = _load_parked_question(t, task_id)
        _validate_and_screen(project, question, result)
        _append_answer(t, question, result, channel=channel, actor=actor, ts=ts)

        node, pipeline_index, route_counts = _locate_parked_step(
            t, question, task_id, runtime_steps, id_to_index
        )
        outcome_label = "answered" if result.action == "accept" else "declined"
        target_str, terminal = _resolutions.resolve_route(
            node.on, outcome_label, route_counts, id_to_index, node.step_id, pipeline_index
        )
        _apply_route_outcome(t, node, target_str, terminal, outcome_label, question, ts)

        outcome["step"] = question.step
        outcome["question_id"] = question.id

    if TaskRepository.for_pod(project).update(task_id, _fn) is None:
        raise AnswerNotFound(f"task {task_id!r} not found in pod {project!r}")
    _finish_answer(project, task_id, outcome, channel=channel, actor=actor, result=result)
    return result


def record_answer(
    project: str,
    task_id: str,
    action: str,
    content: dict[str, Any] | None,
    *,
    channel: str,
    actor: str,
    now: str | None = None,
) -> AnswerResult:
    """Receive the answer to *task_id*'s parked question: validate, screen, append to ``answers[]``
    and reopen the task ``pending``. No pipeline is resolved and no hop appended: the claim applies
    the route or the consult note (``hops.application.resolutions``)."""
    ts = now or _clock.iso()
    result = _answer_result(action, content)
    outcome: dict[str, str] = {}

    def _fn(t: _task.TaskRecord) -> None:
        if t.status != _state.Status.waiting_input:
            raise AnswerStale(f"task {task_id!r} is not waiting_input")
        if isinstance(t.question, QuestionV11) and t.question_is_consultation:
            question: Question = t.question
            _receive_consult(project, t, t.question, result, channel=channel, actor=actor, ts=ts)
        else:
            question = _load_parked_question(t, task_id)
            _validate_and_screen(project, question, result)
            _append_answer(t, question, result, channel=channel, actor=actor, ts=ts)
        _transitions.apply_to_task(t, _state.Status.pending)
        outcome["step"] = question.step
        outcome["question_id"] = question.id

    if TaskRepository.for_pod(project).update(task_id, _fn) is None:
        raise AnswerNotFound(f"task {task_id!r} not found in pod {project!r}")
    _finish_answer(project, task_id, outcome, channel=channel, actor=actor, result=result)
    return result


def _answer_result(action: str, content: dict[str, Any] | None) -> AnswerResult:
    """*action* and *content* as an ``AnswerResult``, or ``AnswerError``."""
    try:
        # *action* is caller-supplied raw text (CLI/HTTP); AnswerResult's own Literal field
        # is what actually rejects anything else, at runtime, via the ValidationError below.
        return AnswerResult(action=cast("Any", action), content=content)
    except ValidationError as exc:
        raise AnswerError(str(exc)) from exc


def _finish_answer(
    project: str,
    task_id: str,
    outcome: dict[str, str],
    *,
    channel: str,
    actor: str,
    result: AnswerResult,
) -> None:
    """The audit line and trace event of a received answer, and the correction a decline records."""
    _record_answer_audit_and_trace(
        project, task_id, outcome, channel=channel, actor=actor, result=result
    )
    if result.action == "decline":
        _corrections.record(
            project,
            "declined_answer",
            task_id=task_id,
            role="operator",
            text="(declined)",
            source="answer",
        )


class QuestionAnswers:
    """``tasks.ports.QuestionAnswers`` over ``record_answer`` (a question with an escalation record)
    and ``answer_task`` (one without), their refusals told in the vocabulary of a resolve."""

    def answer_question(
        self,
        project: str,
        task_id: str,
        action: str,
        content: dict[str, Any] | None,
        *,
        channel: str,
        actor: str,
    ) -> None:
        self._run(answer_task, project, task_id, action, content, channel=channel, actor=actor)

    def record_answer(
        self,
        project: str,
        task_id: str,
        action: str,
        content: dict[str, Any] | None,
        *,
        channel: str,
        actor: str,
    ) -> None:
        self._run(record_answer, project, task_id, action, content, channel=channel, actor=actor)

    @staticmethod
    def _run(
        answer: Callable[..., AnswerResult],
        project: str,
        task_id: str,
        action: str,
        content: dict[str, Any] | None,
        *,
        channel: str,
        actor: str,
    ) -> None:
        try:
            answer(project, task_id, action, content, channel=channel, actor=actor)
        except AnswerRejected as exc:
            raise EscalationRefused(exc.policy_id) from exc
        except AnswerNotFound as exc:
            raise EscalationNotFound(str(exc)) from exc
        except AnswerStale as exc:
            raise EscalationNotPending(str(exc)) from exc
        except AnswerError as exc:
            raise EscalationInvalid(str(exc)) from exc


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
        expired: list[tuple[str, str]] = []

        def _expire(t: _task.TaskRecord, _expired: list[tuple[str, str]] = expired) -> bool:
            question = t.question
            if t.status != _state.Status.waiting_input or question is None:
                return False
            if not question.expires_at:
                return False
            exp_dt = _clock.parse_iso(question.expires_at)
            if exp_dt is None or exp_dt > now_dt:
                return False
            _transitions.apply_to_task(
                t,
                _state.Status.blocked,
                reason=f"question {question.id!r} expired unanswered",
                blocked_reason="input_expired",
            )
            _expired.append((t.id, question.id))
            return True

        TaskRepository.for_pod(project).update_each(_expire)
        for task_id, question_id in expired:
            count += 1
            _escalation_expiry.expire("questionId", question_id)
            _trace.trace_event(
                project,
                f"agent:{project}:{task_id}",
                "lead",
                "input_expired",
                _json.dumps({"task": task_id, "questionId": question_id}),
            )
    return count
