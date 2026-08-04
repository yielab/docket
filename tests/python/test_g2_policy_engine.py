"""Policy engine on the live path.

Before this card, ``core/policy.py`` was fully built and tested but had exactly
one caller: the CLI's own dry-run printer (``docket policies test``).
``docket install`` never installed the shipped templates, ``pre_input`` was
never evaluated anywhere real, and ``pre_output`` had no producer at all —
``cli/_metrics.py``'s "Guardrail trips" reader existed with nothing to read.
This suite exercises the wiring:

  * TestInstallPolicies     — ``core.policy.install_policies()``, the shared
    producer behind both ``docket policies init`` and ``docket install``'s new
    Step 9 (see also ``test_m6_install.py``'s own Step 9 assertion).
  * TestPolicyEvalDetail    — the new ``PolicyHit``-returning evaluator
    underneath the unchanged ``policy_eval``/``policy_test`` (regression: every
    pre-G-2 caller of those two functions keeps working unmodified).
  * TestEnqueuePreInputGate — ``pre_input`` evaluated once, at
    ``core.dispatch.enqueue_task`` time: block rejects before the task is ever
    queued; require_approval persists straight into ``waiting_approval`` with
    a real G-1 approval record; redact scrubs the stored description; allow
    (no policies installed, or a non-matching one) is a no-op.
  * TestPreOutputGate       — ``pre_output`` evaluated on every hop's real
    output inside ``dispatch_task``: redact scrubs the carried-forward
    artifact/persisted hop, block fails the hop (and stops the pipeline) the
    same way a failed agent turn does, warn/allow pass the text through
    unchanged. Every non-allow hit emits ``guardrail_check``; a block
    additionally emits ``guardrail_block`` keyed by policy id.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

import docket.config as _cfg
from docket.core import approval as _ap
from docket.core import dispatch as _dispatch
from docket.core import fleet as _fleet
from docket.core import policy as _policy
from docket.core import runtime_driver as _rd
from docket.core import trace as _trace

# ── hermetic environment (mirrors test_g1_approval_gated_dispatch.py) ────────────


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


# ── install_policies() — the shared producer behind `init` and install Step 9 ────


class TestInstallPolicies:
    def test_first_call_installs_every_shipped_template(self) -> None:
        result = _policy.install_policies()
        template_names = {f.name for f in _cfg.policy_templates_dir().glob("*.json")}
        assert set(result.installed) == template_names
        assert result.skipped == []
        for name in template_names:
            dest = _cfg.POLICIES_DIR / name
            assert dest.is_file()
            assert (dest.stat().st_mode & 0o777) == 0o600

    def test_second_call_skips_everything(self) -> None:
        _policy.install_policies()
        result = _policy.install_policies()
        assert result.installed == []
        template_names = {f.name for f in _cfg.policy_templates_dir().glob("*.json")}
        assert set(result.skipped) == template_names

    def test_entries_preserve_interleaved_order(self) -> None:
        """One entry per file, in template order — not two separately-sorted groups."""
        templates = sorted(_cfg.policy_templates_dir().glob("*.json"))
        # Pre-install just the first template so the second call mixes skip/install.
        _cfg.POLICIES_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copy(templates[0], _cfg.POLICIES_DIR / templates[0].name)

        result = _policy.install_policies()
        assert [name for name, _ in result.entries] == [t.name for t in templates]
        assert result.entries[0] == (templates[0].name, False)
        assert all(was_installed for _, was_installed in result.entries[1:])

    def test_missing_template_dir_returns_empty_not_an_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            _cfg, "templates_dir", lambda: Path("/nonexistent-templates-xyz"), raising=True
        )
        result = _policy.install_policies()
        assert result.entries == []
        assert not result.template_dir.is_dir()


# ── policy_eval_detail() — PolicyHit underneath the unchanged policy_eval() ──────


class TestPolicyEvalDetail:
    def test_no_policies_dir_is_allow(self) -> None:
        hit = _policy.policy_eval_detail("lead", "pre_input", "anything")
        assert hit.action == "allow"
        assert hit.policy_id == ""

    def test_matching_policy_reports_id_and_message(self) -> None:
        _write_policy("kill-switch", "pre_input", "DELETE PROD", "block", message="no.")
        hit = _policy.policy_eval_detail("lead", "pre_input", "please DELETE PROD now")
        assert hit.action == "block"
        assert hit.policy_id == "kill-switch"
        assert hit.message == "no."

    def test_policy_eval_thin_wrapper_matches_detail_action(self) -> None:
        _write_policy("kill-switch", "pre_input", "DELETE PROD", "block")
        assert _policy.policy_eval("lead", "pre_input", "DELETE PROD") == "block"
        assert _policy.policy_eval("lead", "pre_input", "harmless text") == "allow"

    def test_most_restrictive_wins_detail(self) -> None:
        _write_policy("warn-only", "pre_input", "secret", "warn")
        _write_policy("block-it", "pre_input", "secret", "block")
        hit = _policy.policy_eval_detail("lead", "pre_input", "a secret plan")
        assert hit.action == "block"
        assert hit.policy_id == "block-it"


# ── pre_input at enqueue ──────────────────────────────────────────────────────────


class TestEnqueuePreInputGate:
    def test_allows_when_no_policies_installed(self) -> None:
        _seed_lean_pod()
        task = _dispatch.enqueue_task("myapp", "Ship it")
        assert task["status"] == "pending"
        assert _dispatch.read_tasks("myapp")[0]["id"] == task["id"]

    def test_block_rejects_before_the_task_is_ever_queued(self) -> None:
        _seed_lean_pod()
        _write_policy("no-wipes", "pre_input", "wipe prod db", "block", message="absolutely not")
        with pytest.raises(_dispatch.DispatchError, match="no-wipes"):
            _dispatch.enqueue_task("myapp", "please wipe prod db tonight")
        assert _dispatch.read_tasks("myapp") == []

    def test_block_emits_a_self_contained_terminal_session(self) -> None:
        """A rejected task is never dispatched, so nothing else will ever close
        out its trace file — the enqueue gate must close it itself, or the
        guardrail_block event is invisible to `docket metrics`."""
        _seed_lean_pod()
        _write_policy("no-wipes", "pre_input", "wipe prod db", "block")
        with pytest.raises(_dispatch.DispatchError):
            _dispatch.enqueue_task("myapp", "please wipe prod db tonight")

        events = _trace_events("myapp")
        types = [e["event_type"] for e in events]
        assert "session_start" in types
        assert "guardrail_check" in types
        assert "guardrail_block" in types
        assert "session_end" in types
        block_event = next(e for e in events if e["event_type"] == "guardrail_block")
        assert block_event["payload"]["policy"] == "no-wipes"
        assert block_event["payload"]["action"] == "no-wipes"
        end_event = next(e for e in events if e["event_type"] == "session_end")
        assert end_event["payload"]["status"] == "aborted"

    def test_require_approval_persists_waiting_approval_with_real_token(self) -> None:
        _seed_lean_pod()
        _write_policy("big-spend", "pre_input", "URGENT WIRE", "require_approval")
        task = _dispatch.enqueue_task("myapp", "URGENT WIRE the vendor today")

        assert task["status"] == "waiting_approval"
        assert task["approvalToken"].startswith("apr-")
        assert task["pendingApprovalIndex"] == 0
        stored = _dispatch.read_tasks("myapp")[0]
        assert stored["status"] == "waiting_approval"
        assert stored["approvalToken"] == task["approvalToken"]

        rec = _ap.approval_get(task["approvalToken"])
        assert rec["project"] == "myapp"
        assert rec["role"] == "lead"
        assert rec["state"] == "pending"
        assert rec["context"] == {"taskId": task["id"], "pipelineIndex": 0}

        events = _trace_events("myapp")
        approval_events = [e for e in events if e["event_type"] == "approval_required"]
        assert len(approval_events) == 1
        assert approval_events[0]["payload"]["token"] == task["approvalToken"]
        assert approval_events[0]["payload"]["policy"] == "big-spend"

    def test_require_approval_task_is_not_claimable_until_granted(self) -> None:
        _seed_lean_pod()
        _write_policy("big-spend", "pre_input", "URGENT WIRE", "require_approval")
        _dispatch.enqueue_task("myapp", "URGENT WIRE the vendor today")

        runner = _RecordingRunner()
        results = _dispatch.dispatch_pod("myapp", runner=runner)
        assert results == []
        assert runner.calls == []

    def test_require_approval_grant_resumes_and_runs_the_pipeline(self) -> None:
        _seed_lean_pod()
        _write_policy("big-spend", "pre_input", "URGENT WIRE", "require_approval")
        task = _dispatch.enqueue_task("myapp", "URGENT WIRE the vendor today")
        token = task["approvalToken"]

        _ap.approval_grant(token)
        assert _dispatch.resolve_waiting_approval(token, "granted") is True

        resumed = _dispatch.read_tasks("myapp")[0]
        assert resumed["status"] == "pending"
        assert resumed["gateOverridePipelineIndex"] == 0

        runner = _RecordingRunner()
        results = _dispatch.dispatch_pod("myapp", runner=runner)
        assert len(results) == 1
        assert results[0].status == "done"
        assert runner.calls == ["lead", "implementer"]

    def test_require_approval_deny_fails_task_terminally(self) -> None:
        _seed_lean_pod()
        _write_policy("big-spend", "pre_input", "URGENT WIRE", "require_approval")
        task = _dispatch.enqueue_task("myapp", "URGENT WIRE the vendor today")
        token = task["approvalToken"]

        _ap.approval_deny(token)
        assert _dispatch.resolve_waiting_approval(token, "denied") is True

        failed = _dispatch.read_tasks("myapp")[0]
        assert failed["status"] == "failed"
        assert failed["failureKind"] == "approval_denied"

    def test_redact_scrubs_the_persisted_description(self) -> None:
        _seed_lean_pod()
        _write_policy(
            "email-in-task",
            "pre_input",
            r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
            "redact",
        )
        task = _dispatch.enqueue_task("myapp", "loop in leaky@example.com before shipping")
        assert "leaky@example.com" not in task["description"]
        assert "[REDACTED]" in task["description"]
        stored = _dispatch.read_tasks("myapp")[0]
        assert "leaky@example.com" not in stored["description"]

    def test_warn_does_not_change_status_or_description(self) -> None:
        _seed_lean_pod()
        _write_policy("fyi-only", "pre_input", "heads up", "warn")
        task = _dispatch.enqueue_task("myapp", "heads up, this one is tricky")
        assert task["status"] == "pending"
        assert task["description"] == "heads up, this one is tricky"
        events = _trace_events("myapp")
        assert any(e["event_type"] == "guardrail_check" for e in events)
        assert not any(e["event_type"] == "guardrail_block" for e in events)


# ── pre_output on every hop ───────────────────────────────────────────────────────


class TestPreOutputGate:
    def test_redacts_hop_output_before_persisting(self) -> None:
        _seed_lean_pod()
        _write_policy(
            "email-in-output",
            "pre_output",
            r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
            "redact",
        )
        _dispatch.enqueue_task("myapp", "Ship it")
        runner = _RecordingRunner({"lead": "reach me at leaky@example.com for questions"})
        results = _dispatch.dispatch_pod("myapp", runner=runner)

        assert len(results) == 1
        assert results[0].status == "done"
        lead_hop = next(h for h in results[0].hops if h.role == "lead")
        assert "leaky@example.com" not in lead_hop.output
        assert "[REDACTED]" in lead_hop.output
        assert "leaky@example.com" not in lead_hop.rendered_artifact()

    def test_block_fails_the_hop_and_stops_the_pipeline(self) -> None:
        _seed_lean_pod()
        _write_policy("forbidden-marker", "pre_output", "FORBIDDEN_TOKEN", "block")
        _dispatch.enqueue_task("myapp", "Ship it")
        runner = _RecordingRunner({"lead": "here is a FORBIDDEN_TOKEN in my output"})
        results = _dispatch.dispatch_pod("myapp", runner=runner)

        assert len(results) == 1
        assert results[0].status == "failed"
        # The implementer hop never ran — the pipeline stopped at the blocked lead hop.
        assert runner.calls == ["lead"]
        lead_hop = results[0].hops[0]
        assert lead_hop.ok is False
        assert "forbidden-marker" in lead_hop.error

    def test_warn_leaves_output_unchanged_and_task_continues(self) -> None:
        _seed_lean_pod()
        _write_policy("fyi-output", "pre_output", "heads up", "warn")
        _dispatch.enqueue_task("myapp", "Ship it")
        runner = _RecordingRunner({"lead": "heads up: nothing to see here"})
        results = _dispatch.dispatch_pod("myapp", runner=runner)

        assert results[0].status == "done"
        lead_hop = next(h for h in results[0].hops if h.role == "lead")
        assert lead_hop.output == "heads up: nothing to see here"

    def test_fires_on_every_hop_not_just_the_first(self) -> None:
        _seed_lean_pod()
        _write_policy(
            "email-in-output",
            "pre_output",
            r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
            "redact",
        )
        _dispatch.enqueue_task("myapp", "Ship it")
        runner = _RecordingRunner(
            {
                "lead": "lead contact: lead@example.com",
                "implementer": "impl contact: impl@example.com",
            }
        )
        results = _dispatch.dispatch_pod("myapp", runner=runner)

        assert results[0].status == "done"
        by_role = {h.role: h for h in results[0].hops}
        assert "lead@example.com" not in by_role["lead"].output
        assert "impl@example.com" not in by_role["implementer"].output

    def test_guardrail_events_use_the_metrics_bucket_shape(self) -> None:
        """`guardrail_block`'s payload["action"] is the tripped policy's id — the
        field/value `cli/_metrics.py`'s reader tallies "Guardrail trips" by."""
        _seed_lean_pod()
        _write_policy("forbidden-marker", "pre_output", "FORBIDDEN_TOKEN", "block")
        _dispatch.enqueue_task("myapp", "Ship it")
        runner = _RecordingRunner({"lead": "FORBIDDEN_TOKEN in the output"})
        _dispatch.dispatch_pod("myapp", runner=runner)

        events = _trace_events("myapp")
        block_events = [e for e in events if e["event_type"] == "guardrail_block"]
        assert len(block_events) == 1
        assert block_events[0]["payload"]["action"] == "forbidden-marker"
        check_events = [e for e in events if e["event_type"] == "guardrail_check"]
        assert any(e["payload"]["action"] == "block" for e in check_events)

    def test_allow_is_silent_no_guardrail_trace_at_all(self) -> None:
        _seed_lean_pod()
        _dispatch.enqueue_task("myapp", "Ship it")
        runner = _RecordingRunner({"lead": "nothing interesting here"})
        _dispatch.dispatch_pod("myapp", runner=runner)

        events = _trace_events("myapp")
        assert not any(e["event_type"] in ("guardrail_check", "guardrail_block") for e in events)
