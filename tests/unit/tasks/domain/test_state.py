"""The task transition table: every pair is allowed and sets its fields, or is refused.

Generated from ``state.ALLOWED`` over every ordered pair of statuses, so a status added to the
enum is covered with no edit here. Pure: no disk, no patches.
"""

from __future__ import annotations

import itertools

import pytest

from docket.tasks.domain import state as _state

SUBJECT = "docket.tasks.domain.state"

S = _state.Status
_PAIRS = list(itertools.product(S, S))
_FACTS = {
    "now": "2026-01-01T00:00:00+00:00",
    "reason": "why",
    "failure_kind": "gate_failed",
    "blocked_reason": "resources",
    "pid": 42,
    "approval_token": "tok",
    "pending_index": 2,
    "question": {"id": "q-1"},
}


def _id(pair: tuple[S, S]) -> str:
    return f"{pair[0].value}->{pair[1].value}"


@pytest.mark.parametrize("pair", [p for p in _PAIRS if p in _state.ALLOWED], ids=_id)
def test_an_allowed_pair_succeeds_and_sets_its_fields(pair: tuple[S, S]) -> None:
    frm, to = pair
    transition = _state.decide(frm.value, to, **_FACTS)  # type: ignore[arg-type]
    assert transition.to is to
    fields = transition.fields
    if to is S.running:
        assert fields == {
            "startedAt": _FACTS["now"],
            "claimedAt": _FACTS["now"],
            "claimPid": 42,
        }
    elif to is S.pending:
        assert fields == {}
        assert "blockedReason" in transition.drop
    else:
        assert fields["reason"] == "why"
        assert "claimPid" in transition.drop
    if to is S.waiting_input:
        assert fields["question"] == {"id": "q-1"}
    if to is S.waiting_approval:
        assert (fields["approvalToken"], fields["pendingApprovalIndex"]) == ("tok", 2)
    if to is S.blocked:
        assert fields["blockedReason"] == "resources"
    if to in {_state.Status.done, _state.Status.failed, _state.Status.cancelled}:
        assert fields["completedAt"] == _FACTS["now"]
        assert fields["failureKind"] == "gate_failed"
        assert "taskGrants" in transition.drop
    if frm is S.waiting_approval and to is not S.waiting_approval:
        assert {"approvalToken", "pendingApprovalIndex"} <= set(transition.drop)
    if frm is S.waiting_input and to is not S.waiting_input:
        assert "question" in transition.drop


@pytest.mark.parametrize("pair", [p for p in _PAIRS if p not in _state.ALLOWED], ids=_id)
def test_every_other_pair_raises(pair: tuple[S, S]) -> None:
    with pytest.raises(_state.IllegalTransition):
        _state.decide(pair[0].value, pair[1])


def test_the_table_is_the_settle_edges_plus_the_reopen_edges() -> None:
    reopen = {p for p in _state.ALLOWED if p[1] not in _state.SETTLE_TARGETS}
    assert reopen == {
        (S.pending, S.running),
        (S.failed, S.running),
        (S.blocked, S.pending),
        (S.failed, S.pending),
        (S.waiting_input, S.pending),
        (S.waiting_approval, S.pending),
    }
    # Nothing pulls a finished task back except a retry.
    assert not [p for p in _state.ALLOWED if p[0] is S.done and p[1] in (S.pending, S.running)]


def test_a_status_the_enum_does_not_know_can_still_be_settled() -> None:
    assert _state.decide("legacy", S.failed).to is S.failed
    with pytest.raises(_state.IllegalTransition):
        _state.decide("legacy", S.pending)


def test_a_retry_clears_the_previous_outcome_and_an_unblock_does_not() -> None:
    assert set(_state.decide("failed", S.pending, retry=True).drop) >= {
        "blockedReason",
        "failureKind",
        "reason",
        "completedAt",
    }
    assert _state.decide("blocked", S.pending).drop == ("blockedReason",)


def test_a_stale_claim_is_evidence_not_a_finished_task() -> None:
    stale = _state.decide("running", S.failed, now="t", failure_kind=_state.FailureKind.stale_claim)
    assert "completedAt" not in stale.fields
    assert "claimPid" not in stale.drop
    assert "taskGrants" not in stale.drop


def test_a_terminal_result_without_a_failure_kind_clears_a_stale_marker() -> None:
    assert "failureKind" in _state.decide("running", S.done, now="t").drop


def test_resumable_failure_kinds_are_the_two_claims_resume_may_reclaim() -> None:
    assert {"stale_claim", "dispatch_refused"} == _state.RESUMABLE_FAILURE_KINDS
