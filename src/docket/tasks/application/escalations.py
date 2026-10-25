"""Open the escalation record for a pause, and settle it: the two ends of one wait.

Every way a task stops for a person calls an opener here, when the pause is created. The record is
written by the store and its id appended to the task; the fields the task already carried
(``approvalToken``, ``question``) are still written from the same values and equal what ``legacy``
names. ``governance`` sits below this context, so the tool gate reaches ``approval_opened``
through its port. ``resolve`` is the one verb that settles a record; the older verbs reach it
through ``resolve_approval_token`` and ``resolve_question``. It receives an answer to a parked
question and leaves its continuation to the next claim of the task
(``hops.application.resolutions``); an approval's follow-up is done here.
"""

from __future__ import annotations

import datetime as _dt
from collections.abc import Callable, Iterable
from typing import Any, cast

from docket.governance import approval as _approval
from docket.governance import policy as _policy
from docket.governance.audit import audit_log
from docket.governance.secrets import redact as _redact
from docket.kernel import clock as _clock
from docket.kernel import escalation_events as _events
from docket.kernel.errors import InvalidInput
from docket.kernel.operator_contract import (
    Escalation,
    EscalationExpiry,
    EscalationKind,
    EscalationLevel,
    Option,
    Question,
    QuestionV11,
    Resolution,
    new_escalation_id,
    validate_content,
)
from docket.operator import pause_is_live
from docket.platform import list_escalations, read_escalation, resolve_escalation, write_escalation
from docket.tasks.application import actions as _actions
from docket.tasks.application.repository import TaskRepository
from docket.tasks.domain.resolution import (
    EscalationInvalid,
    EscalationNotFound,
    EscalationNotPending,
    EscalationRefused,
    Resolved,
)
from docket.tasks.domain.task import TaskRecord
from docket.tasks.ports import question_answers as _answers
from docket.teams import autonomy as _autonomy
from docket.teams.settings import load_pod_settings

__all__ = [
    "approval_opened",
    "approval_refused",
    "attach",
    "decided_approval",
    "decided_consult",
    "open_for_approval",
    "open_for_question",
    "resolve",
    "resolve_approval_token",
    "resolve_question",
    "waiting_for_token",
]

_DECLINE = Option(id="decline", label="Decline", description="Refuse without choosing an option.")
_APPROVE_ONCE = "approve_once"
_APPROVE_TASK = "approve_task"
_DENY = "deny"
# The elicitation vocabulary has `decline` and `cancel`; docket has one outcome, and `cancel` is
# its alias.
_CANCEL = "cancel"
_APPROVAL_KINDS: frozenset[EscalationKind] = frozenset({"approval", "gate", "check_changed"})

# The table's row for a kind: a pipeline `approval` gate is asked like a tool call.
_ROW: dict[EscalationKind, EscalationKind] = {"gate": "approval"}


def _level_of(pod: str, task_id: str) -> EscalationLevel | None:
    """The autonomy level a pause of *task_id* is decided at, or ``None`` when the pod's queue does
    not hold that task (an ad hoc run, a question outside a pod)."""
    if not task_id:
        return None
    task = TaskRepository.for_pod(pod).get(task_id)
    if task is None:
        return None
    return cast(EscalationLevel, _autonomy.effective_level(pod, task.autonomy))


def _expiry(kind: EscalationKind, level: EscalationLevel | None) -> EscalationExpiry:
    """What the table says becomes of an unanswered *kind* at *level* (``L3`` when none is known)."""
    return cast(EscalationExpiry, _autonomy.policy_for(_ROW.get(kind, kind), level or "L3")[1])


def attach(task: TaskRecord, escalation: Escalation) -> bool:
    """Append *escalation*'s id to *task*; ``False`` when it is already listed."""
    if escalation.id in task.escalations:
        return False
    task.escalations.append(escalation.id)
    return True


