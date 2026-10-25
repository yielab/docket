"""Approval-gated dispatch — the approval store's missing producer.

Wires ``governance/approval.py``'s ``approval_create`` into ``core/dispatch.py`` end to end: creates,
waits on, and resolves a real approval rather than sitting with zero production callers.

  * TestGateSources — the pipeline ``approval`` gate is the one source of a pre-hop gate.
  * TestGateFiresPreHop — a required hop stops *before* its turn runs, persists
    ``waiting_approval`` with a token + exact pipeline position, and traces ``approval_required``.
  * TestNotClaimableConcurrently — a ``waiting_approval`` task is invisible to every claim path
    (a second ``dispatch_pod`` call, or ``claim_next_task`` directly) until its approval resolves.
  * TestGrantResumesAtHop — a grant (direct, and via ``cli/_approve.py``) flips the task to
    ``pending`` and the next dispatch resumes at the exact hop it stopped on — never re-running
    completed hops, never re-prompting for that same hop.
  * TestDenyFailsTerminally — a deny (direct, and via ``cli/_deny.py``) fails the task
    immediately with ``failureKind: "approval_denied"``, never auto-retried even with ``--resume``.
  * TestExpirySweepDenies — ``sweep_escalations`` resolves a stale pending record to
    **denied** (fail-closed, not the old unread ``"expired"``) and fails the waiting task.
  * TestHttpApprovalEndpoint — ``POST /approvals/<token>`` genuinely resumes/kills the task it
    gated, same as the CLI channel.
  * TestReworkReGatesAfterResume — the single-use gate override is consumed exactly once: a
    Reviewer rework cycle sending the task back to the same Implementer hop gates again, with a
    fresh token.
  * TestBudgetGateTakesPrecedence — affordability is checked before permission: a budget-blocked
    hop blocks, it does not wait for approval.
  * TestToolLevelApprovalMode — the tool-call-level gate's own routing
    (``ToolContext.approval_mode``), one level below the pod-dispatch gate: ``"wait"`` is
    unchanged, ``"refuse"`` never touches the approval store at all.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import pytest
from tests.support import home as _support_home
from tests.support.pods import GATED_IMPLEMENTER_PIPELINE_YAML
from tests.support.pods import write_meta as _write_meta
from tests.support.trace import trace_events as _trace_events
from typer.testing import CliRunner

from docket.agent import ports as _rd
from docket.agent.ports import ToolCall
from docket.agent.tools.registry import ToolContext, dispatch_tool
from docket.governance import approval as _ap
from docket.governance import audit as _audit
from docket.governance.policy import install_policies
from docket.hops.application import executor as _executor_c
from docket.hops.application import steps as _steps_c
from docket.hops.application import sweep as _sweep
from docket.hops.application import usage as _usage
from docket.hops.application.builtin_tools import builtin_registry
from docket.hops.gates import pre_hop as _pre_hop
from docket.interfaces.cli.app import app
from docket.interfaces.http.server import _DocketHandler
from docket.kernel.home import current_home, use_home
from docket.kernel.threads import ContextHTTPServer
from docket.pipeline.domain import gates as _gates
from docket.tasks.application import actions as _actions
from docket.tasks.application import escalation_sweep as _escalation_sweep
from docket.tasks.application import lifecycle as _lifecycle
from docket.tasks.application import queue as _queue
from docket.tasks.application.repository import TaskRepository
from docket.tasks.domain.task import TaskRecord
from docket.teams import fleet as _fleet
from docket.teams import pod as _pod
from docket.teams import settings as _settings

_hermetic = _support_home.hermetic

SUBJECT = "docket.hops.application.sweep"

# ── hermetic environment (mirrors test_reviewer_gate.py) ──────────────────────


def _bind_gated_implementer(project: str) -> None:
    """Bind a pod pipeline that is the default one with an ``approval`` gate on the Implementer."""
    text = GATED_IMPLEMENTER_PIPELINE_YAML
    path = _pod.bound_pipeline_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    _fleet.meta_set(
        _pod.member_id(project, "lead"), "pipeline", hashlib.sha256(text.encode()).hexdigest()
    )


def _seed_lean_pod(project: str = "myapp", *, gated: bool = False) -> None:
    _write_meta(f"{project}-lead")
    _write_meta(f"{project}-implementer")
    if gated:
        _bind_gated_implementer(project)


def _seed_full_pod(project: str = "myapp", *, gated: bool = False) -> None:
    _write_meta(f"{project}-lead")
    _write_meta(f"{project}-implementer")
    _write_meta(f"{project}-reviewer")
    _write_meta(f"{project}-tester")
    if gated:
        _bind_gated_implementer(project)


class _RecordingRunner:
    """Stub matching agent_run's signature; records calls, returns canned results."""

    def __init__(self, *, ok: bool = True, cost: float = 0.0):
        self.calls: list[str] = []
        self.ok = ok
        self.cost = cost

    def __call__(
        self,
        agent_id: str,
        session_key: str,
        message: str,
        timeout: int,
        env: dict[str, str] | None = None,
    ) -> _rd.TurnResult:
        self.calls.append(agent_id.rsplit("-", 1)[-1])
        return _rd.TurnResult(self.ok, f"done by {agent_id}", self.cost, {"output": "x"})


