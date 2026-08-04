"""P20-2: guardrail + loop metrics on the existing Prometheus surface.

Extends `docket serve`'s `/metrics` (ROADMAP Phase 20) with denial rate,
approvals granted/denied/timed-out by channel, policy-hit counts by policy
id, tool-call rate and turn latency -- all recomputed fresh, on every
scrape, from durable state already on disk (trace JSONL + the audit log),
never a second in-process counter store (see `docket.serve.LoopMetrics`).
No new endpoint, no new dependency: this only exercises `render_metrics()`.

What's pinned here:

1. `docket_tool_calls_total{decision}` counts every `tool_result` trace
   event (as `core/agent_loop.py` emits for each `dispatch_tool` call),
   bucketed by gate decision -- fleet-wide, across projects.
2. `docket_policy_hits_total{policy_id,hook,action}` merges the structured
   `guardrail_check` trace event (pre_input/pre_output) with the
   `policy_id=`/`policy_action=` fields P20-2 added to `core/tools.py`'s
   tool-gate audit entries (pre_tool_call) -- the pre_tool_call half is
   exercised end-to-end through the real `dispatch_tool` chokepoint, not a
   hand-crafted audit line, and a bare command-classifier denial (no policy
   involved) is proven NOT to count as a policy hit.
3. `docket_approvals_total{channel,outcome}` covers real grant/deny/timeout
   audit entries across cli, telegram and the fail-closed timeout path (via
   the real `dispatch_tool` -> `wait_for_approval` -> timeout route).
4. `docket_turn_duration_seconds_sum`/`_count` sums every completed
   session_start/session_end bracket across every project's trace file, and
   excludes a session with no session_end yet.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import docket.config as _cfg
import docket.serve as serve
from docket.core import approval as _approval
from docket.core.llm import ToolCall
from docket.core.tools import ToolContext, builtin_registry, dispatch_tool
from docket.core.trace import trace_event


@pytest.fixture(autouse=True)
def _hermetic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolate every store this module touches (on top of conftest's autouse
    isolation, which already repoints TRACES_DIR/AUDIT_LOG/APPROVALS_DIR/
    POLICIES_DIR to a tmp dir -- this just pins TOOL_APPROVAL_TIMEOUT to 0 so
    an unanswered `ask` fails closed immediately, no real sleep, matching
    test_p19_3_pre_tool_call.py's own fixture.
    """
    monkeypatch.setattr(_cfg, "TOOL_APPROVAL_TIMEOUT", 0, raising=True)


def _write_policy(
    policy_id: str, pattern: str, action: str, *, hook: str = "pre_tool_call"
) -> None:
    _cfg.POLICIES_DIR.mkdir(parents=True, exist_ok=True)
    doc = {
        "id": policy_id,
        "description": f"test policy {policy_id}",
        "applies_to": ["*"],
        "hook": hook,
        "match": {"type": "regex", "pattern": pattern},
        "action": action,
        "message": "",
    }
    (_cfg.POLICIES_DIR / f"{policy_id}.json").write_text(json.dumps(doc), encoding="utf-8")


def _write_trace(project: str, session: str, events: list[dict[str, Any]]) -> None:
    d = _cfg.TRACES_DIR / project
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{session}.jsonl").write_text(
        "\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8"
    )


def _metric_value(text: str, line_prefix: str) -> str:
    """Return the numeric suffix of the one metrics line starting with *line_prefix*."""
    matches = [line for line in text.splitlines() if line.startswith(line_prefix)]
    assert len(matches) == 1, (
        f"expected exactly one line starting with {line_prefix!r}, got {matches}"
    )
    return matches[0][len(line_prefix) :].strip()


@pytest.fixture
def ctx(tmp_path: Path) -> ToolContext:
    ws = tmp_path / "ws"
    ws.mkdir()
    return ToolContext(agent_id="demo-implementer", role="implementer", project="demo", roots=(ws,))


# ── docket_tool_calls_total ─────────────────────────────────────────────────