def _persist(escalation: Escalation) -> Escalation:
    """Write *escalation* and list it on its task when the pod's queue holds that task."""
    stored = write_escalation(escalation)
    if stored.task:
        repository = TaskRepository.for_pod(stored.pod)
        if repository.get(stored.task) is not None:
            repository.update(stored.task, lambda record: attach(record, stored))
    return stored


def _store(escalation: Escalation) -> Escalation:
    """Persist *escalation*, which a person is asked to settle, and trace that it was asked."""
    stored = _persist(escalation)
    _events.emit(_events.ASKED, stored)
    return stored


def _store_decided(escalation: Escalation, *, option_id: str, session_id: str = "") -> Escalation:
    """Persist *escalation*, which the pod settled itself, and trace the decision."""
    stored = _persist(escalation)
    _events.emit(_events.DECIDED, stored, option_id=option_id, session_id=session_id)
    return stored


def _approval_options(kind: EscalationKind) -> list[Option]:
    options = [Option.model_validate(o) for o in _approval.approval_options()]
    if kind == "approval":
        return options
    return [o for o in options if o.id in (_APPROVE_ONCE, _DENY)]


def open_for_approval(
    token: str,
    *,
    kind: EscalationKind,
    task_id: str,
    caused_by: str,
    step: str = "",
) -> Escalation:
    """Open the escalation of the approval record *token* (``approval``, ``gate`` or
    ``check_changed``). The prompt, role, pod and deadline are the record's own."""
    record = _approval.approval_get(token)
    pod = str(record.get("project", ""))
    level = _level_of(pod, task_id)
    return _store(
        Escalation(
            id=new_escalation_id(),
            task=task_id,
            pod=pod,
            step=step,
            role=str(record.get("role", "")),
            kind=kind,
            caused_by=caused_by,
            prompt=_redact(str(record.get("action", ""))),
            options=_approval_options(kind),
            asked_at=_clock.iso(),
            expires_at=record.get("expiresAt"),
            on_expiry=_expiry(kind, level),
            level=level,
            legacy={"token": token},
        )
    )


def approval_opened(token: str, *, task_id: str, caused_by: str) -> None:
    """The tool gate created approval *token* for a call: open its ``approval`` escalation."""
    open_for_approval(token, kind="approval", task_id=task_id, caused_by=caused_by)


def _question_expiry(question: Question) -> str | None:
    """The deadline the lifecycle will stamp on a question that has none: the pod's input expiry."""
    if question.expires_at:
        return question.expires_at
    hours = load_pod_settings(question.pod).input_expiry_hours
    return (_clock.now() + _dt.timedelta(hours=hours)).isoformat()


def open_for_question(
    question: Question,
    *,
    kind: EscalationKind,
    role: str,
    caused_by: str,
    token: str = "",
) -> Escalation:
    """Open the escalation of a parked question (``consult`` or ``input``); a consult offers its
    options then ``decline``, an input step ``decline`` and the schema. *token* names the approval
    record a consult waiting in the turn blocks on: the pause then expires like an approval."""
    v11 = question if isinstance(question, QuestionV11) else None
    legacy: dict[str, Any] = {"questionId": question.id}
    expires_at = _question_expiry(question)
    level = _level_of(question.pod, question.task_id)
    if token:
        legacy["token"] = token
        expires_at = _approval.approval_get(token).get("expiresAt")
    return _store(
        Escalation(
            id=new_escalation_id(),
            task=question.task_id,
            pod=question.pod,
            step=question.step,
            role=role,
            kind=kind,
            caused_by=caused_by,
            prompt=_redact(question.message),
            options=[*(v11.options if v11 else []), _DECLINE],
            recommendation=v11.recommendation if v11 else None,
            requested_schema=dict(question.requested_schema),
            asked_at=_clock.iso(),
            expires_at=expires_at,
            on_expiry="deny" if token else _expiry(kind, level),
            level=level,
            legacy=legacy,
        )
    )


