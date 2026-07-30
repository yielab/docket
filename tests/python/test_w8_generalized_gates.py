"""W-8: generalized gates, exercised through the real R-1 state machine.

`core/dispatch.py`'s gate execution reads a step's *resolved* gate — its own
declared `gate`, or (only when a step omits one) its archetype's
`gateContract` — instead of branching on a hardcoded role name. Covers, via
`dispatch_task`/`dispatch_pod` with a custom `PipelineSpec` (never the
built-in default, which is covered byte-for-byte by the pre-existing
test_dispatch.py/test_r2/test_r4/test_r5/test_cd2/test_g1 suites):

  * a `mechanical` gate on a non-"implementer" role gets the same
    worktree-aware cwd resolution the implementer always has (W-8's "cwd
    resolves from workspace kind", generalized beyond one hardcoded role);
  * a `verdict` gate on a non-built-in (starter-library) archetype gates
    exactly like reviewer/tester always have, with the new generic W-8 trace
    event names;
  * a pipeline-declared `approval` step genuinely gates pre-hop — the G-1
    seam (`_pipeline_step_requires_approval`) W-2 fills — and a grant resumes
    it the same way the pod-level `requireApprovalRoles` source always has;
  * a `parallel` group actually runs its children concurrently through the
    real state machine and joins (all successful) or fails (any child fails)
    before the task advances.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import docket.config as _cfg
from docket.core import approval as _ap
from docket.core import dispatch as _dispatch
from docket.core import pipeline as _pipeline
from docket.core import runtime_driver as _rd
from docket.core import trace as _trace
from docket.edges.adapters import openclaw as _oc


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DOCKET_NO_RESTART", "1")
    monkeypatch.setenv("DOCKET_SERVICE_MANAGER", "none")
    monkeypatch.setenv("DOCKET_NO_TRACE", "0")

    oc_dir = tmp_path / ".openclaw"
    (oc_dir / "workspaces" / "projects").mkdir(parents=True)
    cfg_file = oc_dir / "openclaw.json"
    cfg_file.write_text(json.dumps({"agents": {"list": []}, "bindings": [], "channels": {}}))

    monkeypatch.setattr(_cfg, "OPENCLAW_DIR", oc_dir, raising=True)
    monkeypatch.setattr(_cfg, "CONFIG_FILE", cfg_file, raising=True)
    monkeypatch.setattr(_cfg, "PROJECTS_DIR", oc_dir / "workspaces" / "projects", raising=True)
    monkeypatch.setattr(_cfg, "TRACES_DIR", oc_dir / "traces", raising=True)
    monkeypatch.setattr(_cfg, "MODEL_REGISTRY_FILE", oc_dir / "docket-models.json", raising=True)
    monkeypatch.setattr(_oc, "CONFIG_FILE", cfg_file, raising=True)
    monkeypatch.setattr(_oc, "meta_path", _cfg.meta_path, raising=True)


def _write_meta(member_id: str, extra: dict[str, Any] | None = None) -> None:
    ws = _cfg.PROJECTS_DIR / member_id
    ws.mkdir(parents=True, exist_ok=True)
    meta: dict[str, Any] = {
        "schemaVersion": 1,
        "kind": "project",
        "scope": "project",
        "role": member_id.rsplit("-", 1)[-1],
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


def _trace_events(project: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    traces_dir = _cfg.TRACES_DIR / project
    if not traces_dir.is_dir():
        return events
    for f in traces_dir.glob("*.jsonl"):
        events.extend(_trace.read_trace(f))
    return events


class _RoleRunner:
    """Canned output keyed by role (an agent id's last non-numeric segment)."""

    def __init__(self, outputs: dict[str, str]) -> None:
        self.outputs = outputs
        self.calls: list[tuple[str, str, str, int, dict[str, str] | None]] = []

    def __call__(
        self,
        agent_id: str,
        session_key: str,
        message: str,
        timeout: int,
        env: dict[str, str] | None = None,
    ) -> Any:
        self.calls.append((agent_id, session_key, message, timeout, env))
        tail = agent_id.rsplit("-", 1)[-1]
        role = agent_id.rsplit("-", 2)[-2] if tail.isdigit() else tail
        output = self.outputs.get(role, f"done by {agent_id}")
        return _rd.TurnResult(True, output, 0.01, {"output": output})


# ── mechanical gate, generalized beyond "implementer" ────────────────────────


class TestMechanicalGateGeneralized:
    def test_non_implementer_role_runs_its_verify_cmd_and_passes(self) -> None:
        _write_meta("myapp-lead")
        _write_meta("myapp-operator", {"verifyCmd": "true"})
        spec = _pipeline.PipelineSpec(
            name="ops",
            steps=[
                _pipeline.Step(id="plan", role="lead"),
                _pipeline.Step(
                    id="apply", role="operator", gate=_pipeline.MechanicalGate(command=None)
                ),
            ],
        )
        task: dict[str, Any] = {"id": "m1", "description": "work", "status": "pending"}
        res = _dispatch.dispatch_task("myapp", task, runner=_RoleRunner({}), spec=spec)
        assert res.status == "done"
        assert [h.role for h in res.hops] == ["lead", "operator"]

    def test_non_implementer_role_verify_cmd_failure_fails_the_task(self) -> None:
        _write_meta("myapp-lead")
        _write_meta("myapp-operator", {"verifyCmd": "false"})
        spec = _pipeline.PipelineSpec(
            name="ops",
            steps=[
                _pipeline.Step(id="plan", role="lead"),
                _pipeline.Step(
                    id="apply", role="operator", gate=_pipeline.MechanicalGate(command=None)
                ),
            ],
        )
        task: dict[str, Any] = {"id": "m2", "description": "work", "status": "pending"}
        res = _dispatch.dispatch_task("myapp", task, runner=_RoleRunner({}), spec=spec)
        assert res.status == "failed"
        assert "verifyCmd failed" in res.reason
        events = _trace_events("myapp")
        assert any(e["event_type"] == "verification_failed" for e in events)

    def test_gates_own_literal_command_bypasses_member_verify_cmd_meta(self) -> None:
        """A step's `gate.command` (when set) is used directly — it doesn't
        need the target member to have its own `verifyCmd` meta at all."""
        _write_meta("myapp-lead")
        _write_meta("myapp-operator")  # no verifyCmd meta set
        spec = _pipeline.PipelineSpec(
            name="ops",
            steps=[
                _pipeline.Step(id="plan", role="lead"),
                _pipeline.Step(
                    id="apply", role="operator", gate=_pipeline.MechanicalGate(command="true")
                ),
            ],
        )
        task: dict[str, Any] = {"id": "m3", "description": "work", "status": "pending"}
        res = _dispatch.dispatch_task("myapp", task, runner=_RoleRunner({}), spec=spec)
        assert res.status == "done"


# ── verdict gate on a non-built-in archetype ─────────────────────────────────


class TestVerdictGateGeneralized:
    @staticmethod
    def _spec() -> _pipeline.PipelineSpec:
        return _pipeline.PipelineSpec(
            name="content",
            steps=[
                _pipeline.Step(id="plan", role="lead"),
                # No gate declared -> falls back to the "critic" starter
                # archetype's own gateContract (verdict: APPROVE/REJECT).
                _pipeline.Step(id="review", role="critic"),
            ],
        )

    def test_approve_advances_and_completes(self) -> None:
        _write_meta("myapp-lead")
        _write_meta("myapp-critic")
        runner = _RoleRunner({"critic": "APPROVE\nlooks good"})
        task: dict[str, Any] = {"id": "v1", "description": "work", "status": "pending"}
        res = _dispatch.dispatch_task("myapp", task, runner=runner, spec=self._spec())
        assert res.status == "done"

    def test_reject_fails_the_task_with_generic_event(self) -> None:
        _write_meta("myapp-lead")
        _write_meta("myapp-critic")
        runner = _RoleRunner({"critic": "REJECT\nneeds work"})
        task: dict[str, Any] = {"id": "v2", "description": "work", "status": "pending"}
        res = _dispatch.dispatch_task("myapp", task, runner=runner, spec=self._spec())
        assert res.status == "failed"
        assert "REJECT" in res.reason
        events = _trace_events("myapp")
        assert any(e["event_type"] == "verdict_rejected" for e in events)
        # The two built-in-only legacy event names must never leak onto a
        # non-built-in role's verdict outcome.
        assert not any(e["event_type"] == "review_rejected" for e in events)

    def test_unparseable_output_fails_with_generic_event(self) -> None:
        _write_meta("myapp-lead")
        _write_meta("myapp-critic")
        runner = _RoleRunner({"critic": "not sure about this one"})
        task: dict[str, Any] = {"id": "v3", "description": "work", "status": "pending"}
        res = _dispatch.dispatch_task("myapp", task, runner=runner, spec=self._spec())
        assert res.status == "failed"
        assert "unparseable" in res.reason
        events = _trace_events("myapp")
        assert any(e["event_type"] == "verdict_unparseable" for e in events)


# ── a pipeline `approval` step genuinely gates (the W-1/W-2 seam) ────────────


class TestPipelineApprovalStepGatesGenuinely:
    @staticmethod
    def _spec() -> _pipeline.PipelineSpec:
        return _pipeline.PipelineSpec(
            name="deploy",
            steps=[
                _pipeline.Step(id="plan", role="lead"),
                _pipeline.Step(
                    id="ship",
                    role="implementer",
                    gate=_pipeline.ApprovalGate(message="Ready to deploy?"),
                ),
            ],
        )

    def test_gate_stops_before_the_gated_hop_runs(self) -> None:
        _write_meta("myapp-lead")
        _write_meta("myapp-implementer")
        _dispatch.enqueue_task("myapp", "Ship it")
        runner = _RoleRunner({})
        results = _dispatch.dispatch_pod("myapp", runner=runner, spec=self._spec())
        assert len(results) == 1
        assert results[0].status == "waiting_approval"
        assert results[0].approval_token
        assert [c[0].rsplit("-", 1)[-1] for c in runner.calls] == ["lead"]

        rec = _ap.approval_get(results[0].approval_token)
        assert rec["project"] == "myapp"
        assert rec["role"] == "implementer"

    def test_grant_resumes_and_completes_without_pod_level_config(self) -> None:
        """No `requireApprovalRoles` Lead-meta is set anywhere — the gate
        fires purely from the pipeline step's own resolved gate."""
        _write_meta("myapp-lead")
        _write_meta("myapp-implementer")
        _dispatch.enqueue_task("myapp", "Ship it")
        spec = self._spec()
        _dispatch.dispatch_pod("myapp", runner=_RoleRunner({}), spec=spec)
        token = _dispatch.read_tasks("myapp")[0]["approvalToken"]
        assert token

        _ap.approval_grant(token, channel="cli")
        assert _dispatch.resolve_waiting_approval(token, "granted") is True
        assert _dispatch.read_tasks("myapp")[0]["status"] == "pending"

        runner2 = _RoleRunner({})
        results = _dispatch.dispatch_pod("myapp", runner=runner2, spec=spec)
        assert results[0].status == "done"
        # The lead hop is not re-run; only the gated implementer hop runs now.
        assert [c[0].rsplit("-", 1)[-1] for c in runner2.calls] == ["implementer"]

    def test_deny_fails_the_task_terminally(self) -> None:
        _write_meta("myapp-lead")
        _write_meta("myapp-implementer")
        _dispatch.enqueue_task("myapp", "Ship it")
        spec = self._spec()
        _dispatch.dispatch_pod("myapp", runner=_RoleRunner({}), spec=spec)
        token = _dispatch.read_tasks("myapp")[0]["approvalToken"]

        _ap.approval_deny(token, channel="cli")
        assert _dispatch.resolve_waiting_approval(token, "denied") is True

        task = _dispatch.read_tasks("myapp")[0]
        assert task["status"] == "failed"
        assert task["failureKind"] == "approval_denied"


# ── parallel group: real concurrent execution + join semantics ──────────────


class TestParallelGroupThroughDispatch:
    def test_both_children_run_and_the_group_joins_before_advancing(self) -> None:
        _write_meta("myapp-lead")
        _write_meta("myapp-implementer")
        _write_meta("myapp-implementer-2", {"role": "implementer"})
        _write_meta("myapp-tester")
        spec = _pipeline.PipelineSpec(
            name="fanout",
            steps=[
                _pipeline.Step(id="plan", role="lead"),
                _pipeline.Step(
                    id="build",
                    parallel=[
                        _pipeline.Step(id="impl-a", agent="myapp-implementer"),
                        _pipeline.Step(id="impl-b", agent="myapp-implementer-2"),
                    ],
                ),
                _pipeline.Step(
                    id="check",
                    role="tester",
                    gate=_pipeline.VerdictGate(pattern=r"^(PASS|FAIL)\b", pass_values=["pass"]),
                ),
            ],
        )
        _dispatch.enqueue_task("myapp", "Ship it")
        runner = _RoleRunner({"tester": "PASS\nall good"})
        results = _dispatch.dispatch_pod("myapp", runner=runner, spec=spec)
        assert results[0].status == "done"

        # Both fan-out children ran (an agent-targeted child's hop role is
        # its agent id — there's no separate "role name" for a bare
        # `agent:` target) ...
        agents_called = [c[0] for c in runner.calls]
        assert agents_called.count("myapp-implementer") == 1
        assert agents_called.count("myapp-implementer-2") == 1
        # ... and only *after* the group joined does the tester run.
        assert agents_called[-1] == "myapp-tester"

        persisted = _dispatch.read_tasks("myapp")[0]
        assert [h["stepId"] for h in persisted["hops"]] == [
            "plan",
            "impl-a",
            "impl-b",
            "check",
        ]

    def test_one_failing_child_fails_the_whole_group(self) -> None:
        _write_meta("myapp-lead")
        _write_meta("myapp-implementer")
        _write_meta("myapp-implementer-2", {"role": "implementer"})
        spec = _pipeline.PipelineSpec(
            name="fanout",
            steps=[
                _pipeline.Step(id="plan", role="lead"),
                _pipeline.Step(
                    id="build",
                    parallel=[
                        _pipeline.Step(id="impl-a", agent="myapp-implementer"),
                        _pipeline.Step(
                            id="impl-b",
                            agent="myapp-implementer-2",
                            gate=_pipeline.MechanicalGate(command="false"),
                        ),
                    ],
                ),
            ],
        )
        _dispatch.enqueue_task("myapp", "Ship it")
        results = _dispatch.dispatch_pod("myapp", runner=_RoleRunner({}), spec=spec)
        assert results[0].status == "failed"
        # Both children still ran (and persisted) despite one failing.
        persisted = _dispatch.read_tasks("myapp")[0]
        assert [h["stepId"] for h in persisted["hops"]] == ["plan", "impl-a", "impl-b"]

    def test_approval_gate_inside_a_group_is_a_clear_configuration_error(self) -> None:
        """Documented scope boundary: a parallel group's children are not
        individually approval-gated (see core/orchestrator.py's module note).
        A child whose resolved gate is `approval` fails clearly rather than
        attempting fragile mid-group human-approval semantics."""
        _write_meta("myapp-lead")
        _write_meta("myapp-implementer")
        spec = _pipeline.PipelineSpec(
            name="fanout",
            steps=[
                _pipeline.Step(id="plan", role="lead"),
                _pipeline.Step(
                    id="build",
                    parallel=[
                        _pipeline.Step(
                            id="impl-a",
                            agent="myapp-implementer",
                            gate=_pipeline.ApprovalGate(),
                        ),
                    ],
                ),
            ],
        )
        task: dict[str, Any] = {"id": "g1", "description": "work", "status": "pending"}
        res = _dispatch.dispatch_task("myapp", task, runner=_RoleRunner({}), spec=spec)
        assert res.status == "failed"
        assert "not supported inside a parallel group" in res.reason
