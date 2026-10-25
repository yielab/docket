"""The derived operator inbox (``operator/inbox.py``) -- pure assembly over pod tasks and pending
approvals, no writes. Pins the four-section split, the A2A mapping on every item, the
approval-to-task linking rule, the `since` cursor semantics, and paused-pod inclusion.
"""

from __future__ import annotations

from typing import Any

from tests.support.pods import build_pod
from tests.support.tasks import task as _make_task

from docket.governance import approval as _approval
from docket.kernel.home import current_home
from docket.kernel.operator_contract import ApprovalView, TaskView
from docket.operator import inbox as _inbox
from docket.platform import store as _store
from docket.tasks.application.repository import TaskRepository
from docket.teams import fleet as _fleet
from docket.teams import pod as _pod_mod

SUBJECT = "docket.operator.inbox"

_NOW = "2026-09-28T12:00:00+00:00"


def _seed_task(project: str, task_id: str, **fields: Any) -> None:
    TaskRepository.for_pod(project).add(
        _make_task(id=task_id, description=f"work on {task_id}", **fields)
    )


class TestBuildInboxSections:
    def _seed(self) -> None:
        build_pod("alpha", ("lead", "implementer"), codebase="/src/alpha")
        build_pod("beta", ("lead", "implementer"), codebase="/src/beta")

        _seed_task("alpha", "task-pending", status="pending", created="2026-09-28T01:00:00+00:00")
        _seed_task("alpha", "task-running", status="running", created="2026-09-28T01:00:00+00:00")
        _seed_task(
            "alpha",
            "task-wa",
            status="waiting_approval",
            approval_token="apr-linked",
            created="2026-09-28T01:00:00+00:00",
        )
        _seed_task(
            "alpha",
            "task-blocked",
            status="blocked",
            blocked_reason="budget",
            created="2026-09-28T01:00:00+00:00",
        )
        _seed_task(
            "beta",
            "task-failed",
            status="failed",
            failure_kind="stale_claim",
            created="2026-09-28T01:00:00+00:00",
        )
        _seed_task(
            "beta",
            "task-done",
            status="done",
            created="2026-09-28T01:00:00+00:00",
            completed_at="2026-09-28T02:00:00+00:00",
        )
        # A consultation or an `input` step parks a task `waiting_input` on the live path; it is
        # written by hand here so this test needs no run.
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
        build_pod("gamma", ("lead", "implementer"), codebase="/src/gamma")
        token = _approval.approval_create(
            "gamma", "implementer", "bash: git push", context={"tool": "bash", "parked": True}
        )
        _seed_task(
            "gamma",
            "task-parked",
            status="waiting_approval",
            approval_token=token,
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
        build_pod("solo", ("lead", "implementer"), codebase="/src/solo")
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
            completed_at="2026-09-28T02:00:00+00:00",
        )

        view = _inbox.build_inbox(now=_NOW)

        assert view.next == "2026-09-28T02:00:00+00:00"


class TestPausedPodsAreIncluded:
    def test_a_paused_pods_tasks_still_appear(self) -> None:
        build_pod("gamma", ("lead", "implementer"), codebase="/src/gamma")
        _seed_task("gamma", "task-g1", status="blocked", blocked_reason="budget")
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


class TestPendingMemory:
    @staticmethod
    def _entries(project: str, *rows: tuple[str, str, str]) -> None:
        entries = [
            {
                "id": f"mem-{i}",
                "kind": kind,
                "path": subject,
                "note": "A fact.",
                "status": status,
                "reason": "awaits operator approval",
                "provenance": {"task": "t1", "date": "2026-10-18", "commit": ""},
            }
            for i, (kind, subject, status) in enumerate(rows)
        ]
        path = current_home().pod_memory_path(project)
        path.parent.mkdir(parents=True, exist_ok=True)
        _store.write_json(path, {"entries": entries})

    def test_only_pending_entries_of_every_pod_are_listed_with_their_pod(self) -> None:
        build_pod("alpha", ("lead", "implementer"), codebase="/src/alpha")
        build_pod("beta", ("lead", "implementer"), codebase="/src/beta")
        self._entries("alpha", ("pitfall", "a.py", "pending"), ("generated", "dist", "accepted"))
        self._entries("beta", ("convention", ".", "pending"), ("pitfall", "b.py", "refused"))

        items = _inbox.pending_memory()

        assert [(m.pod, m.id, m.kind, m.subject, m.task) for m in items] == [
            ("alpha", "mem-0", "pitfall", "a.py", "t1"),
            ("beta", "mem-0", "convention", ".", "t1"),
        ]

    def test_a_pod_without_memory_adds_nothing_and_the_view_is_unchanged(self) -> None:
        build_pod("alpha", ("lead", "implementer"), codebase="/src/alpha")

        assert _inbox.pending_memory() == []
        assert _inbox.build_inbox(now=_NOW).needs_you == []
