"""``approved_ready``: a pending task a person already approved, read from what they resolved.

Nothing is kept on the task for it: a call approved ahead or granted while the task was parked is
in the approval store, and a granted gate is a resolved escalation the claim has not applied yet.
Real pods, tasks, approval records and escalations.
"""

from __future__ import annotations

import pytest
from tests.support import escalations as _support_escalations
from tests.support.escalations import approval_escalation, parked_approval
from tests.support.tasks import pregrant, stored_task, update_task

from docket.platform import mark_escalation_applied
from docket.tasks.application import escalations as _esc
from docket.tasks.application.actions import approved_ready
from docket.tasks.application.queue import enqueue_task_once

SUBJECT = "docket.tasks.application.actions"

PROJECT = "demo"

demo_pod = _support_escalations.demo_pod
pytestmark = pytest.mark.usefixtures("demo_pod")


def test_a_plain_pending_task_is_not_approved_ready() -> None:
    task = enqueue_task_once(PROJECT, "ship it", channel="cli")[0]

    assert approved_ready(task) is False


def test_a_call_approved_ahead_of_the_task_makes_it_approved_ready() -> None:
    task = enqueue_task_once(PROJECT, "ship it", channel="cli")[0]

    pregrant(PROJECT, task.id)

    assert approved_ready(stored_task(PROJECT, task.id)) is True


def test_a_task_that_is_running_is_not_approved_ready() -> None:
    task = enqueue_task_once(PROJECT, "ship it", channel="cli")[0]
    pregrant(PROJECT, task.id)
    update_task(PROJECT, task.id, status="running")

    assert approved_ready(stored_task(PROJECT, task.id)) is False


def test_a_granted_gate_makes_the_task_approved_ready_until_a_claim_applies_it() -> None:
    escalation = approval_escalation("gate")
    _esc.resolve(escalation.id, "approve_once", None, by="alice", channel="cli")

    assert approved_ready(stored_task(PROJECT, escalation.task)) is True

    mark_escalation_applied(escalation.id, "2026-10-25T10:00:00+00:00")

    assert approved_ready(stored_task(PROJECT, escalation.task)) is False


def test_a_parked_call_that_was_granted_is_approved_ready_by_its_unspent_grant() -> None:
    escalation = parked_approval()
    _esc.resolve(escalation.id, "approve_once", None, by="alice", channel="cli")

    assert approved_ready(stored_task(PROJECT, escalation.task)) is True


def test_a_denied_gate_leaves_nothing_to_continue_from() -> None:
    escalation = approval_escalation("gate")
    _esc.resolve(escalation.id, "deny", None, by="alice", channel="cli")

    assert approved_ready(stored_task(PROJECT, escalation.task)) is False
