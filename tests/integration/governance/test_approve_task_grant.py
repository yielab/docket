"""``approve_task`` on a parked pod approval: the grant lasts the rest of that task.

Drives the real writers: a parked approval as ``governance/gate.py::_park`` creates it, the task
flipped to ``waiting_approval`` as ``_apply_result`` does, then ``docket task answer --option
approve_task`` / the escalation resolve route into ``resolve_waiting_approval``, and
``_compose_hop`` into the real ``DOCKET_PREGRANTS`` decoder and the real pre-grant consumer.
"""

from __future__ import annotations

from typing import Any

import pytest
from tests.support.approvals import escalation_of, resolve_token
from tests.support.pods import build_pod
from tests.support.tasks import stored_task, update_task
from typer.testing import CliRunner

from docket.agent import ports as _rd
from docket.agent.tools.registry import ToolContext
from docket.governance import approval as _approval
from docket.governance import approval_pregrant as _pregrants
from docket.governance import audit as _audit
from docket.governance.gate import consume_matching_pregrant as _consume_matching_pregrant
from docket.hops.application import compose as _compose
from docket.hops.application.driver import _parse_pregrants
from docket.interfaces.cli.app import app
from docket.interfaces.cli.commands import pod as _pod
from docket.interfaces.telegram import bot as _tg
from docket.kernel.operator_contract import canonical_args_digest
from docket.pipeline.domain import plan as _orch
from docket.tasks.application import actions as _actions
from docket.tasks.application import escalations as _escalations
from docket.tasks.application import lifecycle as _lifecycle
from docket.tasks.application import queue as _queue
from docket.tasks.application import record as _record
from docket.tasks.domain import task as _domain_task
from docket.teams import fleet as _fleet

SUBJECT = "docket.governance.gate"


def run_answer(token: str, option: str) -> int:
    """`docket task answer <escalation of token> --option <option>`; its exit code."""
    ref = escalation_of(token)
    return CliRunner().invoke(app, ["task", "answer", ref, "--option", option]).exit_code


PROJECT = "demo"
CALL = {"command": "git push origin feature"}


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch: pytest.MonkeyPatch) -> None:
    build_pod(PROJECT, _pod.pod.DEFAULT_POD_ROLES, codebase=f"/src/{PROJECT}")


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
            "taskId": task_id,
            "project": PROJECT,
            "role": "implementer",
        },
        rationale="",
    )

    update_task(PROJECT, task_id, status="waiting_approval")
    _escalations.approval_opened(token, task_id=task_id, caused_by="call-1")
    return token