def decided_consult(
    question: QuestionV11, *, role: str, option_id: str, session_id: str = ""
) -> Escalation:
    """Store, as ``decided`` and listed on its task, the pause where the pod applied the model's
    recommendation, trace ``escalation_decided`` and return the record. The pause never parks."""
    level = _level_of(question.pod, question.task_id)
    decided = Escalation(
        id=new_escalation_id(),
        task=question.task_id,
        pod=question.pod,
        step=question.step,
        role=role,
        kind="consult",
        caused_by=question.step,
        prompt=_redact(question.message),
        options=list(question.options),
        recommendation=question.recommendation,
        asked_at=question.created_at,
        on_expiry=_expiry("consult", level),
        policy="recommendation",
        level=level,
        state="decided",
        resolution=Resolution(option_id=option_id, by="policy", channel="policy", at=_clock.iso()),
        legacy={"questionId": question.id},
    )
    return _store_decided(decided, option_id=option_id, session_id=session_id)


def decided_approval(
    *, pod: str, role: str, task_id: str, caused_by: str, prompt: str, step: str = ""
) -> Escalation:
    """Store, as ``decided`` and listed on its task, the approval the level denied because nobody
    is asked, trace ``escalation_decided`` and return the record. No approval record exists."""
    level = _level_of(pod, task_id)
    at = _clock.iso()
    denied = Escalation(
        id=new_escalation_id(),
        task=task_id,
        pod=pod,
        step=step,
        role=role,
        kind="approval",
        caused_by=caused_by,
        prompt=_redact(prompt),
        options=_approval_options("approval"),
        asked_at=at,
        on_expiry=_expiry("approval", level),
        policy="deny",
        level=level,
        state="decided",
        resolution=Resolution(option_id=_DENY, by="policy", channel="policy", at=at),
    )
    return _store_decided(denied, option_id=_DENY)


def approval_refused(*, project: str, role: str, task_id: str, caused_by: str, prompt: str) -> None:
    """The tool gate refused a call for want of anyone to ask: store the decision when the autonomy
    table made it (an explicit ``approvalMode: refuse`` of the pod is not the table's)."""
    level = _level_of(project, task_id)
    if level is None or not _autonomy.table_denies_approval(project, level):
        return
    decided_approval(pod=project, role=role, task_id=task_id, caused_by=caused_by, prompt=prompt)


def _screen(project: str, texts: Iterable[Any]) -> None:
    """Run every string of *texts* through *project*'s ``pre_input`` policy as untrusted input."""
    for text in texts:
        if not isinstance(text, str):
            continue
        hit = _policy.policy_eval_detail("lead", "pre_input", text, trusted=False, project=project)
        if hit.action == "block":
            raise EscalationRefused(hit.policy_id)


def _chosen_option(escalation: Escalation, option_id: str | None) -> str | None:
    """The option *option_id* names, ``cancel`` read as ``decline``; ``None`` for an answer that
    names none, which only a question offering nothing but ``decline`` can take."""
    offered = [o.id for o in escalation.options]
    choice = _DECLINE.id if option_id == _CANCEL else option_id or None
    if choice is None:
        if escalation.kind in _APPROVAL_KINDS or any(o != _DECLINE.id for o in offered):
            raise EscalationInvalid(f"an option is required; choose one of: {', '.join(offered)}")
        return None
    if choice not in offered:
        raise EscalationInvalid(
            f"option {choice!r} is not offered; choose one of: {', '.join(offered)}"
        )
    return choice


def _reason_of(content: dict[str, Any] | None) -> str:
    """The reason an approval's content carries; it carries nothing else."""
    extra = sorted(set(content or {}) - {"reason"})
    if extra:
        raise EscalationInvalid(f"an approval takes only a reason, not {extra}")
    reason = (content or {}).get("reason", "")
    if not isinstance(reason, str):
        raise EscalationInvalid("reason must be a string")
    return reason


