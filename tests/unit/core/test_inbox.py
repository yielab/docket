"""The derived operator inbox (``core/inbox.py``) -- pure assembly over pod tasks and pending
approvals, no writes. Pins the four-section split, the A2A mapping on every item, the
approval-to-task linking rule, the `since` cursor semantics, and paused-pod inclusion.
"""

from __future__ import annotations

import pytest

from docket.cli import _pod
from docket.core import approval as _approval
from docket.core import dispatch as _dispatch
from docket.core import fleet as _fleet
from docket.core import inbox as _inbox
from docket.core import pod as _pod_mod
from docket.core.operator_contract import ApprovalView, TaskView
from docket.edges import store as _store

SUBJECT = "docket.core.inbox"

_NOW = "2026-09-28T12:00:00+00:00"


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOCKET_SERVICE_MANAGER", "none")


def _seed_task(project: str, task_id: str, **fields: object) -> None:
    path = _dispatch.pod_task_list_path(project)
    doc = _store.read_json(path)
    tasks = doc.get("tasks", []) if isinstance(doc.get("tasks"), list) else []
    tasks.append({"id": task_id, "description": f"work on {task_id}", **fields})
    _store.write_json(path, {"tasks": tasks})


class TestBuildInboxSections:
    def _seed(self) -> None:
        _pod.build_pod("alpha", ("lead", "implementer"), codebase="/src/alpha")
        _pod.build_pod("beta", ("lead", "implementer"), codebase="/src/beta")

        _seed_task("alpha", "task-pending", status="pending", created="2026-09-28T01:00:00+00:00")
        _seed_task("alpha", "task-running", status="running", created="2026-09-28T01:00:00+00:00")
        _seed_task(
            "alpha",
            "task-wa",
            status="waiting_approval",
            approvalToken="apr-linked",
            created="2026-09-28T01:00:00+00:00",
        )
        _seed_task(
            "alpha",
            "task-blocked",
            status="blocked",
            blockedReason="budget",
            created="2026-09-28T01:00:00+00:00",
        )
        _seed_task(
            "beta",
            "task-failed",
            status="failed",
            failureKind="stale_claim",
            created="2026-09-28T01:00:00+00:00",
        )
        _seed_task(
            "beta",
            "task-done",
            status="done",
            created="2026-09-28T01:00:00+00:00",
            completedAt="2026-09-28T02:00:00+00:00",
        )
        # No live path produces `waiting_input` yet (operator-loop.spec.md requirement area 7,
        # owned by a later card) -- written by hand so the inbox's classification is
        # future-proof to it today.
        _seed_task(
            "beta",
            "task-waiting-input",
            status="waiting_input",
            created="2026-09-28T01:00:00+00:00",
        )

        _approval.approval_create("alpha", "lead", "deploy alpha", context={"taskId": "task-wa"})
        _approval.approval_create(
            "beta", "implementer", "bash: rm -rf /tmp/x", context={"tool": "bash", "callId": "c1"}
        )

    def test_sections_split_exactly_as_expected(self) -> None:
        self._seed()
        view = _inbox.build_inbox(now=_NOW)

        needs_you_ids = {
            item.id if isinstance(item, TaskView) else item.token for item in view.needs_you
        }
        assert needs_you_ids == {"task-wa", "task-blocked", "task-waiting-input", _only_token()}
        assert [t.id for t in view.failed] == ["task-failed"]
        assert [t.id for t in view.done_since] == ["task-done"]
        assert [t.id for t in view.running] == ["task-running"]

    def test_linked_approval_does_not_duplicate_its_task(self) -> None:
        self._seed()
        view = _inbox.build_inbox(now=_NOW)

        approval_items = [item for item in view.needs_you if isinstance(item, ApprovalView)]
        assert len(approval_items) == 1
        assert approval_items[0].pod == "beta"
        assert approval_items[0].task_id is None

    def test_approval_a_task_holds_by_token_is_folded_even_without_task_id(self) -> None:
        """A parked approval whose record never learned its task is still the task's: the
        task carries the token as `approvalToken`, so one item, not two."""
        _pod.build_pod("gamma", ("lead", "implementer"), codebase="/src/gamma")
        token = _approval.approval_create(
            "gamma", "implementer", "bash: git push", context={"tool": "bash", "parked": True}
        )
        _seed_task(
            "gamma",
            "task-parked",
            status="waiting_approval",
            approvalToken=token,
            created="2026-09-28T01:00:00+00:00",
        )

        view = _inbox.build_inbox(now=_NOW)

        tokens = [item.token for item in view.needs_you if isinstance(item, ApprovalView)]
        assert token not in tokens
        assert [t.id for t in view.needs_you if isinstance(t, TaskView)] == ["task-parked"]

    def test_every_item_carries_its_a2a_state(self) -> None:
        self._seed()
        view = _inbox.build_inbox(now=_NOW)

        by_id = {item.id: item.a2a_state for item in view.needs_you if isinstance(item, TaskView)}
        assert by_id["task-wa"] == "INPUT_REQUIRED"
        assert by_id["task-blocked"] == "INPUT_REQUIRED"
        assert by_id["task-waiting-input"] == "INPUT_REQUIRED"
        assert view.failed[0].a2a_state == "FAILED"
        assert view.done_since[0].a2a_state == "COMPLETED"
        assert view.running[0].a2a_state == "WORKING"

    def test_a_second_call_with_the_first_calls_next_shows_no_new_done_items(self) -> None:
        self._seed()
        first = _inbox.build_inbox(now=_NOW)
        second = _inbox.build_inbox(now=_NOW, since=first.next)
        assert second.done_since == []


def _only_token() -> str:
    """The one standalone (unlinked) approval's token, read straight from disk so the test
    above does not hardcode a minted id."""
    pending = _approval.list_pending()
    (rec,) = [r for r in pending if r.get("context", {}).get("tool") == "bash"]
    return str(rec["token"])


class TestNextTimestamp:
    def test_next_is_the_maximum_task_timestamp_with_no_approvals(self) -> None:
        _pod.build_pod("solo", ("lead", "implementer"), codebase="/src/solo")
        _seed_task(
            "solo",
            "task-early",
            status="running",
            created="2026-09-28T01:00:00+00:00",
        )
        _seed_task(
            "solo",
            "task-late",
            status="done",
            created="2026-09-28T01:00:00+00:00",
            completedAt="2026-09-28T02:00:00+00:00",
        )

        view = _inbox.build_inbox(now=_NOW)

        assert view.next == "2026-09-28T02:00:00+00:00"


class TestPausedPodsAreIncluded:
    def test_a_paused_pods_tasks_still_appear(self) -> None:
        _pod.build_pod("gamma", ("lead", "implementer"), codebase="/src/gamma")
        _seed_task("gamma", "task-g1", status="blocked", blockedReason="budget")
        lead_id = _pod_mod.member_id("gamma", "lead")
        _fleet.meta_set(lead_id, "paused", True)

        view = _inbox.build_inbox(now=_NOW)

        assert any(isinstance(item, TaskView) and item.id == "task-g1" for item in view.needs_you)


class TestEmptyInbox:
    def test_no_pods_no_approvals_yields_empty_sections_and_no_next(self) -> None:
        view = _inbox.build_inbox(now=_NOW)
        assert view.needs_you == []
        assert view.failed == []
        assert view.done_since == []
        assert view.running == []
        assert view.next is None
