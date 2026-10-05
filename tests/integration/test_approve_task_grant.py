"""``approve_task`` on a parked pod approval: the grant lasts the rest of that task.

Drives the real writers: a parked approval as ``core/tools.py::_park_call`` creates it, the task
flipped to ``waiting_approval`` as ``_apply_result`` does, then ``docket approve --option`` /
Telegram ``/approve <token> task`` into ``resolve_waiting_approval``, and ``_compose_hop`` into
the real ``DOCKET_PREGRANTS`` decoder and the real pre-grant consumer.
"""

from __future__ import annotations

from typing import Any

import pytest

from docket.cli import _pod
from docket.cli._approve import run_approve
from docket.core import approval as _approval
from docket.core import audit as _audit
from docket.core import dispatch as _dispatch
from docket.core import fleet as _fleet
from docket.core import orchestrator as _orch
from docket.core import runtime_driver as _rd
from docket.core import telegram as _tg
from docket.core.operator_contract import canonical_args_digest
from docket.core.tools import ToolContext, _consume_matching_pregrant
from docket.edges import store as _store
from docket.edges.adapters.docket_runtime import _parse_pregrants

SUBJECT = "docket.core"

PROJECT = "demo"
CALL = {"command": "git push origin feature"}


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOCKET_SERVICE_MANAGER", "none")
    _pod.build_pod(PROJECT, _pod.pod.DEFAULT_POD_ROLES, codebase=f"/src/{PROJECT}")


def _park(task_id: str, args: dict[str, Any] | None = None) -> str:
    """Park *task_id* on one ``bash`` call exactly as an in-turn park does."""
    digest = canonical_args_digest("bash", args or CALL)
    token = _approval.approval_create(
        PROJECT,
        "implementer",
        "tool call 'bash': ask",
        context={
            "tool": "bash",
            "callId": "call-1",
            "argsDigest": digest,
            "parked": True,
            "project": PROJECT,
            "role": "implementer",
        },
        rationale="",
    )

    def _fn(doc: dict[str, Any]) -> dict[str, Any] | None:
        for t in doc["tasks"]:
            if t["id"] == task_id:
                t["status"] = "waiting_approval"
                t["approvalToken"] = token
        return {"tasks": doc["tasks"]}

    _store.read_modify_write(_dispatch.pod_task_list_path(PROJECT), _fn)
    return token


def _task(task_id: str) -> dict[str, Any]:
    return next(t for t in _dispatch.read_tasks(PROJECT) if t["id"] == task_id)


def _later_hop_env(task_id: str) -> dict[str, str]:
    ctx = _dispatch._UnitContext(
        project=PROJECT,
        task=_task(task_id),
        task_id=task_id,
        session_id=f"agent:{PROJECT}:{task_id}",
        cap=0.0,
        resolved_turn_timeout=60,
        resolved_verify_timeout=60,
        id_to_index={},
        rework_counts={},
        override_index=None,
        track_pid=False,
        run=lambda *a, **k: _rd.TurnResult(True, "", 0.0, {}),
        do_sleep=lambda s: None,
        on_hop=None,
        on_retry=None,
    )
    member = _pod.pod.member_id(PROJECT, "reviewer")
    node = _orch.PlannedUnit(
        step_id="reviewer",
        role="reviewer",
        agent=None,
        archetype=None,
        member_id=member,
        gate=None,
        retries=None,
        timeout=None,
    )
    _, env = _dispatch._compose_hop(ctx, node, "reviewer", member, [], None)
    return env or {}


def _spend(env: dict[str, str], args: dict[str, Any] | None = None) -> str | None:
    ctx = ToolContext(pregrants=_parse_pregrants(env.get(_rd.DOCKET_PREGRANTS)))
    return _consume_matching_pregrant(ctx, "bash", canonical_args_digest("bash", args or CALL))