class TestToolCallsByDecision:
    def test_counts_by_decision_across_projects(self) -> None:
        trace_event(
            "proj-a",
            "sess-1",
            "implementer",
            "tool_result",
            json.dumps(
                {"tool": "write", "callId": "1", "decision": "allow", "ok": True, "executed": True}
            ),
        )
        trace_event(
            "proj-a",
            "sess-1",
            "implementer",
            "tool_result",
            json.dumps(
                {"tool": "bash", "callId": "2", "decision": "deny", "ok": False, "executed": False}
            ),
        )
        trace_event(
            "proj-b",
            "sess-2",
            "implementer",
            "tool_result",
            json.dumps(
                {"tool": "bash", "callId": "3", "decision": "deny", "ok": False, "executed": False}
            ),
        )
        trace_event(
            "proj-b",
            "sess-2",
            "implementer",
            "tool_result",
            json.dumps(
                {"tool": "fetch", "callId": "4", "decision": "ask", "ok": False, "executed": False}
            ),
        )

        text = serve.render_metrics()
        assert _metric_value(text, 'docket_tool_calls_total{decision="allow"}') == "1"
        assert _metric_value(text, 'docket_tool_calls_total{decision="deny"}') == "2"
        assert _metric_value(text, 'docket_tool_calls_total{decision="ask"}') == "1"

    def test_no_data_keeps_headers_but_emits_no_label_lines(self) -> None:
        text = serve.render_metrics()
        assert "# HELP docket_tool_calls_total" in text
        assert "# TYPE docket_tool_calls_total counter" in text
        assert "docket_tool_calls_total{decision=" not in text


# ── docket_policy_hits_total ────────────────────────────────────────────────


class TestPolicyHitsFromTrace:
    """pre_input / pre_output hits: the structured `guardrail_check` event."""

    def test_hits_are_counted_by_policy_id_hook_and_action(self) -> None:
        trace_event(
            "proj-a",
            "sess-1",
            "lead",
            "guardrail_check",
            json.dumps({"hook": "pre_input", "policy": "prompt-injection", "action": "warn"}),
        )
        trace_event(
            "proj-a",
            "sess-1",
            "lead",
            "guardrail_check",
            json.dumps({"hook": "pre_input", "policy": "prompt-injection", "action": "warn"}),
        )
        trace_event(
            "proj-b",
            "sess-2",
            "implementer",
            "guardrail_check",
            json.dumps(
                {"hook": "pre_output", "policy": "high-risk:money_movement", "action": "warn"}
            ),
        )

        text = serve.render_metrics()
        assert (
            _metric_value(
                text,
                'docket_policy_hits_total{policy_id="prompt-injection",hook="pre_input",action="warn"}',
            )
            == "2"
        )
        assert (
            _metric_value(
                text,
                'docket_policy_hits_total{policy_id="high-risk:money_movement",hook="pre_output",action="warn"}',
            )
            == "1"
        )


class TestPolicyHitsFromToolGate:
    """pre_tool_call hits: exercised through the real `dispatch_tool` chokepoint."""

    def test_a_block_policy_hit_is_counted_with_hook_pre_tool_call(self, ctx: ToolContext) -> None:
        _write_policy("block-secret-write", r"topsecret", "block")
        res = dispatch_tool(
            ToolCall(
                id="c1",
                name="write",
                arguments=json.dumps({"path": "n.txt", "content": "topsecret"}),
            ),
            ctx,
            builtin_registry(),
        )
        assert res.denied

        text = serve.render_metrics()
        assert (
            _metric_value(
                text,
                'docket_policy_hits_total{policy_id="block-secret-write",hook="pre_tool_call",action="block"}',
            )
            == "1"
        )

    def test_a_bare_command_classifier_denial_is_not_a_policy_hit(self, ctx: ToolContext) -> None:
        """`rm x` is denied by core/security.py's classifier, no policy involved
        at all -- it must not show up under docket_policy_hits_total."""
        res = dispatch_tool(
            ToolCall(id="c2", name="bash", arguments=json.dumps({"command": "rm x"})),
            ctx,
            builtin_registry(),
        )
        assert res.denied

        text = serve.render_metrics()
        assert 'hook="pre_tool_call"' not in text


# ── docket_approvals_total ───────────────────────────────────────────────────


class TestApprovalsByChannel:
    def test_grant_and_deny_across_two_real_channels(self) -> None:
        token_a = _approval.approval_create("proj-a", "lead", "deploy to prod")
        _approval.approval_grant(token_a, channel="cli")

        token_b = _approval.approval_create("proj-a", "lead", "rotate a secret")
        _approval.approval_deny(token_b, channel="telegram")

        text = serve.render_metrics()
        assert _metric_value(text, 'docket_approvals_total{channel="cli",outcome="granted"}') == "1"
        assert (
            _metric_value(text, 'docket_approvals_total{channel="telegram",outcome="denied"}')
            == "1"
        )

    def test_timeout_resolution_surfaces_as_channel_timeout_denied(self, ctx: ToolContext) -> None:
        """A fail-closed in-turn approval timeout (TOOL_APPROVAL_TIMEOUT=0, set
        by this module's _hermetic fixture) writes `approval.deny` with
        `channel=timeout` -- the real producer for "timed out", not a third
        outcome value invented for this metric."""
        res = dispatch_tool(
            ToolCall(id="c3", name="bash", arguments=json.dumps({"command": "rm x"})),
            ctx,
            builtin_registry(),
        )
        assert res.denied

        text = serve.render_metrics()
        assert (
            _metric_value(text, 'docket_approvals_total{channel="timeout",outcome="denied"}') == "1"
        )

    def test_no_approvals_keeps_headers_but_emits_no_label_lines(self) -> None:
        text = serve.render_metrics()
        assert "# HELP docket_approvals_total" in text
        assert "# TYPE docket_approvals_total counter" in text
        assert "docket_approvals_total{channel=" not in text