class _VerdictAwareRunner:
    """Like _RecordingRunner, but Reviewer/Tester hops carry a real verdict so a
    full pod can finish `done`."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def __call__(
        self,
        agent_id: str,
        session_key: str,
        message: str,
        timeout: int,
        env: dict[str, str] | None = None,
    ) -> _rd.TurnResult:
        role = agent_id.rsplit("-", 1)[-1]
        self.calls.append(role)
        if role == "tester":
            output = "PASS - looks good"
        elif role == "reviewer":
            output = "APPROVE - looks good"
        else:
            output = f"done by {agent_id}"
        return _rd.TurnResult(True, output, 0.01, {"output": output})


class _OneReworkThenGateAgainRunner:
    """Implementer/Lead succeed; Reviewer REQUEST-CHANGES exactly once, then
    APPROVE; Tester PASS. Proves the gate re-fires on the rework hop."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self._reviewer_calls = 0

    def __call__(
        self,
        agent_id: str,
        session_key: str,
        message: str,
        timeout: int,
        env: dict[str, str] | None = None,
    ) -> _rd.TurnResult:
        role = agent_id.rsplit("-", 1)[-1]
        self.calls.append(role)
        if role == "reviewer":
            self._reviewer_calls += 1
            output = (
                "REQUEST-CHANGES\nfix it" if self._reviewer_calls == 1 else "APPROVE - now good"
            )
        elif role == "tester":
            output = "PASS - looks good"
        else:
            output = f"done by {agent_id}"
        return _rd.TurnResult(True, output, 0.01, {"output": output})


# ── the pipeline gate source ───────────────────────────────────────────────────


class TestGateSources:
    def test_pipeline_step_seam_is_now_wired(self) -> None:
        """This seam reflects the current pipeline position's *resolved* gate —
        real for any step whose gate is `approval` (declared directly, or via an
        archetype's gateContract), regardless of role name."""
        assert _pre_hop._pipeline_step_requires_approval(None) is False
        assert _pre_hop._pipeline_step_requires_approval(_gates.MechanicalGate()) is False
        assert _pre_hop._pipeline_step_requires_approval(_gates.ApprovalGate()) is True


# ── the gate fires pre-hop ────────────────────────────────────────────────────────


