"""apply_to_task: the one writer of a task record's status, on in-memory records."""

from __future__ import annotations

from typing import Any

import pytest

from docket.tasks.application import transitions as _transitions
from docket.tasks.domain import state as _state

SUBJECT = "docket.tasks.application.transitions"

S = _state.Status


def _running() -> dict[str, Any]:
    return {
        "id": "task-1",
        "status": "running",
        "claimPid": 7,
        "consultAnswer": {"text": "x"},
        "taskGrants": [{"tool": "bash"}],
        "failureKind": None,
    }


def test_a_settled_result_releases_the_claim_and_delivers_the_consult_answer() -> None:
    task = _running()
    _transitions.apply_to_task(task, S.done, now="t", reason="ok", ran=True)
    assert task["status"] == "done"
    assert (task["reason"], task["completedAt"]) == ("ok", "t")
    assert not {"claimPid", "consultAnswer", "taskGrants", "failureKind"} & set(task)


def test_a_refusal_keeps_the_undelivered_consult_answer_and_the_grants() -> None:
    task = _running()
    _transitions.apply_to_task(
        task, S.failed, now="t", reason="no", failure_kind="prepare", keep_grants=True
    )
    assert task["failureKind"] == "prepare"
    assert "claimPid" not in task
    assert task["consultAnswer"] == {"text": "x"}
    assert task["taskGrants"] == [{"tool": "bash"}]


def test_a_swept_stale_claim_stamps_no_completion_and_keeps_the_pid() -> None:
    task = _running()
    _transitions.apply_to_task(
        task, S.failed, reason="stale", failure_kind=_state.FailureKind.stale_claim
    )
    assert (task["status"], task["failureKind"]) == ("failed", "stale_claim")
    assert task["claimPid"] == 7
    assert "completedAt" not in task


def test_a_parked_approval_is_resolved_back_to_pending_without_its_token() -> None:
    task = {"status": "waiting_approval", "approvalToken": "t", "pendingApprovalIndex": 1}
    _transitions.apply_to_task(task, S.pending)
    assert task == {"status": "pending"}


def test_an_illegal_move_raises_and_leaves_the_record_untouched() -> None:
    task = {"status": "done", "reason": "ok"}
    with pytest.raises(_state.IllegalTransition):
        _transitions.apply_to_task(task, S.running, now="t", pid=1)
    assert task == {"status": "done", "reason": "ok"}
