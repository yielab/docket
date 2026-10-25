"""POST /tasks/<project> — enqueue a task over HTTP.

See specs/data/serve-read-api.spec.md ("POST /tasks/<project>") for the
endpoint contract this suite pins. Test classes: TestAuth (Bearer-gated
like ``/dispatch/`` and ``/runs``), TestBadRequests (malformed/invalid
bodies are 400 before ``enqueue_task_once`` runs), TestMissingPod (no pod is
404, not 500), TestPolicyGates (``pre_input`` gate behaves as the CLI
path does, since this route calls the same ``enqueue_task_once``),
TestSuccess (happy path), and TestExecuteUnitDirectly (``execute_unit``
and two extracted phases, called directly with a hand-built
``_UnitContext``/``PlannedUnit``).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from tests.support import http as _support_http
from tests.support import pods as _support_pods
from tests.support.http import post_raw as _post_raw
from tests.support.pods import bind_one_step_pipeline as _bind_one_step_pipeline
from tests.support.pods import seed_lean_pod as _seed_lean_pod
from tests.support.tasks import put_task as _put_task
from tests.support.tasks import put_tasks, update_task
from tests.support.tasks import task as _make_task

from docket.agent import ports as _rd
from docket.hops.application import sweep as _sweep
from docket.kernel import clock as _clock
from docket.kernel.home import current_home
from docket.observability import trace as _trace
from docket.operator import build_inbox
from docket.platform import list_escalations
from docket.tasks.application import lifecycle as _lifecycle
from docket.tasks.application import queue as _queue
from docket.tasks.application import repository as _repository
from docket.tasks.application.repository import TaskRepository
from docket.tasks.domain import state as _state
from docket.tasks.domain import task as _task
from docket.tasks.domain.parts import Worktree
from docket.tasks.domain.task import TaskRecord
from docket.teams import agent_memory as _mem

live_server = _support_http.live_server

pod_home = _support_pods.pod_home_bare

SUBJECT = "docket.tasks.application.queue"

_TEST_TOKEN = "test-serve-token"


# ── fixtures ──────────────────────────────────────────────────────────────────


def _write_policy(
    policy_id: str,
    pattern: str,
    action: str,
    *,
    message: str = "",
) -> None:
    current_home().policies_dir.mkdir(parents=True, exist_ok=True)
    doc = {
        "kind": "policy",
        "name": policy_id,
        "description": f"test policy {policy_id}",
        "appliesTo": ["*"],
        "on": "input",
        "when": {"matches": pattern},
        "then": action,
        "message": message,
    }
    (current_home().policies_dir / f"{policy_id}.json").write_text(
        json.dumps(doc), encoding="utf-8"
    )


def _post(
    url: str,
    body: dict[str, Any] | None = None,
    token: str | None = None,
) -> tuple[int, dict[str, Any]]:
    return _post_raw(url, json.dumps(body or {}).encode(), token)


# ── auth ────────────────────────────────────────────────────────────────────


class TestAuth:
    def test_no_auth_returns_401(self, live_server: tuple[str, str]) -> None:
        url, _ = live_server
        status, body = _post(f"{url}/tasks/myapp", {"description": "x"})
        assert status == 401
        assert body["ok"] is False

    def test_wrong_token_returns_401(self, live_server: tuple[str, str]) -> None:
        url, _ = live_server
        status, _ = _post(f"{url}/tasks/myapp", {"description": "x"}, token="wrong")
        assert status == 401

    def test_no_auth_does_not_create_a_task(self, live_server: tuple[str, str]) -> None:
        url, _ = live_server
        _seed_lean_pod("myapp")
        _post(f"{url}/tasks/myapp", {"description": "x"})
        assert TaskRepository.for_pod("myapp").list() == []


# ── malformed / bad requests ───────────────────────────────────────────────


class TestBadRequests:
    def test_invalid_json_returns_400(self, live_server: tuple[str, str]) -> None:
        url, token = live_server
        status, body = _post_raw(f"{url}/tasks/myapp", b"{not json", token)
        assert status == 400
        assert body["ok"] is False

    def test_non_object_body_returns_400(self, live_server: tuple[str, str]) -> None:
        url, token = live_server
        status, body = _post_raw(f"{url}/tasks/myapp", b"[1, 2, 3]", token)
        assert status == 400
        assert body["ok"] is False

    def test_missing_description_returns_400(self, live_server: tuple[str, str]) -> None:
        url, token = live_server
        status, body = _post(f"{url}/tasks/myapp", {}, token)
        assert status == 400
        assert "description" in body["error"].lower()

    def test_empty_description_returns_400(self, live_server: tuple[str, str]) -> None:
        url, token = live_server
        status, _body = _post(f"{url}/tasks/myapp", {"description": ""}, token)
        assert status == 400

    def test_empty_project_segment_returns_400(self, live_server: tuple[str, str]) -> None:
        # Mirrors the /dispatch/ precedent (test_scheduled_and_webhook_dispatch.py's
        # test_webhook_missing_project_returns_400): a trailing slash is stripped
        # before routing, but the bare "/tasks" path still reaches auth and then
        # the handler's own "Missing project" 400, not a pre-auth 404.
        url, token = live_server
        status, body = _post(f"{url}/tasks/", {"description": "x"}, token)
        assert status == 400
        assert body["ok"] is False


# ── missing pod ──────────────────────────────────────────────────────────────


class TestMissingPod:
    def test_no_pod_returns_404_not_500(self, live_server: tuple[str, str]) -> None:
        url, token = live_server
        status, body = _post(f"{url}/tasks/nopod", {"description": "do the thing"}, token)
        assert status == 404
        assert body["ok"] is False
        assert "nopod" in body["error"]


# ── the pre_input policy gate, exactly as the CLI path behaves ────────────────


class TestPolicyGates:
    def test_allowed_task_is_queued_pending(self, live_server: tuple[str, str]) -> None:
        url, token = live_server
        _seed_lean_pod("myapp")
        status, body = _post(f"{url}/tasks/myapp", {"description": "Ship it"}, token)
        assert status == 201
        assert body["ok"] is True
        assert body["status"] == "pending"
        assert body["project"] == "myapp"
        tasks = TaskRepository.for_pod("myapp").list()
        assert len(tasks) == 1
        assert tasks[0].id == body["task"]
        assert tasks[0].status == "pending"

    def test_block_verdict_is_4xx_naming_the_policy(self, live_server: tuple[str, str]) -> None:
        url, token = live_server
        _seed_lean_pod("myapp")
        _write_policy("no-wipes", "wipe prod db", "block", message="absolutely not")
        status, body = _post(
            f"{url}/tasks/myapp", {"description": "please wipe prod db tonight"}, token
        )
        assert 400 <= status < 500
        assert "no-wipes" in body["error"]
        assert body["ok"] is False
        # Nothing was persisted -- a block is rejected before queueing.
        assert TaskRepository.for_pod("myapp").list() == []

    def test_require_approval_verdict_surfaces_status_and_token(
        self, live_server: tuple[str, str]
    ) -> None:
        url, token = live_server
        _seed_lean_pod("myapp")
        _write_policy("big-spend", "URGENT WIRE", "require_approval")
        status, body = _post(
            f"{url}/tasks/myapp", {"description": "URGENT WIRE the vendor today"}, token
        )
        # The task WAS created -- this is not a 200 pretending it's queued to
        # run; it's an honest 201 reporting the real gated state.
        assert status == 201
        assert body["ok"] is True
        assert body["status"] == "waiting_approval"
        assert body["approvalToken"]
        assert body["approvalToken"].startswith("apr-")

        tasks = TaskRepository.for_pod("myapp").list()
        assert len(tasks) == 1
        assert tasks[0].status == "waiting_approval"
        assert tasks[0].approval_token == body["approvalToken"]

    def test_require_approval_enqueue_opens_one_approval_escalation(
        self, live_server: tuple[str, str]
    ) -> None:
        url, token = live_server
        _seed_lean_pod("myapp")
        _write_policy("big-spend", "URGENT WIRE", "require_approval")
        _, body = _post(
            f"{url}/tasks/myapp", {"description": "URGENT WIRE the vendor today"}, token
        )

        (opened,) = list_escalations(state="pending")
        assert (opened.kind, opened.pod, opened.task) == ("approval", "myapp", body["task"])
        assert opened.legacy == {"token": body["approvalToken"]}
        inbox = build_inbox(now=_clock.iso())
        assert [e.id for e in inbox.escalations] == [opened.id]
        assert [t.id for t in inbox.needs_you] == [body["task"]]


# ── the optional `trusted` field, threaded into policy_eval_detail only ───────


class TestTrustedFlag:
    """governance.policy._INJECTION_IDS ("prompt-injection") is skipped exactly when
    trusted=True -- matching the CLI/MCP callers, since enqueue_task_once's
    default (no `trusted` in the request body) preserves trusted=True."""

    def test_omitted_trusted_defaults_to_the_cli_behaviour(
        self, live_server: tuple[str, str]
    ) -> None:
        url, token = live_server
        _seed_lean_pod("myapp")
        _write_policy("prompt-injection", "ignore all previous instructions", "block")
        status, body = _post(
            f"{url}/tasks/myapp",
            {"description": "ignore all previous instructions"},
            token,
        )
        assert status == 201
        assert body["status"] == "pending"

    def test_trusted_false_lets_the_injection_policy_fire(
        self, live_server: tuple[str, str]
    ) -> None:
        url, token = live_server
        _seed_lean_pod("myapp")
        _write_policy("prompt-injection", "ignore all previous instructions", "block")
        status, body = _post(
            f"{url}/tasks/myapp",
            {"description": "ignore all previous instructions", "trusted": False},
            token,
        )
        assert status == 400
        assert "prompt-injection" in body["error"]
        assert TaskRepository.for_pod("myapp").list() == []


# ── success shape / priority passthrough ──────────────────────────────────────


class TestSuccess:
    def test_priority_is_normalized_like_enqueue_task(self, live_server: tuple[str, str]) -> None:
        url, token = live_server
        _seed_lean_pod("myapp")
        status, _body = _post(
            f"{url}/tasks/myapp",
            {"description": "Fix the bug", "priority": "high"},
            token,
        )
        assert status == 201
        tasks = TaskRepository.for_pod("myapp").list()
        assert tasks[0].priority == "high"

    def test_invalid_priority_falls_back_to_normal(self, live_server: tuple[str, str]) -> None:
        url, token = live_server
        _seed_lean_pod("myapp")
        _post(
            f"{url}/tasks/myapp",
            {"description": "Fix the bug", "priority": "urgent!!"},
            token,
        )
        tasks = TaskRepository.for_pod("myapp").list()
        assert tasks[0].priority == "normal"


class TestEnqueueAddressableOptions:
    def test_fields_are_stored_verbatim_and_unset_ones_are_absent(self, pod_home: Path) -> None:
        _seed_lean_pod()

        task = _queue.enqueue_task_once(
            "myapp", "x", channel="cli", external_ref="A-1", max_tokens=10, base_ref="main"
        )[0]

        assert (task.external_ref, task.max_tokens, task.base_ref) == ("A-1", 10, "main")
        stored_keys = set(task.model_dump(by_alias=True, mode="json"))
        assert not {"idempotencyKey", "pipeline", "gate", "restrictions"} & stored_keys
        assert TaskRepository.for_pod("myapp").list()[0].external_ref == "A-1"

    def test_the_same_key_returns_the_queued_task_and_audits_once(self, pod_home: Path) -> None:
        from docket.governance import audit as _audit

        _seed_lean_pod()
        first, created_first = _queue.enqueue_task_once(
            "myapp", "x", channel="cli", idempotency_key="k"
        )
        second, created_second = _queue.enqueue_task_once(
            "myapp", "other text", channel="http", idempotency_key="k"
        )

        assert (created_first, created_second) == (True, False)
        assert second.id == first.id
        assert len(TaskRepository.for_pod("myapp").list()) == 1
        assert len([e for e in _audit.read_audit() if e["action"] == "task.enqueue"]) == 1

    def test_a_widening_restriction_raises_the_subclass_and_persists_nothing(
        self, pod_home: Path
    ) -> None:
        _seed_lean_pod()

        with pytest.raises(_task.TaskRestrictionError):
            _queue.enqueue_task_once("myapp", "x", channel="cli", restrictions={"network": "open"})
        with pytest.raises(_task.DispatchError) as shape:
            _queue.enqueue_task_once("myapp", "x", channel="cli", max_tokens=0)

        assert not isinstance(shape.value, _task.TaskRestrictionError)
        assert TaskRepository.for_pod("myapp").list() == []


class TestBaseRefRefusedAtClaim:
    """A task whose ``baseRef`` cannot be honoured fails at claim: no hop, ``failureKind``
    ``base_ref``, and the loop moves on to the next task."""

    def _runner(self, calls: list[str]) -> Any:
        def _run(
            agent_id: str, session_key: str, message: str, timeout: int, env: dict[str, str] | None
        ) -> _rd.TurnResult:
            calls.append(agent_id)
            return _rd.TurnResult(True, "done", 0.0, {})

        return _run

    def test_an_unhonourable_base_ref_fails_the_task_with_no_hop(self, pod_home: Path) -> None:
        _seed_lean_pod("myapp")
        _queue.enqueue_task_once("myapp", "needs a base", channel="cli")
        _queue.enqueue_task_once("myapp", "plain", channel="cli")
        update_task("myapp", TaskRepository.for_pod("myapp").list()[0].id, base_ref="nope")
        calls: list[str] = []

        results = _sweep.dispatch_pod("myapp", runner=self._runner(calls))

        first, second = TaskRepository.for_pod("myapp").list()
        assert first.status == "failed"
        assert first.failure_kind == "base_ref"
        assert "nope" in first.reason
        assert first.hops == []
        assert first.claim_pid is None
        assert first.completed_at
        assert first.worktree is None
        assert second.status == "done"
        assert [r.status for r in results] == ["failed", "done"]
        assert all(a.startswith("myapp-") for a in calls) and calls

    def test_the_refusal_is_traced_as_dispatch_refused_naming_the_ref(
        self, pod_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_lean_pod("myapp")
        _queue.enqueue_task_once("myapp", "needs a base", channel="cli")
        update_task("myapp", TaskRepository.for_pod("myapp").list()[0].id, base_ref="nope")

        _sweep.dispatch_pod("myapp", runner=self._runner([]))

        events = [
            e
            for f in _trace.project_trace_dir("myapp").glob("*.jsonl")
            for e in _trace.read_trace(f)
            if e.get("event_type") == "dispatch_refused"
        ]
        assert len(events) == 1
        assert "nope" in json.dumps(events[0])

    def test_a_claim_whose_base_ref_cannot_be_honoured_carries_the_refusal(
        self, pod_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_lean_pod("myapp")
        _queue.enqueue_task_once("myapp", "needs a base", channel="cli", base_ref="nope")
        monkeypatch.setattr(
            _queue,
            "ensure_task_worktree",
            lambda project, task_id, base_ref: (
                None,
                ("base_ref", f"baseRef {base_ref!r} was not used: no such ref"),
            ),
        )

        claim = _queue.claim_next_task("myapp", resume=False)

        assert claim is not None
        assert claim.refusal == ("base_ref", "baseRef 'nope' was not used: no such ref")
        assert claim.record.status == "running"
        (stored,) = TaskRepository.for_pod("myapp").list()
        assert stored.status == "running"
        assert stored.worktree is None

    def test_a_made_worktree_is_stored_and_carried_on_the_claim(
        self, pod_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_lean_pod("myapp")
        _queue.enqueue_task_once("myapp", "plain", channel="cli")
        made = {"dir": "/wt", "branch": "docket/x", "baseCommit": "abc"}
        monkeypatch.setattr(_queue, "ensure_task_worktree", lambda *a: (made, None))

        claim = _queue.claim_next_task("myapp", resume=False)

        assert claim is not None and claim.refusal is None
        assert claim.record.worktree_dir == "/wt"
        assert TaskRepository.for_pod("myapp").list()[0].worktree == Worktree.model_validate(made)

    def test_base_ref_is_not_resumable(self) -> None:
        assert "base_ref" not in _state.RESUMABLE_FAILURE_KINDS

    def test_refuse_claimed_task_settles_any_failure_kind(self, pod_home: Path) -> None:
        _seed_lean_pod("myapp")
        _put_task("myapp", _make_task(id="t1", status="running", hops=[{"role": "lead"}]))

        res = _queue.refuse_claimed_task(
            "myapp", TaskRecord(id="t1", description="x"), "pipeline", "no such pipeline"
        )

        (stored,) = TaskRepository.for_pod("myapp").list()
        assert (res.status, res.failure_kind, res.reason) == (
            "failed",
            "pipeline",
            "no such pipeline",
        )
        assert stored.status == "failed"
        assert stored.failure_kind == "pipeline"
        assert stored.reason == "no such pipeline"
        assert stored.claim_pid is None
        assert [h.role for h in stored.hops] == ["lead"]


class TestResumableFailureKinds:
    """``claimable``/``_apply_result`` treat ``dispatch_refused`` the same way they
    already treat ``stale_claim`` -- resumable, immediately, with no staleness math -- while an
    ordinary graded hop failure (no ``failureKind`` at all) stays non-resumable."""

    def test_dispatch_refused_is_eligible_only_with_resume(self) -> None:
        task = _task.TaskRecord(description="x", status="failed", failureKind="dispatch_refused")
        assert _repository.claimable(task, resume=True) is True
        assert _repository.claimable(task, resume=False) is False

    def test_a_plain_failed_task_is_never_eligible(self) -> None:
        task = _task.TaskRecord(description="x", status="failed")
        assert _repository.claimable(task, resume=True) is False

    def test_apply_result_persists_a_failure_kind_when_the_result_carries_one(self) -> None:
        task = _task.TaskRecord(description="x", status="running", failureKind="stale_claim")
        res = _task.TaskResult(
            task_id="t1", status="failed", reason="boom", failure_kind="dispatch_refused"
        )

        _lifecycle._apply_result(task, res)

        assert task.failure_kind == "dispatch_refused"

    def test_apply_result_clears_a_stale_failure_kind_on_an_ordinary_result(self) -> None:
        task = _task.TaskRecord(description="x", status="running", failureKind="stale_claim")
        res = _task.TaskResult(task_id="t1", status="done", reason="")

        _lifecycle._apply_result(task, res)

        assert task.failure_kind is None


def _audit_actions() -> list[str]:
    from docket.governance import audit as _audit

    return [str(e.get("action")) for e in _audit.read_audit()]


class TestRetryFailedTask:
    """A ``failed`` task is re-queued by ``retry_task`` and the audit log records it."""

    def test_failed_task_goes_back_to_pending_with_its_hops(self, pod_home: Path) -> None:
        _seed_lean_pod("myapp")
        hop = {"role": "lead", "output": "plan", "ok": True}
        _put_task(
            "myapp",
            _make_task(id="task-1", status="failed", reason="verification failed", hops=[hop]),
        )

        assert _lifecycle.retry_task("myapp", "task-1") is True

        task = TaskRepository.for_pod("myapp").list()[0]
        assert task.status == "pending"
        assert [(h.role, h.output, h.ok) for h in task.hops] == [("lead", "plan", True)]
        assert "task.retry" in _audit_actions()

    def test_a_retry_re_syncs_the_heartbeat_ledger(self, pod_home: Path) -> None:
        """Every write of the queue regenerates the ledger, a retry included: an entry left for
        a task that is no longer ``running`` goes with the retry."""
        _seed_lean_pod("myapp")
        _put_task("myapp", _make_task(id="task-1", status="failed"))
        lead = current_home().workspace_dir("myapp-lead")
        _mem.write_dispatch_tasks(
            lead, [_mem.DispatchHeartbeatTask(task_id="task-1", description="x", claimed_at="")]
        )
        assert _mem.read_dispatch_task_ids(lead) == ["task-1"]

        assert _lifecycle.retry_task("myapp", "task-1") is True

        assert _mem.read_dispatch_task_ids(lead) == []

    def test_a_done_task_is_not_retried(self, pod_home: Path) -> None:
        _seed_lean_pod("myapp")
        _put_task("myapp", _make_task(id="task-1", status="done"))

        assert _lifecycle.retry_task("myapp", "task-1") is False
        assert TaskRepository.for_pod("myapp").list()[0].status == "done"
        assert "task.retry" not in _audit_actions()


_GONE_PID = 2_000_000_000


class TestStaleClaimReclaim:
    """``--resume`` reclaims a ``running`` task whose claimant is gone, and only that one."""

    def _running(self, claim_pid: int, claimed_at: str) -> TaskRecord:
        return _make_task(id="task-1", status="running", claim_pid=claim_pid, claimed_at=claimed_at)

    def test_dead_claimant_is_reclaimed_and_audited(self, pod_home: Path) -> None:
        from tests.support.fakes import FakeDriver

        _seed_lean_pod("myapp")
        _put_task("myapp", self._running(_GONE_PID, _clock.iso()))

        results = _sweep.dispatch_pod("myapp", runner=FakeDriver(), resume=True)

        assert [r.task_id for r in results] == ["task-1"]
        assert TaskRepository.for_pod("myapp").list()[0].status == "done"
        assert "task.reclaimed" in _audit_actions()

    def test_dead_claimant_reclaim_marks_the_trace_with_a_stale_claim_event(
        self, pod_home: Path
    ) -> None:
        claimed_at = _clock.iso()
        _seed_lean_pod("myapp")
        _put_task("myapp", self._running(_GONE_PID, claimed_at))

        _lifecycle.reclaim_stale_running("myapp")

        found = _trace.find_trace("agent:myapp:task-1")
        assert found is not None
        [event] = [e for e in _trace.read_trace(found) if e["event_type"] == "stale_claim"]
        assert event["payload"] == {"task": "task-1", "claimedAt": claimed_at}

    def test_live_claimant_inside_the_lease_is_left_alone(self, pod_home: Path) -> None:
        import os

        from tests.support.fakes import FakeDriver

        _seed_lean_pod("myapp")
        _put_task("myapp", self._running(os.getpid(), _clock.iso()))

        results = _sweep.dispatch_pod("myapp", runner=FakeDriver(), resume=True)

        assert results == []
        assert TaskRepository.for_pod("myapp").list()[0].status == "running"
        assert "task.reclaimed" not in _audit_actions()


class TestStopBetweenTasks:
    def test_dispatch_pod_stops_between_tasks_when_asked(self, pod_home: Path) -> None:
        """A stop that flips after the first claim ends the loop with the rest still pending."""
        from tests.support.fakes import FakeDriver

        _seed_lean_pod("myapp")
        _bind_one_step_pipeline("myapp")
        put_tasks("myapp", *(_make_task(id=f"task-{i}") for i in (1, 2, 3)))
        driver = FakeDriver()

        results = _sweep.dispatch_pod("myapp", runner=driver, stop=lambda: len(driver.calls) >= 1)

        assert len(results) == 1
        statuses = [t.status for t in TaskRepository.for_pod("myapp").list()]
        assert sorted(statuses) == ["done", "pending", "pending"]