# ── docket_turn_duration_seconds_{sum,count} ────────────────────────────────


class TestTurnDuration:
    def test_sums_completed_sessions_across_projects(self) -> None:
        _write_trace(
            "proj-a",
            "sess-1",
            [
                {"event_type": "session_start", "ts": "2026-08-01T10:00:00Z"},
                {
                    "event_type": "session_end",
                    "ts": "2026-08-01T10:00:05Z",
                    "payload": {"status": "success"},
                },
            ],
        )
        _write_trace(
            "proj-b",
            "sess-2",
            [
                {"event_type": "session_start", "ts": "2026-08-01T11:00:00Z"},
                {
                    "event_type": "session_end",
                    "ts": "2026-08-01T11:00:11Z",
                    "payload": {"status": "failure"},
                },
            ],
        )

        text = serve.render_metrics()
        assert _metric_value(text, "docket_turn_duration_seconds_sum") == "16.0"
        assert _metric_value(text, "docket_turn_duration_seconds_count") == "2"

    def test_an_open_session_with_no_end_is_excluded(self) -> None:
        _write_trace(
            "proj-a",
            "sess-open",
            [{"event_type": "session_start", "ts": "2026-08-01T10:00:00Z"}],
        )

        text = serve.render_metrics()
        assert _metric_value(text, "docket_turn_duration_seconds_sum") == "0.0"
        assert _metric_value(text, "docket_turn_duration_seconds_count") == "0"

    def test_no_traces_dir_returns_zero_not_an_error(self) -> None:
        text = serve.render_metrics()
        assert _metric_value(text, "docket_turn_duration_seconds_sum") == "0.0"
        assert _metric_value(text, "docket_turn_duration_seconds_count") == "0"


# ── HELP/TYPE style, matching the six pre-existing metrics exactly ─────────


class TestMetricFormatting:
    def test_help_and_type_lines_present_for_every_new_metric(self) -> None:
        text = serve.render_metrics()
        for name, kind in (
            ("docket_tool_calls_total", "counter"),
            ("docket_policy_hits_total", "counter"),
            ("docket_approvals_total", "counter"),
        ):
            assert f"# HELP {name} " in text
            assert f"# TYPE {name} {kind}" in text

    def test_turn_duration_is_one_summary_family_not_two_counters(self) -> None:
        """Prometheus text exposition format: `_sum`/`_count` are members of
        one `summary` family declared on the bare metric name -- not two
        independent counters with their own HELP/TYPE pair."""
        text = serve.render_metrics()
        assert "# HELP docket_turn_duration_seconds " in text
        assert "# TYPE docket_turn_duration_seconds summary" in text
        # Exactly one HELP/TYPE pair for the family -- not one per suffix.
        assert text.count("# HELP docket_turn_duration_seconds ") == 1
        assert text.count("# TYPE docket_turn_duration_seconds ") == 1
        assert "docket_turn_duration_seconds_sum " in text
        assert "docket_turn_duration_seconds_count " in text
        # Never declared as their own metric family.
        assert "# TYPE docket_turn_duration_seconds_sum" not in text
        assert "# TYPE docket_turn_duration_seconds_count" not in text

    def test_stable_pre_p20_2_metrics_are_unaffected(self) -> None:
        # docket_agent_cost_usd/docket_agent_turns_total only ever emit label
        # lines when an agent exists (this fixture seeds none, matching
        # pre-P20-2 behavior) -- check the four metrics with an unconditional
        # HELP header instead.
        text = serve.render_metrics()
        for name in (
            "docket_agents_total",
            "docket_cost_usd_total",
            "docket_gateway_up",
            "docket_approvals_pending_total",
        ):
            assert f"# HELP {name} " in text

    def test_no_trailing_newline(self) -> None:
        assert not serve.render_metrics().endswith("\n")