class TestGateFiresPreHop:
    def test_gate_stops_before_the_gated_hop_runs(self) -> None:
        _seed_lean_pod(gated=True)
        _queue.enqueue_task_once("myapp", "Ship it", channel="cli")
        runner = _RecordingRunner()
        results = _sweep.dispatch_pod("myapp", runner=runner)
        assert len(results) == 1
        assert results[0].status == "waiting_approval"
        # Lead ran (not gated); the implementer's turn never happened.
        assert runner.calls == ["lead"]

    def test_waiting_approval_persists_token_and_pipeline_position(self) -> None:
        _seed_lean_pod(gated=True)
        _queue.enqueue_task_once("myapp", "Ship it", channel="cli")
        _sweep.dispatch_pod("myapp", runner=_RecordingRunner())

        task = TaskRepository.for_pod("myapp").list()[0]
        assert task.status == "waiting_approval"
        assert task.claim_pid is None
        assert task.approval_token
        assert task.approval_token.startswith("apr-")
        # Lean pod pipeline is [lead, implementer] -> implementer is index 1.
        assert task.pending_approval_index == 1
        # Only the lead hop is on record; the implementer hop never ran.
        assert [h.role for h in task.hops] == ["lead"]

    def test_gate_creates_a_real_approval_record(self) -> None:
        _seed_lean_pod(gated=True)
        task = _queue.enqueue_task_once("myapp", "Ship it", channel="cli")[0]
        _sweep.dispatch_pod("myapp", runner=_RecordingRunner())

        stored = TaskRepository.for_pod("myapp").list()[0]
        token = stored.approval_token
        pending = _ap.list_pending()
        assert any(p["token"] == token for p in pending)
        rec = _ap.approval_get(token)
        assert rec["project"] == "myapp"
        assert rec["role"] == "implementer"
        assert rec["state"] == "pending"
        assert rec["context"] == {"taskId": task.id, "pipelineIndex": 1}

    def test_approval_required_trace_event_emitted(self) -> None:
        _seed_lean_pod(gated=True)
        _queue.enqueue_task_once("myapp", "Ship it", channel="cli")
        _sweep.dispatch_pod("myapp", runner=_RecordingRunner())

        events = _trace_events("myapp")
        gate_events = [e for e in events if e["event_type"] == "approval_required"]
        assert len(gate_events) == 1
        assert gate_events[0]["payload"]["role"] == "implementer"

    def test_pod_with_no_gated_roles_is_unaffected(self) -> None:
        _seed_lean_pod()
        _queue.enqueue_task_once("myapp", "Ship it", channel="cli")
        runner = _RecordingRunner()
        results = _sweep.dispatch_pod("myapp", runner=runner)
        assert results[0].status == "done"
        assert runner.calls == ["lead", "implementer"]


# ── waiting_approval is invisible to every claim path ────────────────────────────


class TestNotClaimableConcurrently:
    def test_second_dispatch_pod_call_does_not_reclaim_it(self) -> None:
        _seed_lean_pod(gated=True)
        _queue.enqueue_task_once("myapp", "Ship it", channel="cli")
        _sweep.dispatch_pod("myapp", runner=_RecordingRunner())
        assert TaskRepository.for_pod("myapp").list()[0].status == "waiting_approval"

        runner2 = _RecordingRunner()
        results = _sweep.dispatch_pod("myapp", runner=runner2)
        assert results == []
        assert runner2.calls == []
        assert TaskRepository.for_pod("myapp").list()[0].status == "waiting_approval"

    def test_claim_next_task_directly_returns_none(self) -> None:
        _seed_lean_pod(gated=True)
        _queue.enqueue_task_once("myapp", "Ship it", channel="cli")
        _sweep.dispatch_pod("myapp", runner=_RecordingRunner())

        assert _queue.claim_next_task("myapp", resume=False) is None
        # --resume only ever reclaims a stale_claim failure, never a
        # waiting_approval task.
        assert _queue.claim_next_task("myapp", resume=True) is None

    def test_stale_claim_sweep_does_not_touch_a_waiting_approval_task(self) -> None:
        _seed_lean_pod(gated=True)
        _queue.enqueue_task_once("myapp", "Ship it", channel="cli")
        _sweep.dispatch_pod("myapp", runner=_RecordingRunner())

        # Even if the stale-claim clock were somehow tripped, a
        # waiting_approval task has no claimedAt to go stale against — the
        # sweep only ever looks at status == "running".
        with use_home(dataclasses.replace(current_home(), claim_stale_timeout=-1)):
            _lifecycle.sweep_stale_claims("myapp")
            assert TaskRepository.for_pod("myapp").list()[0].status == "waiting_approval"


