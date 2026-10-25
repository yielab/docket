"""apply_to_task: the one writer of a task record's status."""

from __future__ import annotations

import itertools

import pytest

from docket.tasks.application import transitions as _transitions
from docket.tasks.domain import state as _state
from docket.tasks.domain import task as _task

SUBJECT = "docket.tasks.application.transitions"

S = _state.Status


_Q = {
    "id": "q-1",
    "taskId": "task-1",
    "pod": "demo",
    "step": "lead",
    "message": "which?",
    "requestedSchema": {"type": "object", "properties": {"a": {"type": "string"}}},
    "createdAt": "2026-10-24T00:00:00+00:00",
    "kind": "decision",
}
_GRANT = {
    "tool": "bash",
    "argsDigest": "d",
    "token": "t",
    "role": "lead",
    "grantedAt": "2026-10-24T00:00:00+00:00",
    "actor": "me",
    "channel": "cli",
}
_FACTS = {
    "now": "2026-10-24T00:00:01+00:00",
    "reason": "why",
    "failure_kind": "gate_failed",
    "blocked_reason": "resources",
    "pid": 42,
    "approval_token": "tok",
    "pending_index": 2,
    "question": _Q,
}


def _loaded(status: S) -> _task.TaskRecord:
    """A record carrying every field a transition can drop."""
    return _task.TaskRecord.model_validate(
        {
            "description": "x",
            "status": status.value,
            "reason": "old",
            "startedAt": "2026-10-24T00:00:00+00:00",
            "completedAt": "2026-10-24T00:00:00+00:00",
            "claimedAt": "2026-10-24T00:00:00+00:00",
            "claimPid": 7,
            "failureKind": "x",
            "blockedReason": "r",
            "approvalToken": "old",
            "pendingApprovalIndex": 0,
            "question": _Q,
            "consultAnswer": {"step": "s", "questionId": "q-1", "text": "go"},
            "taskGrants": [_GRANT],
        }
    )


@pytest.mark.parametrize(
    "pair", [p for p in itertools.product(S, S) if p in _state.ALLOWED], ids=str
)
def test_a_record_takes_every_allowed_move_and_loses_what_the_move_drops(
    pair: tuple[S, S],
) -> None:
    frm, to = pair
    record = _loaded(frm)
    transition = _transitions.apply_to_task(record, to, **_FACTS)
    dumped = record.model_dump(by_alias=True, mode="json")
    assert record.status is to
    for name, value in transition.fields.items():
        if name != "question":
            assert getattr(record, name) == value
    for name in set(transition.drop) - set(transition.fields):
        assert getattr(record, name) == _transitions._default(name)
        assert dumped.get(_task.TaskRecord.model_fields[name].alias or name) in (None, "")


def test_a_dropped_field_is_none_after_and_absent_from_the_dump() -> None:
    record = _loaded(S.running)
    _transitions.apply_to_task(record, S.done, now="t", reason="ok", ran=True)
    assert record.claim_pid is None and record.consult_answer is None
    assert record.failure_kind is None
    dumped = record.model_dump(by_alias=True, mode="json")
    assert not {"claimPid", "consultAnswer", "failureKind"} & set(dumped)
    assert (dumped["reason"], dumped["completedAt"], dumped["status"]) == ("ok", "t", "done")


def test_a_retry_resets_the_outcome_to_the_defaults() -> None:
    record = _loaded(S.failed)
    _transitions.apply_to_task(record, S.pending, retry=True)
    assert (record.reason, record.completed_at, record.failure_kind) == ("", None, None)


def test_a_record_refuses_an_illegal_move_and_stays_as_it_was() -> None:
    record = _loaded(S.done)
    before = record.model_dump(by_alias=True, mode="json")
    with pytest.raises(_state.IllegalTransition):
        _transitions.apply_to_task(record, S.running, now="t", pid=1)
    assert record.model_dump(by_alias=True, mode="json") == before


def test_a_parked_question_is_stored_as_the_typed_question() -> None:
    record = _task.TaskRecord(description="x", status=S.running)
    _transitions.apply_to_task(record, S.waiting_input, question=_Q)
    assert record.question is not None
    assert record.question_is_consultation is True
    assert record.model_dump(by_alias=True, mode="json")["question"]["id"] == "q-1"
