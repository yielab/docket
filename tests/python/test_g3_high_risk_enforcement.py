"""High-risk classes enforced on docket-launched processes.

Before this card, ``core/security.py``'s ``HIGH_RISK_PATTERNS`` classifier had
callers only in tests (``test_m5_gates_policy.py``). A classifier nothing calls
is documentation, not enforcement -- the same defect shape G-1/G-2 fixed for
the approval store and the policy engine.

``match_high_risk`` is what this card wired, and it is what survived. Three
sibling helpers that composed it -- ``high_risk_bins``, ``is_high_risk`` and
``resolve_command_action`` -- were deleted on merge rather than left beside it:
none had a production caller, because they modelled an ask/allow decision the
daemon's exec gate owns and docket cannot reach (D-15). This suite exercises
the two real wiring points that remain:

  * TestRunVerifyCmdHighRisk  -- ``edges/adapters/system.py``'s
    ``run_verify_cmd`` is the one docket-launched subprocess built from a
    fully free-form, operator-composed command string run through a real
    shell (every other call in that module is a fixed argv list it built
    itself -- not a comparable classification target, see
    ``security-gates.spec.md``). A high-risk match now fails closed: the
    shell command is never started at all.
  * TestPreOutputHighRiskClassification -- ``core/dispatch.py``'s
    ``pre_output`` guardrail scan (G-2) now also classifies a hop's real
    output against the same built-in list, independently of the JSON policy
    engine (whose shipped ``high-risk-*.json`` templates are hooked on
    ``pre_tool_call``, which docket never evaluates -- D-15). A match never
    downgrades an existing, stronger policy_eval_detail verdict; it only
    raises a bare "allow" to "warn" -- visibility only, since HIGH_RISK_PATTERNS
    is a built-in list, not an operator-authored policy (FD-3).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

import docket.config as _cfg
from docket.core import dispatch as _dispatch
from docket.core import fleet as _fleet
from docket.core import runtime_driver as _rd
from docket.core import trace as _trace
from docket.edges.adapters import system as _sys

# ── system adapter: run_verify_cmd's own high-risk guard ─────────────────────


class TestRunVerifyCmdHighRisk:
    def test_money_movement_command_never_runs(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _boom(*a: Any, **k: Any) -> Any:
            raise AssertionError("subprocess.run must not be called for a high-risk command")

        monkeypatch.setattr(subprocess, "run", _boom)
        passed, output = _sys.run_verify_cmd("stripe charge customer --amount 500", str(tmp_path))
        assert passed is False
        assert "money-movement" in output
        assert "docket gates classes" in output

    def test_prod_deploy_command_never_runs(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _boom(*a: Any, **k: Any) -> Any:
            raise AssertionError("subprocess.run must not be called for a high-risk command")

        monkeypatch.setattr(subprocess, "run", _boom)
        passed, output = _sys.run_verify_cmd("git push origin production", str(tmp_path))
        assert passed is False
        assert "prod-deploy" in output

    def test_secret_access_command_never_runs(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _boom(*a: Any, **k: Any) -> Any:
            raise AssertionError("subprocess.run must not be called for a high-risk command")

        monkeypatch.setattr(subprocess, "run", _boom)
        passed, output = _sys.run_verify_cmd("ssh-keygen -t ed25519 -N ''", str(tmp_path))
        assert passed is False
        assert "secret-access" in output

    def test_ordinary_verify_pipeline_is_unaffected(self, tmp_path: Path) -> None:
        """A realistic multi-command verify pipeline is not a false positive."""
        passed, output = _sys.run_verify_cmd(
            "echo building; echo testing && echo done", str(tmp_path)
        )
        assert passed is True
        assert "done" in output


# ── dispatch integration: pre_output high-risk classification ────────────────


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DOCKET_SERVICE_MANAGER", "none")

    home = tmp_path / ".docket"
    (home / "workspaces" / "projects").mkdir(parents=True)
    (home / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))

    monkeypatch.setattr(_cfg, "DOCKET_HOME", home, raising=True)
    monkeypatch.setattr(_cfg, "FLEET_FILE", home / "fleet.json", raising=True)
    monkeypatch.setattr(_cfg, "WORKSPACES_DIR", home / "workspaces", raising=True)
    monkeypatch.setattr(_cfg, "PROJECTS_DIR", home / "workspaces" / "projects", raising=True)
    monkeypatch.setattr(_cfg, "TRACES_DIR", home / "traces", raising=True)
    monkeypatch.setattr(_cfg, "MODEL_REGISTRY_FILE", home / "docket-models.json", raising=True)
    monkeypatch.setattr(_cfg, "POLICIES_DIR", home / "policies", raising=True)
    monkeypatch.setattr(_cfg, "APPROVALS_DIR", home / "approvals", raising=True)
    monkeypatch.setattr(_cfg, "AUDIT_LOG", home / "audit.log", raising=True)


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
    _fleet.add_agent(member_id, meta["model"], meta["sessionKey"], "default")


def _seed_lean_pod(project: str = "myapp") -> None:
    _write_meta(f"{project}-lead")
    _write_meta(f"{project}-implementer")


def _write_policy(
    policy_id: str,
    hook: str,
    pattern: str,
    action: str,
    *,
    applies_to: list[str] | None = None,
    message: str = "",
) -> None:
    _cfg.POLICIES_DIR.mkdir(parents=True, exist_ok=True)
    doc = {
        "id": policy_id,
        "description": f"test policy {policy_id}",
        "applies_to": applies_to or ["*"],
        "hook": hook,
        "match": {"type": "regex", "pattern": pattern},
        "action": action,
        "message": message,
    }
    (_cfg.POLICIES_DIR / f"{policy_id}.json").write_text(json.dumps(doc), encoding="utf-8")


def _trace_events(project: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    traces_dir = _cfg.TRACES_DIR / project
    if not traces_dir.is_dir():
        return events
    for f in traces_dir.glob("*.jsonl"):
        events.extend(_trace.read_trace(f))
    return events


class _RecordingRunner:
    """Stub matching agent_run's signature; returns a fixed output per role."""

    def __init__(self, outputs: dict[str, str] | None = None, *, ok: bool = True) -> None:
        self.calls: list[str] = []
        self.outputs = outputs or {}
        self.ok = ok

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
        output = self.outputs.get(role, f"done by {agent_id}")
        return _rd.TurnResult(self.ok, output, 0.01, {"output": output})