# ── grant resumes at the exact hop ────────────────────────────────────────────────


class TestGrantResumesAtHop:
    def _gate_then_grant(self) -> str:
        _seed_full_pod(gated=True)
        _queue.enqueue_task_once("myapp", "Ship it", channel="cli")
        _sweep.dispatch_pod("myapp", runner=_RecordingRunner())
        token = TaskRepository.for_pod("myapp").list()[0].approval_token
        return token

    def test_resolve_waiting_approval_flips_to_pending_with_override(self) -> None:
        token = self._gate_then_grant()
        _ap.approval_grant(token, channel="cli")
        updated = _actions.resolve_waiting_approval(token, "granted")
        assert updated is True

        task = TaskRepository.for_pod("myapp").list()[0]
        assert task.status == "pending"
        assert task.approval_token is None
        assert task.pending_approval_index is None
        assert task.gate_override_pipeline_index == 1

    def test_next_dispatch_continues_from_the_gated_hop(self) -> None:
        token = self._gate_then_grant()
        _ap.approval_grant(token, channel="cli")
        _actions.resolve_waiting_approval(token, "granted")

        runner = _VerdictAwareRunner()
        results = _sweep.dispatch_pod("myapp", runner=runner)
        assert len(results) == 1
        assert results[0].status == "done"
        # The lead hop is NOT re-run; only implementer/reviewer/tester continue.
        assert runner.calls == ["implementer", "reviewer", "tester"]

        final = TaskRepository.for_pod("myapp").list()[0]
        assert [h.role for h in final.hops] == [
            "lead",
            "implementer",
            "reviewer",
            "tester",
        ]
        assert final.approval_token is None
        assert final.gate_override_pipeline_index is None

    def test_grant_via_cli_approve_resumes_dispatch(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        token = self._gate_then_grant()
        rc = CliRunner().invoke(app, ["task", "approve", token]).exit_code
        assert rc == 0
        capsys.readouterr()

        task = TaskRepository.for_pod("myapp").list()[0]
        assert task.status == "pending"
        assert task.gate_override_pipeline_index == 1

        runner = _VerdictAwareRunner()
        results = _sweep.dispatch_pod("myapp", runner=runner)
        assert results[0].status == "done"
        assert runner.calls == ["implementer", "reviewer", "tester"]

    def test_grant_on_a_non_dispatch_token_is_a_harmless_noop(self) -> None:
        token = _ap.approval_create("someproj", "programmer", "rm -rf /tmp/x")
        _ap.approval_grant(token, channel="cli")
        assert _actions.resolve_waiting_approval(token, "granted") is False

    def test_resolve_waiting_approval_unknown_token_returns_false(self) -> None:
        assert _actions.resolve_waiting_approval("apr-does-not-exist", "granted") is False


# ── deny fails the task terminally ───────────────────────────────────────────────


class TestDenyFailsTerminally:
    def _gate(self) -> str:
        _seed_lean_pod(gated=True)
        _queue.enqueue_task_once("myapp", "Ship it", channel="cli")
        _sweep.dispatch_pod("myapp", runner=_RecordingRunner())
        return str(TaskRepository.for_pod("myapp").list()[0].approval_token)

    def test_resolve_waiting_approval_fails_task_immediately(self) -> None:
        token = self._gate()
        _ap.approval_deny(token, channel="cli")
        updated = _actions.resolve_waiting_approval(token, "denied")
        assert updated is True

        task = TaskRepository.for_pod("myapp").list()[0]
        assert task.status == "failed"
        assert task.failure_kind == "approval_denied"
        assert task.reason == "approval denied"
        assert task.approval_token is None
        assert task.pending_approval_index is None
        assert task.completed_at

    def test_denied_task_is_never_reclaimed_even_with_resume(self) -> None:
        token = self._gate()
        _ap.approval_deny(token, channel="cli")
        _actions.resolve_waiting_approval(token, "denied")

        runner = _RecordingRunner()
        results = _sweep.dispatch_pod("myapp", runner=runner, resume=True)
        assert results == []
        assert runner.calls == []
        assert TaskRepository.for_pod("myapp").list()[0].status == "failed"

    def test_deny_via_cli_deny_fails_dispatch_task(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        token = self._gate()
        rc = CliRunner().invoke(app, ["task", "deny", token]).exit_code
        assert rc == 0
        capsys.readouterr()

        task = TaskRepository.for_pod("myapp").list()[0]
        assert task.status == "failed"
        assert task.failure_kind == "approval_denied"

    def test_deny_trace_event_emitted(self) -> None:
        token = self._gate()
        _ap.approval_deny(token, channel="cli")
        _actions.resolve_waiting_approval(token, "denied")

        events = _trace_events("myapp")
        assert any(e["event_type"] == "approval_task_denied" for e in events)


# ── expiry sweep resolves to denied (fail-closed) ────────────────────────────────


class TestExpirySweepDenies:
    def test_sweep_marks_stale_pending_approval_denied(self) -> None:
        token = _ap.approval_create("someproj", "programmer", "rm -rf /tmp/x")
        rec = _ap.approval_get(token)
        rec["created"] = "2000-01-01T00:00:00Z"
        rec["expiresAt"] = rec["created"]
        current_home().approvals_dir.joinpath(f"{token}.json").write_text(json.dumps(rec))

        swept = _escalation_sweep.sweep_escalations()
        assert swept == 1
        assert _ap.approval_get(token)["state"] == "denied"

    def test_sweep_writes_timeout_channel_audit_entry(self) -> None:
        token = _ap.approval_create("someproj", "programmer", "rm -rf /tmp/x")
        rec = _ap.approval_get(token)
        rec["created"] = "2000-01-01T00:00:00Z"
        rec["expiresAt"] = rec["created"]
        current_home().approvals_dir.joinpath(f"{token}.json").write_text(json.dumps(rec))

        _escalation_sweep.sweep_escalations()
        entries = [
            json.loads(line)
            for line in current_home().audit_log.read_text().splitlines()
            if line.strip()
        ]
        assert any(
            e["action"] == "approval.deny"
            and "channel=timeout" in e["detail"]
            and token in e["detail"]
            for e in entries
        )

    def test_sweep_fails_the_waiting_dispatch_task(self) -> None:
        _seed_lean_pod(gated=True)
        _queue.enqueue_task_once("myapp", "Ship it", channel="cli")
        _sweep.dispatch_pod("myapp", runner=_RecordingRunner())
        token = str(TaskRepository.for_pod("myapp").list()[0].approval_token)

        rec = _ap.approval_get(token)
        rec["created"] = "2000-01-01T00:00:00Z"
        rec["expiresAt"] = rec["created"]
        current_home().approvals_dir.joinpath(f"{token}.json").write_text(json.dumps(rec))

        swept = _escalation_sweep.sweep_escalations()
        assert swept == 1

        task = TaskRepository.for_pod("myapp").list()[0]
        assert task.status == "failed"
        assert task.failure_kind == "approval_denied"


# ── HTTP POST /approvals/<token> genuinely resumes/kills ─────────────────────────

_TEST_TOKEN = "test-serve-token-g1-xyz789"


@pytest.fixture()
def live_server() -> Any:
    class _Handler(_DocketHandler):
        serve_token = _TEST_TOKEN

    srv = ContextHTTPServer(("127.0.0.1", 0), _Handler)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{port}"
    srv.shutdown()


def _post(url: str, body: dict[str, Any], token: str) -> tuple[int, dict[str, Any]]:
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


class TestHttpApprovalEndpoint:
    def test_post_grant_resumes_the_dispatch_task(self, live_server: str) -> None:
        _seed_full_pod(gated=True)
        _queue.enqueue_task_once("myapp", "Ship it", channel="cli")
        _sweep.dispatch_pod("myapp", runner=_RecordingRunner())
        token = str(TaskRepository.for_pod("myapp").list()[0].approval_token)

        status, body = _post(f"{live_server}/approvals/{token}", {"action": "grant"}, _TEST_TOKEN)
        assert status == 200
        assert body["state"] == "granted"

        task = TaskRepository.for_pod("myapp").list()[0]
        assert task.status == "pending"
        assert task.gate_override_pipeline_index == 1

        runner = _VerdictAwareRunner()
        results = _sweep.dispatch_pod("myapp", runner=runner)
        assert results[0].status == "done"
        assert runner.calls == ["implementer", "reviewer", "tester"]

    def test_post_deny_fails_the_dispatch_task(self, live_server: str) -> None:
        _seed_lean_pod(gated=True)
        _queue.enqueue_task_once("myapp", "Ship it", channel="cli")
        _sweep.dispatch_pod("myapp", runner=_RecordingRunner())
        token = str(TaskRepository.for_pod("myapp").list()[0].approval_token)

        status, body = _post(f"{live_server}/approvals/{token}", {"action": "deny"}, _TEST_TOKEN)
        assert status == 200
        assert body["state"] == "denied"

        task = TaskRepository.for_pod("myapp").list()[0]
        assert task.status == "failed"
        assert task.failure_kind == "approval_denied"


# ── the single-use override is consumed exactly once ─────────────────────────────


class TestReworkReGatesAfterResume:
    def test_rework_cycle_re_gates_the_second_implementer_hop(self) -> None:
        _seed_full_pod(gated=True)
        _queue.enqueue_task_once("myapp", "Ship it", channel="cli")
        _sweep.dispatch_pod("myapp", runner=_RecordingRunner())
        first_token = str(TaskRepository.for_pod("myapp").list()[0].approval_token)
        assert first_token

        _ap.approval_grant(first_token, channel="cli")
        _actions.resolve_waiting_approval(first_token, "granted")

        runner = _OneReworkThenGateAgainRunner()
        results = _sweep.dispatch_pod("myapp", runner=runner)
        assert len(results) == 1
        # The override cleared the gate for the FIRST implementer hop only;
        # the Reviewer's REQUEST-CHANGES sends it back to the Implementer a
        # second time, and that second hop gates again (a fresh token).
        assert results[0].status == "waiting_approval"
        assert runner.calls == ["implementer", "reviewer"]

        second_task = TaskRepository.for_pod("myapp").list()[0]
        second_token = second_task.approval_token
        assert second_token
        assert second_token != first_token
        assert second_task.pending_approval_index == 1  # same implementer index

        # Grant the second gate too and let the task finish.
        _ap.approval_grant(second_token, channel="cli")
        _actions.resolve_waiting_approval(second_token, "granted")
        final_runner = _OneReworkThenGateAgainRunner()
        final_runner._reviewer_calls = 1  # next reviewer call approves
        final_results = _sweep.dispatch_pod("myapp", runner=final_runner)
        assert final_results[0].status == "done"


class TestGateOverrideIndexArgument:
    """``dispatch_task`` takes the claim's ``gate_override_index`` as an argument, not a task key."""

    def test_the_index_skips_that_gate_once_and_the_rework_revisit_gates(self) -> None:
        _seed_full_pod(gated=True)
        runner = _OneReworkThenGateAgainRunner()

        result = _executor_c.dispatch_task(
            "myapp",
            TaskRecord(id="task-1", description="Ship it"),
            gate_override_index=1,
            runner=runner,
        )

        # The implementer (index 1) ran ungated once; the reviewer sent it back; it gated then.
        assert runner.calls == ["lead", "implementer", "reviewer"]
        assert result.status == "waiting_approval"
        assert result.pending_approval_index == 1

    def test_without_an_index_the_first_implementer_hop_gates(self) -> None:
        _seed_full_pod(gated=True)
        runner = _OneReworkThenGateAgainRunner()

        result = _executor_c.dispatch_task(
            "myapp", TaskRecord(id="task-1", description="Ship it"), runner=runner
        )

        assert runner.calls == ["lead"]
        assert (result.status, result.pending_approval_index) == ("waiting_approval", 1)


# ── budget still checked before approval (affordability before permission) ──────


class TestBudgetGateTakesPrecedence:
    def test_budget_blocked_hop_never_reaches_the_approval_gate(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_lean_pod(gated=True)
        _queue.enqueue_task_once("myapp", "Too expensive", channel="cli")
        monkeypatch.setattr(_settings, "pod_budget", lambda _p: 1.0)
        monkeypatch.setattr(_steps_c, "pod_budget", lambda _p: 1.0)
        monkeypatch.setattr(_executor_c, "pod_budget", lambda _p: 1.0)
        monkeypatch.setattr(_usage, "pod_recorded_cost", lambda _p: 5.0)
        monkeypatch.setattr(_pre_hop, "pod_recorded_cost", lambda _p: 5.0)

        results = _sweep.dispatch_pod("myapp", runner=_RecordingRunner())
        assert results[0].status == "blocked"
        # No approval record was ever created for this hop.
        assert _ap.list_pending() == []


# ── approval_create's context parameter ──────────────────────────────────────────


class TestApprovalCreateContext:
    def test_context_round_trips(self) -> None:
        token = _ap.approval_create(
            "myapp", "implementer", "do the thing", context={"taskId": "task-1", "x": 2}
        )
        rec = _ap.approval_get(token)
        assert rec["context"] == {"taskId": "task-1", "x": 2}

    def test_context_defaults_to_empty_dict(self) -> None:
        token = _ap.approval_create("myapp", "implementer", "do the thing")
        rec = _ap.approval_get(token)
        assert rec["context"] == {}


# ── tool-call-level approval routing (agent/tools/registry.py's ToolContext.approval_mode) ──


class TestToolLevelApprovalMode:
    """`dispatch_tool`'s own `ask` routing, gated by the real shipped
    `block-destructive` template rather than a synthetic policy."""

    def test_refuse_mode_denies_immediately_with_no_record_and_one_audit_entry(
        self, tmp_path: Path
    ) -> None:
        # A zero bound on the *wait* path so an ignored approval_mode fails fast
        # instead of blocking; the empty approvals dir is what proves no wait
        # happened. The elapsed bound is loose because shared CI runners have
        # measured over 100ms for this call.
        with use_home(dataclasses.replace(current_home(), tool_approval_timeout=0)):
            install_policies()
            ws = tmp_path / "ws"
            ws.mkdir()
            ctx = ToolContext(agent_id="demo", role="implementer", project="demo", roots=(ws,))
            ctx.approval_mode = "refuse"
            registry = builtin_registry()
            call = ToolCall(id="c1", name="bash", arguments=json.dumps({"command": "rm -rf build"}))

            started = time.monotonic()
            result = dispatch_tool(call, ctx, registry)
            elapsed = time.monotonic() - started

            assert elapsed < 1.0
            assert result.decision == "deny"
            assert result.denial_kind == "approval_unavailable"
            assert result.policy_id == "block-destructive"
            assert (
                not current_home().approvals_dir.exists()
                or list(current_home().approvals_dir.glob("*.json")) == []
            )
            ask_entries = [e for e in _audit.read_audit() if e["action"] == "tool.ask"]
            assert len(ask_entries) == 1

    def test_wait_mode_is_unchanged_still_creates_a_record_and_times_out(
        self, tmp_path: Path
    ) -> None:
        """`approval_mode` defaults to `"wait"` -- today's behavior, byte for
        byte: a real record is created and an unanswered call times out to
        denied, exactly as before this field existed."""
        with use_home(dataclasses.replace(current_home(), tool_approval_timeout=0)):
            install_policies()
            ws = tmp_path / "ws"
            ws.mkdir()
            ctx = ToolContext(agent_id="demo", role="implementer", project="demo", roots=(ws,))
            registry = builtin_registry()
            call = ToolCall(id="c1", name="bash", arguments=json.dumps({"command": "rm -rf build"}))

            result = dispatch_tool(call, ctx, registry)

            assert result.decision == "deny"
            assert result.denial_kind == "approval_timeout"
            records = list(current_home().approvals_dir.glob("*.json"))
            assert len(records) == 1
            stored = json.loads(records[0].read_text())
            assert stored["state"] == "denied"
