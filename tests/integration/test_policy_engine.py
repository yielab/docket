"""Policy engine on the live path.

Exercises ``governance/policy.py``'s ``pre_input``/``pre_output`` hooks wired into the real dispatch
path, not just the CLI's dry-run printer. TestInstallPolicies covers the shared
``install_policies()`` producer; TestPolicyEvalDetail covers the ``PolicyHit``-returning evaluator
underneath ``policy_test``; TestEnqueuePreInputGate and TestPreOutputGate cover the hooks themselves: block
rejects before/fails a hop and stops the pipeline, require_approval persists a real approval
record, redact scrubs the stored/carried text, allow/warn pass it through, and every non-allow
hit emits ``guardrail_check`` (block also ``guardrail_block``). See
specs/functional/security-gates.spec.md Requirements 2-4.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from tests.support import home as _support_home
from tests.support.pods import seed_lean_pod as _seed_lean_pod
from tests.support.pods import write_policy as _write_policy
from tests.support.trace import trace_events as _trace_events

import docket.kernel.templates as _templates
from docket.agent import ports as _rd
from docket.governance import approval as _ap
from docket.governance import policy as _policy
from docket.kernel.home import current_home
from docket.tasks.application import actions as _actions
from docket.tasks.application import queue as _queue
from docket.tasks.application import sweep as _sweep
from docket.tasks.domain import task as _task

_hermetic = _support_home.hermetic

SUBJECT = "docket.tasks"

# ── hermetic environment (mirrors test_approval_gated_dispatch.py) ────────────


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


def _shipped_template_files() -> list[Path]:
    """Every shipped template -- JSON or YAML, since the baseline templates ship as short-form
    YAML -- sorted the same way ``governance.policy.install_policies`` iterates them."""
    return sorted(
        p
        for pattern in ("*.json", "*.yaml", "*.yml")
        for p in _templates.POLICY_TEMPLATES_DIR.glob(pattern)
    )


class TestInstallPolicies:
    def test_first_call_installs_every_shipped_template(self) -> None:
        result = _policy.install_policies()
        template_names = {f.name for f in _shipped_template_files()}
        assert set(result.installed) == template_names
        assert result.skipped == []
        for name in template_names:
            dest = current_home().policies_dir / name
            assert dest.is_file()
            assert (dest.stat().st_mode & 0o777) == 0o600

    def test_second_call_skips_everything(self) -> None:
        _policy.install_policies()
        result = _policy.install_policies()
        assert result.installed == []
        template_names = {f.name for f in _shipped_template_files()}
        assert set(result.skipped) == template_names

    def test_entries_preserve_interleaved_order(self) -> None:
        """One entry per file, in template order — not two separately-sorted groups."""
        templates = _shipped_template_files()
        # Pre-install just the first template so the second call mixes skip/install.
        current_home().policies_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy(templates[0], current_home().policies_dir / templates[0].name)

        result = _policy.install_policies()
        assert [name for name, _ in result.entries] == [t.name for t in templates]
        assert result.entries[0] == (templates[0].name, False)
        assert all(was_installed for _, was_installed in result.entries[1:])

    def test_missing_template_dir_returns_empty_not_an_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            _templates,
            "POLICY_TEMPLATES_DIR",
            Path("/nonexistent-templates-xyz/policies"),
            raising=True,
        )
        result = _policy.install_policies()
        assert result.entries == []
        assert not result.template_dir.is_dir()


# ── policy_eval_detail() — PolicyHit underneath the unchanged policy_eval_detail().action ──────


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
        assert _policy.policy_eval_detail("lead", "pre_input", "DELETE PROD").action == "block"
        assert _policy.policy_eval_detail("lead", "pre_input", "harmless text").action == "allow"

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
        task = _queue.enqueue_task_once("myapp", "Ship it", channel="cli")[0]
        assert task["status"] == "pending"
        assert _queue.read_tasks("myapp")[0]["id"] == task["id"]

    def test_block_rejects_before_the_task_is_ever_queued(self) -> None:
        _seed_lean_pod()
        _write_policy("no-wipes", "pre_input", "wipe prod db", "block", message="absolutely not")
        with pytest.raises(_task.DispatchError, match="no-wipes"):
            _queue.enqueue_task_once("myapp", "please wipe prod db tonight", channel="cli")
        assert _queue.read_tasks("myapp") == []

    def test_block_emits_a_self_contained_terminal_session(self) -> None:
        """A rejected task is never dispatched, so nothing else will ever close
        out its trace file — the enqueue gate must close it itself, or the
        guardrail_block event is invisible to `docket status`."""
        _seed_lean_pod()
        _write_policy("no-wipes", "pre_input", "wipe prod db", "block")
        with pytest.raises(_task.DispatchError):
            _queue.enqueue_task_once("myapp", "please wipe prod db tonight", channel="cli")

        events = _trace_events("myapp")
        types = [e["event_type"] for e in events]
        assert "session_start" in types
        assert "guardrail_check" in types
        assert "guardrail_block" in types
        assert "session_end" in types
        block_event = next(e for e in events if e["event_type"] == "guardrail_block")
        assert block_event["payload"]["policy"] == "no-wipes"
        assert block_event["payload"]["action"] == "block"
        end_event = next(e for e in events if e["event_type"] == "session_end")
        assert end_event["payload"]["status"] == "aborted"

    def test_require_approval_persists_waiting_approval_with_real_token(self) -> None:
        _seed_lean_pod()
        _write_policy("big-spend", "pre_input", "URGENT WIRE", "require_approval")
        task = _queue.enqueue_task_once("myapp", "URGENT WIRE the vendor today", channel="cli")[0]

        assert task["status"] == "waiting_approval"
        assert task["approvalToken"].startswith("apr-")
        assert task["pendingApprovalIndex"] == 0
        stored = _queue.read_tasks("myapp")[0]
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
        _queue.enqueue_task_once("myapp", "URGENT WIRE the vendor today", channel="cli")

        runner = _RecordingRunner()
        results = _sweep.dispatch_pod("myapp", runner=runner)
        assert results == []
        assert runner.calls == []

    def test_require_approval_grant_resumes_and_runs_the_pipeline(self) -> None:
        _seed_lean_pod()
        _write_policy("big-spend", "pre_input", "URGENT WIRE", "require_approval")
        task = _queue.enqueue_task_once("myapp", "URGENT WIRE the vendor today", channel="cli")[0]
        token = task["approvalToken"]

        _ap.approval_grant(token)
        assert _actions.resolve_waiting_approval(token, "granted") is True

        resumed = _queue.read_tasks("myapp")[0]
        assert resumed["status"] == "pending"
        assert resumed["gateOverridePipelineIndex"] == 0

        runner = _RecordingRunner()
        results = _sweep.dispatch_pod("myapp", runner=runner)
        assert len(results) == 1
        assert results[0].status == "done"
        assert runner.calls == ["lead", "implementer"]

    def test_require_approval_deny_fails_task_terminally(self) -> None:
        _seed_lean_pod()
        _write_policy("big-spend", "pre_input", "URGENT WIRE", "require_approval")
        task = _queue.enqueue_task_once("myapp", "URGENT WIRE the vendor today", channel="cli")[0]
        token = task["approvalToken"]

        _ap.approval_deny(token)
        assert _actions.resolve_waiting_approval(token, "denied") is True

        failed = _queue.read_tasks("myapp")[0]
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
        task = _queue.enqueue_task_once(
            "myapp", "loop in leaky@example.com before shipping", channel="cli"
        )[0]
        assert "leaky@example.com" not in task["description"]
        assert "[REDACTED]" in task["description"]
        stored = _queue.read_tasks("myapp")[0]
        assert "leaky@example.com" not in stored["description"]

    def test_warn_does_not_change_status_or_description(self) -> None:
        _seed_lean_pod()
        _write_policy("fyi-only", "pre_input", "heads up", "warn")
        task = _queue.enqueue_task_once("myapp", "heads up, this one is tricky", channel="cli")[0]
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
        _queue.enqueue_task_once("myapp", "Ship it", channel="cli")
        runner = _RecordingRunner({"lead": "reach me at leaky@example.com for questions"})
        results = _sweep.dispatch_pod("myapp", runner=runner)

        assert len(results) == 1
        assert results[0].status == "done"
        lead_hop = next(h for h in results[0].hops if h.role == "lead")
        assert "leaky@example.com" not in lead_hop.output
        assert "[REDACTED]" in lead_hop.output
        assert "leaky@example.com" not in lead_hop.artifact.render()

    def test_block_fails_the_hop_and_stops_the_pipeline(self) -> None:
        _seed_lean_pod()
        _write_policy("forbidden-marker", "pre_output", "FORBIDDEN_TOKEN", "block")
        _queue.enqueue_task_once("myapp", "Ship it", channel="cli")
        runner = _RecordingRunner({"lead": "here is a FORBIDDEN_TOKEN in my output"})
        results = _sweep.dispatch_pod("myapp", runner=runner)

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
        _queue.enqueue_task_once("myapp", "Ship it", channel="cli")
        runner = _RecordingRunner({"lead": "heads up: nothing to see here"})
        results = _sweep.dispatch_pod("myapp", runner=runner)

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
        _queue.enqueue_task_once("myapp", "Ship it", channel="cli")
        runner = _RecordingRunner(
            {
                "lead": "lead contact: lead@example.com",
                "implementer": "impl contact: impl@example.com",
            }
        )
        results = _sweep.dispatch_pod("myapp", runner=runner)

        assert results[0].status == "done"
        by_role = {h.role: h for h in results[0].hops}
        assert "lead@example.com" not in by_role["lead"].output
        assert "impl@example.com" not in by_role["implementer"].output

    def test_guardrail_events_use_the_metrics_bucket_shape(self) -> None:
        """`guardrail_block`'s payload["action"] is the tripped policy's action — the
        field/value `cli/_metrics.py`'s reader tallies "Guardrail trips" by."""
        _seed_lean_pod()
        _write_policy("forbidden-marker", "pre_output", "FORBIDDEN_TOKEN", "block")
        _queue.enqueue_task_once("myapp", "Ship it", channel="cli")
        runner = _RecordingRunner({"lead": "FORBIDDEN_TOKEN in the output"})
        _sweep.dispatch_pod("myapp", runner=runner)

        events = _trace_events("myapp")
        block_events = [e for e in events if e["event_type"] == "guardrail_block"]
        assert len(block_events) == 1
        assert block_events[0]["payload"]["action"] == "block"
        check_events = [e for e in events if e["event_type"] == "guardrail_check"]
        assert any(e["payload"]["action"] == "block" for e in check_events)

    def test_allow_is_silent_no_guardrail_trace_at_all(self) -> None:
        _seed_lean_pod()
        _queue.enqueue_task_once("myapp", "Ship it", channel="cli")
        runner = _RecordingRunner({"lead": "nothing interesting here"})
        _sweep.dispatch_pod("myapp", runner=runner)

        events = _trace_events("myapp")
        assert not any(e["event_type"] in ("guardrail_check", "guardrail_block") for e in events)