def _checked_content(
    escalation: Escalation, option: str | None, content: dict[str, Any] | None
) -> dict[str, Any] | None:
    """*content* as *escalation* accepts it: a decline carries none, an approval a reason, a
    question what its schema allows."""
    if option == _DECLINE.id:
        return None
    if escalation.kind in _APPROVAL_KINDS:
        _reason_of(content)
        return dict(content) if content else None
    try:
        validate_content(escalation.requested_schema or {}, content)
    except InvalidInput as exc:
        raise EscalationInvalid(exc.message) from exc
    return dict(content) if content else None


def _apply_approval(
    token: str, option: str, *, project: str, channel: str, actor: str, reason: str
) -> str:
    """Grant or deny the approval *token* and settle the task it gated, as `docket task approve`
    and `deny` always did; returns the note a refused task-wide grant produces."""
    _screen(project, [reason])
    # An actor is recorded with the decision only when a reason comes with it.
    acting = actor if reason else ""
    decision = "denied" if option == _DENY else "granted"
    try:
        if option == _DENY:
            _approval.approval_deny(token, channel=channel, actor=acting, reason=reason)
        else:
            if option == _APPROVE_TASK:
                _approval.approval_set_option(token, option)
            _approval.approval_grant(token, channel=channel, actor=acting, reason=reason)
    except _approval.ApprovalNoop as exc:
        # The pause may have ended while the task kept waiting; free it before saying so.
        _actions.resolve_waiting_approval(token, decision)
        raise EscalationNotPending(exc.message, already_so=True) from exc
    except _approval.ApprovalConflict as exc:
        raise EscalationNotPending(str(exc)) from exc
    except _approval.ApprovalError as exc:
        raise EscalationNotFound(str(exc)) from exc
    _, note = _actions.resolve_waiting_approval_detail(
        token, decision, channel=channel, actor=acting, reason=reason
    )
    return note


def _receive_question(
    project: str,
    task_id: str,
    option: str | None,
    content: dict[str, Any] | None,
    *,
    channel: str,
    actor: str,
) -> None:
    """Receive the answer *option* and *content* to the question *task_id* is parked on."""
    if option == _DECLINE.id:
        _answers.record_answer(project, task_id, "decline", None, channel=channel, actor=actor)
        return
    body = dict(content or {})
    if option:
        body["optionId"] = option
    _answers.record_answer(project, task_id, "accept", body or None, channel=channel, actor=actor)


def _wake_waiting_turn(
    token: str, option: str | None, content: dict[str, Any] | None, *, project: str, channel: str
) -> None:
    """A consult waiting in the turn blocks on the approval record *token*: grant it for an option,
    deny it for a decline, and the turn reads the answer from the resolved escalation."""
    _screen(project, (content or {}).values())
    try:
        if option == _DECLINE.id:
            _approval.approval_deny(token, channel=channel)
        else:
            _approval.approval_grant(token, channel=channel)
    except _approval.ApprovalNoop as exc:
        raise EscalationNotPending(exc.message, already_so=True) from exc
    except _approval.ApprovalConflict as exc:
        raise EscalationNotPending(str(exc)) from exc
    except _approval.ApprovalError as exc:
        raise EscalationNotFound(str(exc)) from exc