def _later_hop_env(task_id: str, role: str = "implementer") -> dict[str, str]:
    ctx = _record.UnitContext(
        project=PROJECT,
        task=stored_task(PROJECT, task_id),
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
    member = _pod.pod.member_id(PROJECT, role)
    node = _orch.PlannedUnit(
        step_id=role,
        role=role,
        agent=None,
        archetype=None,
        member_id=member,
        gate=None,
        retries=None,
        timeout=None,
    )
    _, env = _compose._compose_hop(ctx, node, role, member, [], None)
    return env or {}


def _spend(env: dict[str, str], args: dict[str, Any] | None = None) -> str | None:
    ctx = ToolContext(pregrants=_parse_pregrants(env.get(_rd.DOCKET_PREGRANTS)))
    return _consume_matching_pregrant(ctx, "bash", canonical_args_digest("bash", args or CALL))


class TestApproveTaskCli:
    def test_grant_records_a_task_grant_and_a_later_hop_runs_the_call(self) -> None:
        task = _queue.enqueue_task_once(PROJECT, "ship it", channel="cli")[0]
        token = _park(task.id)

        assert run_answer(token, "approve_task") == 0

        grants = _pregrants.task_grants(task.id)
        assert len(grants) == 1
        assert grants[0].tool == "bash"
        assert grants[0].args_digest == canonical_args_digest("bash", CALL)
        assert grants[0].token == token
        assert grants[0].channel == "cli"
        assert grants[0].created
        assert grants[0].actor == ""

        env = _later_hop_env(task.id)
        used = _spend(env)
        assert used is not None
        assert any(
            e["action"] == "approval.consume" and used in e["detail"] for e in _audit.read_audit()
        )
        # Every use is single-use: the parked call's own pre-grant, then this hop's minted one.
        assert _spend(env) is not None
        assert _spend(env) is None
        # The next hop gets a fresh one.
        assert _spend(_later_hop_env(task.id)) is not None

    def test_without_the_option_nothing_is_task_wide(self) -> None:
        task = _queue.enqueue_task_once(PROJECT, "ship it", channel="cli")[0]
        token = _park(task.id)
        assert run_answer(token, "approve_once") == 0
        assert not _pregrants.task_grants(task.id)
        assert len(_pregrants.pending_pregrants(task.id)) == 1

    def test_another_task_with_the_same_call_still_parks(self) -> None:
        first = _queue.enqueue_task_once(PROJECT, "one", channel="cli")[0]
        second = _queue.enqueue_task_once(PROJECT, "two", channel="cli")[0]
        run_answer(_park(first.id), "approve_task")
        assert not _pregrants.task_grants(second.id)
        assert _spend(_later_hop_env(second.id)) is None

    def test_a_later_hop_of_another_role_gets_no_task_grant(self) -> None:
        task = _queue.enqueue_task_once(PROJECT, "ship it", channel="cli")[0]
        run_answer(_park(task.id), "approve_task")
        assert _pregrants.task_grants(task.id)[0].role == "implementer"
        env = _later_hop_env(task.id, "reviewer")
        assert _spend(env) is not None  # the parked call's own single-use pre-grant
        assert _spend(env) is None

    def test_a_different_argument_digest_still_parks(self) -> None:
        task = _queue.enqueue_task_once(PROJECT, "ship it", channel="cli")[0]
        run_answer(_park(task.id), "approve_task")
        env = _later_hop_env(task.id)
        assert _spend(env, {"command": "git push origin main"}) is None

    def test_grants_are_dropped_when_the_task_reaches_a_terminal_status(self) -> None:
        task = _queue.enqueue_task_once(PROJECT, "ship it", channel="cli")[0]
        run_answer(_park(task.id), "approve_task")
        assert _pregrants.task_grants(task.id)
        _lifecycle.finalize_task(PROJECT, task.id, _domain_task.TaskResult(task.id, "done"))
        assert not _pregrants.task_grants(task.id)

    def test_denial_fails_the_task_with_nothing_to_grant(self) -> None:
        task = _queue.enqueue_task_once(PROJECT, "ship it", channel="cli")[0]
        token = _park(task.id)
        _approval.approval_deny(token, channel="cli")
        _actions.resolve_waiting_approval(token, "denied")
        stored = stored_task(PROJECT, task.id)
        assert stored.status == "failed"
        assert not _pregrants.task_grants(task.id)

    def test_the_twenty_first_grant_is_refused_with_a_message(self) -> None:
        task = _queue.enqueue_task_once(PROJECT, "ship it", channel="cli")[0]
        for i in range(_actions.TASK_GRANT_CAP):
            run_answer(_park(task.id, {"command": f"echo {i}"}), "approve_task")
        assert len(_pregrants.task_grants(task.id)) == _actions.TASK_GRANT_CAP

        token = _park(task.id, {"command": "echo extra"})
        note = resolve_token(token, "approve_task")

        assert "task-wide grants" in note
        stored = stored_task(PROJECT, task.id)
        assert len(_pregrants.task_grants(task.id)) == _actions.TASK_GRANT_CAP
        assert any(e["action"] == "approval.task_grant_refused" for e in _audit.read_audit())
        # The call itself was still approved once.
        assert stored.status == "pending"
        assert token in [g.token for g in _pregrants.pending_pregrants(task.id)]


class TestApproveTaskTelegram:
    def _bind(self) -> None:
        _fleet.upsert_binding(_pod.pod.member_id(PROJECT, "lead"), "-100", "telegram")

    def _say(self, text: str) -> _tg.TelegramActionResult:
        return _tg.handle_message(_tg.InboundMessage("-100", "1", text, 1))

    def test_approve_token_task_grants_task_wide(self) -> None:
        self._bind()
        task = _queue.enqueue_task_once(PROJECT, "ship it", channel="cli")[0]
        token = _park(task.id)
        assert self._say(f"/answer {escalation_of(token)} approve_task").ok
        assert [g.channel for g in _pregrants.task_grants(task.id)] == ["telegram"]

    def test_plain_approve_stays_single_use(self) -> None:
        self._bind()
        task = _queue.enqueue_task_once(PROJECT, "ship it", channel="cli")[0]
        token = _park(task.id)
        assert self._say(f"/answer {escalation_of(token)} approve_once").ok
        assert not _pregrants.task_grants(task.id)

    def test_unbound_chat_cannot_grant_task_wide(self) -> None:
        task = _queue.enqueue_task_once(PROJECT, "ship it", channel="cli")[0]
        token = _park(task.id)
        out = self._say(f"/answer {escalation_of(token)} approve_task")
        assert not out.authorized
        assert _approval.approval_get(token)["state"] == "pending"


class TestApproveTaskHttpAndMcp:
    def test_mcp_grant_with_the_option_records_a_task_grant(self) -> None:
        from docket.interfaces.cli.commands import mcp as _mcp

        task = _queue.enqueue_task_once(PROJECT, "ship it", channel="cli")[0]
        result = _mcp.tool_resolve(escalation_of(_park(task.id)), "approve_task")
        assert result["state"] == "resolved"
        (grant,) = _pregrants.task_grants(task.id)
        assert grant.channel == "mcp"

    def test_http_grant_with_the_option_records_a_task_grant(self) -> None:
        import json
        import threading
        import urllib.request

        from docket.interfaces.http.server import _DocketHandler
        from docket.kernel.threads import ContextHTTPServer

        class _Handler(_DocketHandler):
            serve_token = "tok-approve-task"

        srv = ContextHTTPServer(("127.0.0.1", 0), _Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            task = _queue.enqueue_task_once(PROJECT, "ship it", channel="cli")[0]
            token = _park(task.id)
            body = json.dumps({"optionId": "approve_task"}).encode()
            req = urllib.request.Request(
                f"http://127.0.0.1:{srv.server_address[1]}/escalations/{escalation_of(token)}",
                data=body,
                method="POST",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": "Bearer tok-approve-task",
                },
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                assert json.loads(resp.read())["state"] == "resolved"
        finally:
            srv.shutdown()
        (grant,) = _pregrants.task_grants(task.id)
        assert grant.channel == "http"

    def test_an_unknown_option_is_refused_by_mcp_and_leaves_the_approval_pending(self) -> None:
        from docket.interfaces.cli.commands import mcp as _mcp

        task = _queue.enqueue_task_once(PROJECT, "ship it", channel="cli")[0]
        token = _park(task.id)
        with pytest.raises(_mcp.McpToolError):
            _mcp.tool_resolve(escalation_of(token), "approve_forever")
        assert _approval.approval_get(token)["state"] == "pending"