class TestPreOutputHighRiskClassification:
    def test_secret_access_output_gets_warn_classification(self) -> None:
        _seed_lean_pod()
        _dispatch.enqueue_task("myapp", "Rotate the deploy key")
        runner = _RecordingRunner({"lead": "ran ssh-keygen -t ed25519 to rotate the deploy key"})
        results = _dispatch.dispatch_pod("myapp", runner=runner)

        assert results[0].status == "done"
        lead_hop = next(h for h in results[0].hops if h.role == "lead")
        # Visibility only -- HIGH_RISK_PATTERNS is not user-authorable the way
        # an installed JSON policy is, so it never redacts/blocks by itself.
        assert lead_hop.output == "ran ssh-keygen -t ed25519 to rotate the deploy key"

        events = _trace_events("myapp")
        checks = [e for e in events if e["event_type"] == "guardrail_check"]
        assert any(
            e["payload"]["policy"] == "high-risk:secret-access" and e["payload"]["action"] == "warn"
            for e in checks
        )
        assert not any(e["event_type"] == "guardrail_block" for e in events)

    def test_money_movement_output_gets_warn_classification(self) -> None:
        _seed_lean_pod()
        _dispatch.enqueue_task("myapp", "Process the refund")
        runner = _RecordingRunner({"lead": "stripe charge customer for the annual invoice"})
        results = _dispatch.dispatch_pod("myapp", runner=runner)

        assert results[0].status == "done"
        events = _trace_events("myapp")
        checks = [e for e in events if e["event_type"] == "guardrail_check"]
        assert any(
            e["payload"]["policy"] == "high-risk:money-movement"
            and e["payload"]["action"] == "warn"
            for e in checks
        )

    def test_stronger_existing_policy_verdict_is_not_downgraded(self) -> None:
        """A real installed policy's block must win -- the built-in classifier
        only ever raises a bare allow to warn, never overrides a stronger hit."""
        _seed_lean_pod()
        _write_policy("forbidden-marker", "pre_output", "FORBIDDEN_TOKEN", "block")
        _dispatch.enqueue_task("myapp", "Ship it")
        runner = _RecordingRunner({"lead": "FORBIDDEN_TOKEN: also ran stripe charge customer here"})
        results = _dispatch.dispatch_pod("myapp", runner=runner)

        assert results[0].status == "failed"
        events = _trace_events("myapp")
        block_events = [e for e in events if e["event_type"] == "guardrail_block"]
        assert len(block_events) == 1
        # The operator's own policy id wins -- not overwritten by the built-in tag.
        assert block_events[0]["payload"]["action"] == "forbidden-marker"

    def test_non_matching_output_still_silent(self) -> None:
        _seed_lean_pod()
        _dispatch.enqueue_task("myapp", "Ship it")
        runner = _RecordingRunner({"lead": "nothing interesting here"})
        _dispatch.dispatch_pod("myapp", runner=runner)

        events = _trace_events("myapp")
        assert not any(e["event_type"] in ("guardrail_check", "guardrail_block") for e in events)