def resolve(
    escalation_id: str,
    option_id: str | None,
    content: dict[str, Any] | None = None,
    *,
    by: str,
    channel: str,
) -> Resolved:
    """Settle the pending *escalation_id* with *option_id* and *content*: check, receive the answer,
    then record, audit and trace it; a refusal leaves the record pending. An approval is followed
    up here, a parked question by the next claim of its task (``applied_at`` stays unset)."""
    escalation = read_escalation(escalation_id)
    if escalation is None:
        raise EscalationNotFound(f"no escalation {escalation_id!r}")
    if not pause_is_live(escalation):
        raise EscalationNotPending(f"escalation {escalation.id} is not pending")
    option = _chosen_option(escalation, option_id)
    body = _checked_content(escalation, option, content)
    note = ""
    applied = True
    if escalation.kind in _APPROVAL_KINDS:
        note = _apply_approval(
            str(escalation.legacy.get("token", "")),
            option or _APPROVE_ONCE,
            project=escalation.pod,
            channel=channel,
            actor=by,
            reason=_reason_of(body),
        )
    elif escalation.legacy.get("token"):
        _wake_waiting_turn(
            str(escalation.legacy["token"]), option, body, project=escalation.pod, channel=channel
        )
    else:
        _receive_question(escalation.pod, escalation.task, option, body, channel=channel, actor=by)
        applied = False
    at = _clock.iso()
    resolution = Resolution(
        option_id=option,
        content=body,
        by=by or "unknown",
        channel=channel,
        at=at,
        applied_at=at if applied else None,
    )
    settled = resolve_escalation(escalation.id, resolution) or escalation.model_copy(
        update={"state": "resolved", "resolution": resolution}
    )
    audit_log(
        "escalation.resolve",
        f"escalation={settled.id} kind={settled.kind} pod={settled.pod} task={settled.task} "
        f"option={option or '-'} channel={channel} actor={resolution.by}",
    )
    _events.emit(_events.RESOLVED, settled, channel=channel, option_id=option or "")
    return Resolved(settled, note)


def _live_record(matches: Callable[[Escalation], bool]) -> Escalation | None:
    """The newest pending escalation that *matches* and whose pause still waits, else ``None``."""
    return next(
        (e for e in reversed(list_escalations(state="pending")) if matches(e) and pause_is_live(e)),
        None,
    )


def waiting_for_token(token: str) -> bool:
    """Whether a pending escalation names the approval record *token* and its pause still waits."""
    return _live_record(lambda e: e.legacy.get("token") == token) is not None


def resolve_approval_token(
    token: str, option_id: str, *, channel: str, actor: str, reason: str = ""
) -> str:
    """Resolve the escalation of approval *token* (a consult waiting in the turn is found by its
    token too), returning the note a refused task-wide grant produces. An approval with no live
    record takes the direct path: same follow-up, same messages."""
    record = _live_record(lambda e: e.legacy.get("token") == token)
    if record is None:
        try:
            project = str(_approval.approval_get(token).get("project", ""))
        except _approval.ApprovalError as exc:
            raise EscalationNotFound(str(exc)) from exc
        return _apply_approval(
            token, option_id, project=project, channel=channel, actor=actor, reason=reason
        )
    # A gate or a changed check offers no task-wide grant; asking for one is a plain grant.
    if option_id == _APPROVE_TASK and _APPROVE_TASK not in (o.id for o in record.options):
        option_id = _APPROVE_ONCE
    reasoned = {"reason": reason} if reason else None
    return resolve(record.id, option_id, reasoned, by=actor, channel=channel).note


def resolve_question(
    project: str,
    task_id: str,
    action: str,
    content: dict[str, Any] | None,
    *,
    channel: str,
    actor: str,
) -> None:
    """The older answer verbs: resolve the escalation of the question *task_id* is parked on.
    *action* is ``accept``, ``decline`` or ``cancel``; an ``optionId`` in *content* names the
    option. A question with no live record is answered directly."""
    record = _live_record(
        lambda e: (e.pod, e.task) == (project, task_id) and e.kind in ("consult", "input")
    )
    if record is None:
        _answers.answer_question(project, task_id, action, content, channel=channel, actor=actor)
        return
    if action in ("decline", _CANCEL):
        resolve(record.id, _DECLINE.id, None, by=actor, channel=channel)
        return
    if action != "accept":
        raise EscalationInvalid(f"action must be accept, decline or cancel, not {action!r}")
    body = dict(content or {})
    option = body.pop("optionId", None)
    resolve(record.id, option, body, by=actor, channel=channel)