class TestApproveTaskCli:
    def test_grant_records_a_task_grant_and_a_later_hop_runs_the_call(self) -> None:
        task = _dispatch.enqueue_task(PROJECT, "ship it")
        token = _park(task["id"])

        assert run_approve(token, option="approve_task") == 0

        grants = _task(task["id"])["taskGrants"]
        assert len(grants) == 1
        assert grants[0]["tool"] == "bash"
        assert grants[0]["argsDigest"] == canonical_args_digest("bash", CALL)
        assert grants[0]["token"] == token
        assert grants[0]["channel"] == "cli"
        assert grants[0]["grantedAt"]
        assert "actor" in grants[0]

        env = _later_hop_env(task["id"])
        used = _spend(env)
        assert used is not None
        assert any(
            e["action"] == "approval.consume" and used in e["detail"] for e in _audit.read_audit()
        )
        # Every use is single-use: the parked call's own pre-grant, then this hop's minted one.
        assert _spend(env) is not None
        assert _spend(env) is None
        # The next hop gets a fresh one.
        assert _spend(_later_hop_env(task["id"])) is not None

    def test_without_the_option_nothing_is_task_wide(self) -> None:
        task = _dispatch.enqueue_task(PROJECT, "ship it")
        token = _park(task["id"])
        assert run_approve(token) == 0
        stored = _task(task["id"])
        assert not stored.get("taskGrants")
        assert len(stored["pregrants"]) == 1

    def test_another_task_with_the_same_call_still_parks(self) -> None:
        first = _dispatch.enqueue_task(PROJECT, "one")
        second = _dispatch.enqueue_task(PROJECT, "two")
        run_approve(_park(first["id"]), option="approve_task")
        assert not _task(second["id"]).get("taskGrants")
        assert _spend(_later_hop_env(second["id"])) is None

    def test_a_different_argument_digest_still_parks(self) -> None:
        task = _dispatch.enqueue_task(PROJECT, "ship it")
        run_approve(_park(task["id"]), option="approve_task")
        env = _later_hop_env(task["id"])
        assert _spend(env, {"command": "git push origin main"}) is None

    def test_unknown_option_is_refused_and_leaves_the_approval_pending(self) -> None:
        task = _dispatch.enqueue_task(PROJECT, "ship it")
        token = _park(task["id"])
        assert run_approve(token, option="approve_forever") == 1
        assert _approval.approval_get(token)["state"] == "pending"

    def test_grants_are_dropped_when_the_task_reaches_a_terminal_status(self) -> None:
        task = _dispatch.enqueue_task(PROJECT, "ship it")
        run_approve(_park(task["id"]), option="approve_task")
        stored = _task(task["id"])
        _dispatch._apply_result(stored, _dispatch.TaskResult(task["id"], "done"))
        assert "taskGrants" not in stored

    def test_denial_fails_the_task_with_nothing_to_grant(self) -> None:
        task = _dispatch.enqueue_task(PROJECT, "ship it")
        token = _park(task["id"])
        _approval.approval_deny(token, channel="cli")
        _dispatch.resolve_waiting_approval(token, "denied")
        stored = _task(task["id"])
        assert stored["status"] == "failed"
        assert not stored.get("taskGrants")

    def test_the_twenty_first_grant_is_refused_with_a_message(self) -> None:
        task = _dispatch.enqueue_task(PROJECT, "ship it")
        for i in range(_dispatch.TASK_GRANT_CAP):
            run_approve(_park(task["id"], {"command": f"echo {i}"}), option="approve_task")
        assert len(_task(task["id"])["taskGrants"]) == _dispatch.TASK_GRANT_CAP

        token = _park(task["id"], {"command": "echo extra"})
        _approval.approval_set_option(token, "approve_task")
        _approval.approval_grant(token, channel="cli")
        updated, note = _dispatch.resolve_waiting_approval_detail(token, "granted", channel="cli")

        assert updated
        assert "task-wide grants" in note
        stored = _task(task["id"])
        assert len(stored["taskGrants"]) == _dispatch.TASK_GRANT_CAP
        assert any(e["action"] == "approval.task_grant_refused" for e in _audit.read_audit())
        # The call itself was still approved once.
        assert stored["status"] == "pending"
        assert stored["pregrants"][-1]["token"] == token


class TestApproveTaskTelegram:
    def _bind(self) -> None:
        _fleet.upsert_binding(_pod.pod.member_id(PROJECT, "lead"), "-100", "telegram")

    def _say(self, text: str) -> _tg.TelegramActionResult:
        return _tg.handle_message(_tg.InboundMessage("-100", "1", text, 1))

    def test_approve_token_task_grants_task_wide(self) -> None:
        self._bind()
        task = _dispatch.enqueue_task(PROJECT, "ship it")
        token = _park(task["id"])
        assert self._say(f"/approve {token} task").ok
        grants = _task(task["id"])["taskGrants"]
        assert [g["channel"] for g in grants] == ["telegram"]

    def test_plain_approve_stays_single_use(self) -> None:
        self._bind()
        task = _dispatch.enqueue_task(PROJECT, "ship it")
        token = _park(task["id"])
        assert self._say(f"/approve {token}").ok
        assert not _task(task["id"]).get("taskGrants")

    def test_unbound_chat_cannot_grant_task_wide(self) -> None:
        task = _dispatch.enqueue_task(PROJECT, "ship it")
        token = _park(task["id"])
        out = self._say(f"/approve {token} task")
        assert not out.authorized
        assert _approval.approval_get(token)["state"] == "pending"

    def test_an_unknown_trailing_word_is_unrecognized(self) -> None:
        self._bind()
        out = self._say("/approve apr-x forever")
        assert out.action == "unparseable"
        assert "Unrecognized" in out.reply
