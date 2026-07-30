"""G-1: approval-gated dispatch — the approval store's missing producer.

Before this card ``core/approval.py``'s ``approval_create`` had zero production
callers: the approval store and the daemon's exec prompt were disconnected
systems, and nothing in ``core/dispatch.py`` ever created, waited on, or
resolved a docket approval. This suite exercises the pipeline this card wires
up end to end:

  * TestGateSources              — the pod-level ``requireApprovalRoles`` gate
    source in isolation, and the G-2/W-1/W-2 seams staying inert (always False).
  * TestGateFiresPreHop           — a required hop stops the pipeline *before*
    its agent turn runs, persists ``waiting_approval`` with a real approval
    token + the exact pipeline position, and traces ``approval_required``.
  * TestNotClaimableConcurrently  — a ``waiting_approval`` task is invisible to
    every claim path (a second ``dispatch_pod`` call, or ``_claim_next_task``
    directly) until its approval resolves.
  * TestGrantResumesAtHop         — a grant (``core/dispatch.py`` directly, and
    through ``cli/_approve.py``) flips the task back to ``pending`` and the
    *next* dispatch continues from the exact hop it stopped on — never
    re-running completed hops, never re-prompting for that same hop.
  * TestDenyFailsTerminally       — a deny (direct, and through
    ``cli/_deny.py``) fails the task immediately, ``failureKind:
    "approval_denied"``, never auto-retried (with or without ``--resume``).
  * TestExpirySweepDenies         — ``approval_sweep_expired`` now resolves a
    stale pending record to **denied** (fail-closed), not the old, read-by-
    nobody ``"expired"``, and reaches into dispatch to fail the waiting task.
  * TestHttpApprovalEndpoint      — ``POST /approvals/<token>`` genuinely
    resumes/kills the task it gated, the same as the CLI channel.
  * TestReworkReGatesAfterResume  — the single-use gate-override is consumed
    exactly once: a Reviewer rework cycle sending the task back to the same
    Implementer hop gates again, with a fresh token.
  * TestBudgetGateTakesPrecedence — affordability is still checked before
    permission: a budget-blocked hop blocks, it does not wait for approval.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

import docket.config as _cfg
from docket.cli import _approve, _deny
from docket.core import approval as _ap
from docket.core import dispatch as _dispatch
from docket.core import pipeline as _pipeline
from docket.core import trace as _trace
from docket.edges.adapters import openclaw as _oc
from docket.serve import _DocketHandler

# ── hermetic environment (mirrors test_r4_reviewer_gate.py) ──────────────────────


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DOCKET_NO_RESTART", "1")
    monkeypatch.setenv("DOCKET_SERVICE_MANAGER", "none")

    oc_dir = tmp_path / ".openclaw"
    (oc_dir / "workspaces" / "projects").mkdir(parents=True)
    cfg_file = oc_dir / "openclaw.json"
    cfg_file.write_text(json.dumps({"agents": {"list": []}, "bindings": [], "channels": {}}))

    monkeypatch.setattr(_cfg, "OPENCLAW_DIR", oc_dir, raising=True)
    monkeypatch.setattr(_cfg, "CONFIG_FILE", cfg_file, raising=True)
    monkeypatch.setattr(_cfg, "PROJECTS_DIR", oc_dir / "workspaces" / "projects", raising=True)
    monkeypatch.setattr(_cfg, "TRACES_DIR", oc_dir / "traces", raising=True)
    monkeypatch.setattr(_cfg, "MODEL_REGISTRY_FILE", oc_dir / "docket-models.json", raising=True)
    monkeypatch.setattr(_cfg, "DOCKET_HOME", oc_dir, raising=True)
    monkeypatch.setattr(_cfg, "APPROVALS_DIR", oc_dir / "approvals", raising=True)
    monkeypatch.setattr(_cfg, "AUDIT_LOG", oc_dir / "audit.log", raising=True)
    monkeypatch.setattr(_oc, "CONFIG_FILE", cfg_file, raising=True)
    monkeypatch.setattr(_oc, "meta_path", _cfg.meta_path, raising=True)


def _write_meta(member_id: str, extra: dict[str, Any] | None = None) -> None:
    ws = _cfg.PROJECTS_DIR / member_id
    ws.mkdir(parents=True, exist_ok=True)
    meta: dict[str, Any] = {
        "schemaVersion": 1,
        "kind": "project",
        "scope": "project",
        "role": member_id.split("-")[-1],
        "name": member_id,
        "codebase": str(ws),
        "model": "anthropic/claude-haiku-4-5",
        "modelSource": "policy",
        "sessionKey": f"agent:{member_id}:default",
        "projectKey": "default",
        "created": "2026-07-30T00:00:00+00:00",
    }
    if extra:
        meta.update(extra)
    (ws / ".docket-meta.json").write_text(json.dumps(meta))
    _oc.add_agent(member_id, meta["model"], meta["sessionKey"], "default")


def _seed_lean_pod(project: str = "myapp", lead_extra: dict[str, Any] | None = None) -> None:
    _write_meta(f"{project}-lead", lead_extra)
    _write_meta(f"{project}-implementer")


def _seed_full_pod(project: str = "myapp", lead_extra: dict[str, Any] | None = None) -> None:
    _write_meta(f"{project}-lead", lead_extra)
    _write_meta(f"{project}-implementer")
    _write_meta(f"{project}-reviewer")
    _write_meta(f"{project}-tester")


def _trace_events(project: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    traces_dir = _cfg.TRACES_DIR / project
    if not traces_dir.is_dir():
        return events
    for f in traces_dir.glob("*.jsonl"):
        events.extend(_trace.read_trace(f))
    return events


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
    ) -> _oc.AgentRunResult:
        self.calls.append(agent_id.rsplit("-", 1)[-1])
        return _oc.AgentRunResult(self.ok, f"done by {agent_id}", self.cost, {"output": "x"})


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
    ) -> _oc.AgentRunResult:
        role = agent_id.rsplit("-", 1)[-1]
        self.calls.append(role)
        if role == "tester":
            output = "PASS - looks good"
        elif role == "reviewer":
            output = "APPROVE - looks good"
        else:
            output = f"done by {agent_id}"
        return _oc.AgentRunResult(True, output, 0.01, {"output": output})


class _OneReworkThenGateAgainRunner:
    """Implementer/Lead succeed; Reviewer REQUEST-CHANGES exactly once, then
    APPROVE; Tester PASS. Used to prove the gate re-fires on the rework hop."""

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
    ) -> _oc.AgentRunResult:
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
        return _oc.AgentRunResult(True, output, 0.01, {"output": output})


# ── pod-level gate source + the G-2/W-1/W-2 seams ────────────────────────────────


class TestGateSources:
    def test_pod_requires_approval_matches_configured_role(self) -> None:
        _seed_lean_pod(lead_extra={"requireApprovalRoles": "implementer"})
        assert _dispatch._pod_requires_approval("myapp", "implementer") is True
        assert _dispatch._pod_requires_approval("myapp", "lead") is False

    def test_pod_requires_approval_case_and_whitespace_insensitive(self) -> None:
        _seed_lean_pod(lead_extra={"requireApprovalRoles": " Implementer , Reviewer "})
        assert _dispatch._pod_requires_approval("myapp", "implementer") is True
        assert _dispatch._pod_requires_approval("myapp", "reviewer") is True
        assert _dispatch._pod_requires_approval("myapp", "tester") is False

    def test_pod_requires_approval_blank_gates_nothing(self) -> None:
        _seed_lean_pod()
        assert _dispatch._pod_requires_approval("myapp", "implementer") is False

    def test_policy_seam_always_false(self) -> None:
        assert _dispatch._policy_requires_approval("myapp", "implementer", {}) is False

    def test_pipeline_step_seam_is_now_wired(self) -> None:
        """W-2 fills this seam: it used to ignore its arguments and always
        return False (see G-1's changelog). It now genuinely reflects the
        current pipeline position's *resolved* gate — real for any step
        whose gate is `approval` (declared directly, or via an archetype's
        gateContract), regardless of role name."""
        assert _dispatch._pipeline_step_requires_approval(None) is False
        assert _dispatch._pipeline_step_requires_approval(_pipeline.MechanicalGate()) is False
        assert _dispatch._pipeline_step_requires_approval(_pipeline.ApprovalGate()) is True

    def test_hop_requires_approval_is_an_or_of_all_sources(self) -> None:
        _seed_lean_pod(lead_extra={"requireApprovalRoles": "implementer"})
        assert _dispatch._hop_requires_approval("myapp", "implementer", {}, 1, None) is True
        assert _dispatch._hop_requires_approval("myapp", "lead", {}, 0, None) is False

    def test_hop_requires_approval_fires_from_pipeline_gate_alone(self) -> None:
        """A step with no pod-level/policy source still gates when its own
        resolved gate is `approval` — the W-2 seam operating independently
        of the pod-level `requireApprovalRoles` source."""
        _seed_lean_pod()
        assert (
            _dispatch._hop_requires_approval(
                "myapp", "implementer", {}, 1, _pipeline.ApprovalGate()
            )
            is True
        )


# ── the gate fires pre-hop ────────────────────────────────────────────────────────


class TestGateFiresPreHop:
    def test_gate_stops_before_the_gated_hop_runs(self) -> None:
        _seed_lean_pod(lead_extra={"requireApprovalRoles": "implementer"})
        _dispatch.enqueue_task("myapp", "Ship it")
        runner = _RecordingRunner()
        results = _dispatch.dispatch_pod("myapp", runner=runner)
        assert len(results) == 1
        assert results[0].status == "waiting_approval"
        # Lead ran (not gated); the implementer's turn never happened.
        assert runner.calls == ["lead"]

    def test_waiting_approval_persists_token_and_pipeline_position(self) -> None:
        _seed_lean_pod(lead_extra={"requireApprovalRoles": "implementer"})
        _dispatch.enqueue_task("myapp", "Ship it")
        _dispatch.dispatch_pod("myapp", runner=_RecordingRunner())

        task = _dispatch.read_tasks("myapp")[0]
        assert task["status"] == "waiting_approval"
        assert task["claimId"] is None
        assert task["approvalToken"]
        assert task["approvalToken"].startswith("apr-")
        # Lean pod pipeline is [lead, implementer] -> implementer is index 1.
        assert task["pendingApprovalIndex"] == 1
        # Only the lead hop is on record; the implementer hop never ran.
        assert [h["role"] for h in task["hops"]] == ["lead"]

    def test_gate_creates_a_real_approval_record(self) -> None:
        _seed_lean_pod(lead_extra={"requireApprovalRoles": "implementer"})
        task = _dispatch.enqueue_task("myapp", "Ship it")
        _dispatch.dispatch_pod("myapp", runner=_RecordingRunner())

        stored = _dispatch.read_tasks("myapp")[0]
        token = stored["approvalToken"]
        pending = _ap.list_pending()
        assert any(p["token"] == token for p in pending)
        rec = _ap.approval_get(token)
        assert rec["project"] == "myapp"
        assert rec["role"] == "implementer"
        assert rec["state"] == "pending"
        assert rec["context"] == {"taskId": task["id"], "pipelineIndex": 1}

    def test_approval_required_trace_event_emitted(self) -> None:
        _seed_lean_pod(lead_extra={"requireApprovalRoles": "implementer"})
        _dispatch.enqueue_task("myapp", "Ship it")
        _dispatch.dispatch_pod("myapp", runner=_RecordingRunner())

        events = _trace_events("myapp")
        gate_events = [e for e in events if e["event_type"] == "approval_required"]
        assert len(gate_events) == 1
        assert gate_events[0]["payload"]["role"] == "implementer"

    def test_pod_with_no_gated_roles_is_unaffected(self) -> None:
        _seed_lean_pod()
        _dispatch.enqueue_task("myapp", "Ship it")
        runner = _RecordingRunner()
        results = _dispatch.dispatch_pod("myapp", runner=runner)
        assert results[0].status == "done"
        assert runner.calls == ["lead", "implementer"]


# ── waiting_approval is invisible to every claim path ────────────────────────────


class TestNotClaimableConcurrently:
    def test_second_dispatch_pod_call_does_not_reclaim_it(self) -> None:
        _seed_lean_pod(lead_extra={"requireApprovalRoles": "implementer"})
        _dispatch.enqueue_task("myapp", "Ship it")
        _dispatch.dispatch_pod("myapp", runner=_RecordingRunner())
        assert _dispatch.read_tasks("myapp")[0]["status"] == "waiting_approval"

        runner2 = _RecordingRunner()
        results = _dispatch.dispatch_pod("myapp", runner=runner2)
        assert results == []
        assert runner2.calls == []
        assert _dispatch.read_tasks("myapp")[0]["status"] == "waiting_approval"

    def test_claim_next_task_directly_returns_none(self) -> None:
        _seed_lean_pod(lead_extra={"requireApprovalRoles": "implementer"})
        _dispatch.enqueue_task("myapp", "Ship it")
        _dispatch.dispatch_pod("myapp", runner=_RecordingRunner())

        assert _dispatch._claim_next_task("myapp", resume=False) is None
        # --resume only ever reclaims a stale_claim failure, never a
        # waiting_approval task.
        assert _dispatch._claim_next_task("myapp", resume=True) is None

    def test_stale_claim_sweep_does_not_touch_a_waiting_approval_task(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_lean_pod(lead_extra={"requireApprovalRoles": "implementer"})
        _dispatch.enqueue_task("myapp", "Ship it")
        _dispatch.dispatch_pod("myapp", runner=_RecordingRunner())

        # Even if the stale-claim clock were somehow tripped, a
        # waiting_approval task has no claimedAt to go stale against — the
        # sweep only ever looks at status == "running".
        monkeypatch.setattr(_cfg, "CLAIM_STALE_TIMEOUT", -1, raising=True)
        _dispatch._sweep_stale_claims("myapp")
        assert _dispatch.read_tasks("myapp")[0]["status"] == "waiting_approval"


# ── grant resumes at the exact hop ────────────────────────────────────────────────


class TestGrantResumesAtHop:
    def _gate_then_grant(self) -> str:
        _seed_full_pod(lead_extra={"requireApprovalRoles": "implementer"})
        _dispatch.enqueue_task("myapp", "Ship it")
        _dispatch.dispatch_pod("myapp", runner=_RecordingRunner())
        token = _dispatch.read_tasks("myapp")[0]["approvalToken"]
        return token

    def test_resolve_waiting_approval_flips_to_pending_with_override(self) -> None:
        token = self._gate_then_grant()
        _ap.approval_grant(token, channel="cli")
        updated = _dispatch.resolve_waiting_approval(token, "granted")
        assert updated is True

        task = _dispatch.read_tasks("myapp")[0]
        assert task["status"] == "pending"
        assert task["approvalToken"] is None
        assert task["pendingApprovalIndex"] is None
        assert task["gateOverridePipelineIndex"] == 1

    def test_next_dispatch_continues_from_the_gated_hop(self) -> None:
        token = self._gate_then_grant()
        _ap.approval_grant(token, channel="cli")
        _dispatch.resolve_waiting_approval(token, "granted")

        runner = _VerdictAwareRunner()
        results = _dispatch.dispatch_pod("myapp", runner=runner)
        assert len(results) == 1
        assert results[0].status == "done"
        # The lead hop is NOT re-run; only implementer/reviewer/tester continue.
        assert runner.calls == ["implementer", "reviewer", "tester"]

        final = _dispatch.read_tasks("myapp")[0]
        assert [h["role"] for h in final["hops"]] == [
            "lead",
            "implementer",
            "reviewer",
            "tester",
        ]
        assert final["approvalToken"] is None
        assert final["gateOverridePipelineIndex"] is None

    def test_grant_via_cli_approve_resumes_dispatch(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        token = self._gate_then_grant()
        rc = _approve.run_approve(token)
        assert rc == 0
        capsys.readouterr()

        task = _dispatch.read_tasks("myapp")[0]
        assert task["status"] == "pending"
        assert task["gateOverridePipelineIndex"] == 1

        runner = _VerdictAwareRunner()
        results = _dispatch.dispatch_pod("myapp", runner=runner)
        assert results[0].status == "done"
        assert runner.calls == ["implementer", "reviewer", "tester"]

    def test_grant_on_a_non_dispatch_token_is_a_harmless_noop(self) -> None:
        token = _ap.approval_create("someproj", "programmer", "rm -rf /tmp/x")
        _ap.approval_grant(token, channel="cli")
        assert _dispatch.resolve_waiting_approval(token, "granted") is False

    def test_resolve_waiting_approval_unknown_token_returns_false(self) -> None:
        assert _dispatch.resolve_waiting_approval("apr-does-not-exist", "granted") is False


# ── deny fails the task terminally ───────────────────────────────────────────────


class TestDenyFailsTerminally:
    def _gate(self) -> str:
        _seed_lean_pod(lead_extra={"requireApprovalRoles": "implementer"})
        _dispatch.enqueue_task("myapp", "Ship it")
        _dispatch.dispatch_pod("myapp", runner=_RecordingRunner())
        return str(_dispatch.read_tasks("myapp")[0]["approvalToken"])

    def test_resolve_waiting_approval_fails_task_immediately(self) -> None:
        token = self._gate()
        _ap.approval_deny(token, channel="cli")
        updated = _dispatch.resolve_waiting_approval(token, "denied")
        assert updated is True

        task = _dispatch.read_tasks("myapp")[0]
        assert task["status"] == "failed"
        assert task["failureKind"] == "approval_denied"
        assert task["reason"] == "approval denied"
        assert task["approvalToken"] is None
        assert task["pendingApprovalIndex"] is None
        assert task["completedAt"]

    def test_denied_task_is_never_reclaimed_even_with_resume(self) -> None:
        token = self._gate()
        _ap.approval_deny(token, channel="cli")
        _dispatch.resolve_waiting_approval(token, "denied")

        runner = _RecordingRunner()
        results = _dispatch.dispatch_pod("myapp", runner=runner, resume=True)
        assert results == []
        assert runner.calls == []
        assert _dispatch.read_tasks("myapp")[0]["status"] == "failed"

    def test_deny_via_cli_deny_fails_dispatch_task(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        token = self._gate()
        rc = _deny.run_deny(token)
        assert rc == 0
        capsys.readouterr()

        task = _dispatch.read_tasks("myapp")[0]
        assert task["status"] == "failed"
        assert task["failureKind"] == "approval_denied"

    def test_deny_trace_event_emitted(self) -> None:
        token = self._gate()
        _ap.approval_deny(token, channel="cli")
        _dispatch.resolve_waiting_approval(token, "denied")

        events = _trace_events("myapp")
        assert any(e["event_type"] == "approval_task_denied" for e in events)


# ── expiry sweep resolves to denied (fail-closed) ────────────────────────────────


class TestExpirySweepDenies:
    def test_sweep_marks_stale_pending_approval_denied(self) -> None:
        token = _ap.approval_create("someproj", "programmer", "rm -rf /tmp/x")
        rec = _ap.approval_get(token)
        rec["created"] = "2000-01-01T00:00:00Z"
        _cfg.APPROVALS_DIR.joinpath(f"{token}.json").write_text(json.dumps(rec))

        swept = _ap.approval_sweep_expired()
        assert swept == 1
        assert _ap.approval_get(token)["state"] == "denied"

    def test_sweep_writes_timeout_channel_audit_entry(self) -> None:
        token = _ap.approval_create("someproj", "programmer", "rm -rf /tmp/x")
        rec = _ap.approval_get(token)
        rec["created"] = "2000-01-01T00:00:00Z"
        _cfg.APPROVALS_DIR.joinpath(f"{token}.json").write_text(json.dumps(rec))

        _ap.approval_sweep_expired()
        entries = [
            json.loads(line) for line in _cfg.AUDIT_LOG.read_text().splitlines() if line.strip()
        ]
        assert any(
            e["action"] == "approval.deny"
            and "channel=timeout" in e["detail"]
            and token in e["detail"]
            for e in entries
        )

    def test_sweep_fails_the_waiting_dispatch_task(self) -> None:
        _seed_lean_pod(lead_extra={"requireApprovalRoles": "implementer"})
        _dispatch.enqueue_task("myapp", "Ship it")
        _dispatch.dispatch_pod("myapp", runner=_RecordingRunner())
        token = str(_dispatch.read_tasks("myapp")[0]["approvalToken"])

        rec = _ap.approval_get(token)
        rec["created"] = "2000-01-01T00:00:00Z"
        _cfg.APPROVALS_DIR.joinpath(f"{token}.json").write_text(json.dumps(rec))

        swept = _ap.approval_sweep_expired()
        assert swept == 1

        task = _dispatch.read_tasks("myapp")[0]
        assert task["status"] == "failed"
        assert task["failureKind"] == "approval_denied"


# ── HTTP POST /approvals/<token> genuinely resumes/kills ─────────────────────────

_TEST_TOKEN = "test-serve-token-g1-xyz789"


@pytest.fixture()
def live_server() -> Any:
    class _Handler(_DocketHandler):
        serve_token = _TEST_TOKEN

    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
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
        _seed_full_pod(lead_extra={"requireApprovalRoles": "implementer"})
        _dispatch.enqueue_task("myapp", "Ship it")
        _dispatch.dispatch_pod("myapp", runner=_RecordingRunner())
        token = str(_dispatch.read_tasks("myapp")[0]["approvalToken"])

        status, body = _post(f"{live_server}/approvals/{token}", {"action": "grant"}, _TEST_TOKEN)
        assert status == 200
        assert body["state"] == "granted"

        task = _dispatch.read_tasks("myapp")[0]
        assert task["status"] == "pending"
        assert task["gateOverridePipelineIndex"] == 1

        runner = _VerdictAwareRunner()
        results = _dispatch.dispatch_pod("myapp", runner=runner)
        assert results[0].status == "done"
        assert runner.calls == ["implementer", "reviewer", "tester"]

    def test_post_deny_fails_the_dispatch_task(self, live_server: str) -> None:
        _seed_lean_pod(lead_extra={"requireApprovalRoles": "implementer"})
        _dispatch.enqueue_task("myapp", "Ship it")
        _dispatch.dispatch_pod("myapp", runner=_RecordingRunner())
        token = str(_dispatch.read_tasks("myapp")[0]["approvalToken"])

        status, body = _post(f"{live_server}/approvals/{token}", {"action": "deny"}, _TEST_TOKEN)
        assert status == 200
        assert body["state"] == "denied"

        task = _dispatch.read_tasks("myapp")[0]
        assert task["status"] == "failed"
        assert task["failureKind"] == "approval_denied"


# ── the single-use override is consumed exactly once ─────────────────────────────


class TestReworkReGatesAfterResume:
    def test_rework_cycle_re_gates_the_second_implementer_hop(self) -> None:
        _seed_full_pod(lead_extra={"requireApprovalRoles": "implementer"})
        _dispatch.enqueue_task("myapp", "Ship it")
        _dispatch.dispatch_pod("myapp", runner=_RecordingRunner())
        first_token = str(_dispatch.read_tasks("myapp")[0]["approvalToken"])
        assert first_token

        _ap.approval_grant(first_token, channel="cli")
        _dispatch.resolve_waiting_approval(first_token, "granted")

        runner = _OneReworkThenGateAgainRunner()
        results = _dispatch.dispatch_pod("myapp", runner=runner)
        assert len(results) == 1
        # The override cleared the gate for the FIRST implementer hop only;
        # the Reviewer's REQUEST-CHANGES sends it back to the Implementer a
        # second time, and that second hop gates again (a fresh token).
        assert results[0].status == "waiting_approval"
        assert runner.calls == ["implementer", "reviewer"]

        second_task = _dispatch.read_tasks("myapp")[0]
        second_token = second_task["approvalToken"]
        assert second_token
        assert second_token != first_token
        assert second_task["pendingApprovalIndex"] == 1  # same implementer index

        # Grant the second gate too and let the task finish.
        _ap.approval_grant(second_token, channel="cli")
        _dispatch.resolve_waiting_approval(second_token, "granted")
        final_runner = _OneReworkThenGateAgainRunner()
        final_runner._reviewer_calls = 1  # next reviewer call approves
        final_results = _dispatch.dispatch_pod("myapp", runner=final_runner)
        assert final_results[0].status == "done"


# ── budget still checked before approval (affordability before permission) ──────


class TestBudgetGateTakesPrecedence:
    def test_budget_blocked_hop_never_reaches_the_approval_gate(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_lean_pod(lead_extra={"requireApprovalRoles": "implementer"})
        _dispatch.enqueue_task("myapp", "Too expensive")
        monkeypatch.setattr(_dispatch, "pod_budget", lambda _p: 1.0)
        monkeypatch.setattr(_dispatch, "pod_recorded_cost", lambda _p: 5.0)

        results = _dispatch.dispatch_pod("myapp", runner=_RecordingRunner())
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
