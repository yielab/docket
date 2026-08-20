"""The `pre_tool_call` policy hook is live.

docket used to ship four `pre_tool_call` policy templates and never evaluate
any of them -- `core/dispatch.py` said so in three places. `core/policy.py`'s
`policy_eval_detail` is wired into `core/tools.py`'s single decision point
(`evaluate_tool_call`), combined with the command classifier
(most-restrictive-wins), and an `ask` verdict routes to a synchronous waiter
on the real approval store (`core/approval.py`'s `wait_for_approval`) so an
in-turn tool call actually blocks on a human instead of being a no-op.

What's pinned here:

1. `render_tool_call`'s exact shape -- every shipped policy pattern depends
   on it, so it is a contract, not an implementation detail.
2. A `block-destructive` policy actually gates an `rm -rf` tool call through
   `dispatch_tool`, with the handler proven not to have run.
3. `high-risk-deploy` catches `git push origin main` by argument, while
   `git push origin feature/x` stays allowed.
4. `block` denies; `require_approval` asks and then executes iff granted; an
   unanswered approval times out to denied; every gated decision is audited.

No test in this file ever sleeps for real: `wait_for_approval`'s `sleep`/
`clock` are exercised either by explicit injection or by monkeypatching
`docket.core.approval._time` -- see `TestWaitForApprovalUnit` and
`TestDispatchToolApprovalRouting` respectively.
"""

from __future__ import annotations

import json
import time as _real_time
import types
from pathlib import Path
from typing import Any

import pytest

import docket.config as _cfg
from docket.core import approval as _approval
from docket.core import audit as _audit
from docket.core.llm import ToolCall
from docket.core.policy import install_policies
from docket.core.tools import (
    Tool,
    ToolContext,
    ToolRegistry,
    builtin_registry,
    dispatch_tool,
    evaluate_tool_call,
    render_tool_call,
)
from docket.edges.adapters.toolbox import ToolOutcome


@pytest.fixture(autouse=True)
def _hermetic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolate every docket-owned store this module touches, and default the
    in-turn approval timeout to 0 so an unresolved `ask` fails closed
    immediately (no real sleep) unless a test overrides it to exercise the
    waiting/granting path deliberately.
    """
    monkeypatch.setattr(_cfg, "POLICIES_DIR", tmp_path / "policies", raising=True)
    monkeypatch.setattr(_cfg, "APPROVALS_DIR", tmp_path / "approvals", raising=True)
    monkeypatch.setattr(_cfg, "AUDIT_LOG", tmp_path / "audit.log", raising=True)
    monkeypatch.setattr(_cfg, "TOOL_APPROVAL_TIMEOUT", 0, raising=True)


def _write_policy(
    policy_id: str,
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
        "hook": "pre_tool_call",
        "match": {"type": "regex", "pattern": pattern},
        "action": action,
        "message": message,
    }
    (_cfg.POLICIES_DIR / f"{policy_id}.json").write_text(json.dumps(doc), encoding="utf-8")


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir()
    return ws


@pytest.fixture
def ctx(workspace: Path) -> ToolContext:
    return ToolContext(
        agent_id="demo-implementer",
        role="implementer",
        project="demo",
        roots=(workspace,),
        timeout=10,
    )


def _call(name: str, arguments: str = "{}", call_id: str = "c1") -> ToolCall:
    return ToolCall(id=call_id, name=name, arguments=arguments)


def _audit_actions() -> list[str]:
    return [e["action"] for e in _audit.read_audit()]


def _recording_tool(name: str, kind: str, ran: dict[str, bool]) -> Tool:
    def _handler(args: dict[str, Any], _ctx: ToolContext) -> ToolOutcome:
        ran["handler"] = True
        return ToolOutcome(ok=True, content="should not happen")

    return Tool(
        name=name,
        description="",
        parameters={
            "type": "object",
            "properties": {"command": {"type": "string"}, "x": {"type": "string"}},
            "required": ["command"] if kind == "exec" else ["x"],
        },
        handler=_handler,
        kind=kind,  # type: ignore[arg-type]
    )


class TestRenderToolCallShape:
    """The contract every shipped policy pattern is written against."""

    def test_no_arguments_renders_as_just_the_name(self) -> None:
        assert render_tool_call("read", {}) == "read"

    def test_string_values_are_quoted(self) -> None:
        assert (
            render_tool_call("write", {"path": ".env", "content": "SECRET=1"})
            == 'write path=".env" content="SECRET=1"'
        )

    def test_non_string_values_render_as_json_literals(self) -> None:
        assert (
            render_tool_call("edit", {"replace_all": True, "limit": 3, "note": None})
            == "edit replace_all=true limit=3 note=null"
        )

    def test_argument_order_is_preserved_not_sorted(self) -> None:
        assert render_tool_call("x", {"b": 1, "a": 2}) == "x b=1 a=2"


class TestBlockDestructiveShippedTemplate:
    """Acceptance: a block-destructive policy actually blocks/gates an
    `rm -rf` tool call, through dispatch_tool, with the handler proven not to
    have run."""

    def test_rm_rf_bash_call_is_gated_and_handler_never_runs(self, ctx: ToolContext) -> None:
        install_policies()
        ran = {"handler": False}
        registry = ToolRegistry()
        registry.register(_recording_tool("bash", "exec", ran))

        res = dispatch_tool(
            _call("bash", json.dumps({"command": "rm -rf /var/data"})), ctx, registry
        )

        assert ran["handler"] is False
        assert res.denied
        assert not res.executed

    def test_policy_gates_a_write_call_the_command_classifier_never_inspects(
        self, ctx: ToolContext
    ) -> None:
        """Proves the *policy engine*, not just the exec classifier, is
        what fires: `write` is a non-exec tool, so `classify_command` never
        runs on it -- only the block-destructive `.env` clause can gate this.
        This is also the regression test for the pattern fix: the template's
        original `\\.env\\b.*write` clause required the path to appear
        *before* the literal word "write", which no render of a `write` tool
        call produces (verified empirically, not assumed -- a natural render
        is `write path=".env" ...`, verb first). Fixed to match either order.
        """
        install_policies()
        verdict = evaluate_tool_call(
            _recording_tool("write", "write", {"handler": False}),
            {"path": ".env", "content": "API_KEY=x"},
            ctx,
        )
        assert verdict.policy_id == "block-destructive"
        assert verdict.decision == "ask"

    def test_ssh_directory_write_is_also_gated(self, ctx: ToolContext) -> None:
        install_policies()
        verdict = evaluate_tool_call(
            _recording_tool("write", "write", {"handler": False}),
            {"path": "~/.ssh/authorized_keys", "content": "ssh-rsa AAAA..."},
            ctx,
        )
        assert verdict.policy_id == "block-destructive"
        assert verdict.decision == "ask"


class TestHighRiskDeployByArgument:
    """Acceptance: high-risk-deploy catches `git push origin main` by
    argument, while `git push origin feature/x` stays allowed."""

    def test_push_to_main_is_gated_push_to_a_feature_branch_is_not(self, ctx: ToolContext) -> None:
        install_policies()
        bash_tool = builtin_registry().get("bash")
        assert bash_tool is not None

        gated = evaluate_tool_call(bash_tool, {"command": "git push origin main"}, ctx)
        allowed = evaluate_tool_call(bash_tool, {"command": "git push origin feature/x"}, ctx)

        assert gated.decision == "ask"
        assert gated.policy_id == "high-risk-deploy"
        assert allowed.decision == "allow"
        assert allowed.policy_id in ("", "high-risk-deploy")  # no hit at all, or hit-but-allow
        assert allowed.policy_action in ("", "allow")


class TestMostRestrictiveWins:
    """The command classifier and the policy engine can disagree; deny beats
    ask beats allow, mirroring core/policy.py's own _RANK philosophy."""

    def test_policy_block_overrides_a_classifier_ask(self, ctx: ToolContext) -> None:
        _write_policy("custom-block", r"suspicious-arg", "block", message="nope")
        bash_tool = builtin_registry().get("bash")
        assert bash_tool is not None
        # 'curl' is off SAFE_BINS -> classifier alone would only ask.
        verdict = evaluate_tool_call(bash_tool, {"command": "curl suspicious-arg"}, ctx)
        assert verdict.decision == "deny"
        assert verdict.policy_id == "custom-block"

    def test_classifier_ask_overrides_a_policy_allow(self, ctx: ToolContext) -> None:
        bash_tool = builtin_registry().get("bash")
        assert bash_tool is not None
        # No policy installed at all -> pure classifier result.
        verdict = evaluate_tool_call(bash_tool, {"command": "rm x"}, ctx)
        assert verdict.decision == "ask"

    def test_policy_require_approval_overrides_a_classifier_allow(self, ctx: ToolContext) -> None:
        _write_policy("custom-approve", r"\bspecial\b", "require_approval", message="ask a human")
        bash_tool = builtin_registry().get("bash")
        assert bash_tool is not None
        # 'ls' is allowlisted -> classifier alone would allow.
        verdict = evaluate_tool_call(bash_tool, {"command": "ls special"}, ctx)
        assert verdict.decision == "ask"
        assert verdict.policy_id == "custom-approve"

    def test_warn_does_not_change_an_otherwise_allowed_decision(self, ctx: ToolContext) -> None:
        _write_policy("custom-warn", r"\bnoisy\b", "warn", message="fyi")
        bash_tool = builtin_registry().get("bash")
        assert bash_tool is not None
        verdict = evaluate_tool_call(bash_tool, {"command": "ls noisy"}, ctx)
        assert verdict.decision == "allow"
        assert verdict.policy_action == "warn"
        assert verdict.policy_id == "custom-warn"

    def test_no_policy_hit_at_all_carries_no_policy_id(self, ctx: ToolContext) -> None:
        bash_tool = builtin_registry().get("bash")
        assert bash_tool is not None
        verdict = evaluate_tool_call(bash_tool, {"command": "ls"}, ctx)
        assert verdict.decision == "allow"
        assert verdict.policy_id == ""


class TestRoleScopedPolicy:
    """ToolContext.role feeds policy_eval_detail's applies_to matching."""

    def test_a_role_scoped_policy_does_not_fire_for_a_different_role(self, workspace: Path) -> None:
        _write_policy("reviewer-only", r"\bdeploy\b", "block", applies_to=["reviewer"])
        implementer_ctx = ToolContext(agent_id="x", role="implementer", roots=(workspace,))
        reviewer_ctx = ToolContext(agent_id="y", role="reviewer", roots=(workspace,))
        bash_tool = builtin_registry().get("bash")
        assert bash_tool is not None
        assert (
            evaluate_tool_call(bash_tool, {"command": "ls deploy"}, implementer_ctx).decision
            == "allow"
        )
        assert (
            evaluate_tool_call(bash_tool, {"command": "ls deploy"}, reviewer_ctx).decision == "deny"
        )

    def test_wildcard_applies_to_matches_an_empty_role(self, workspace: Path) -> None:
        _write_policy("wildcard-block", r"\bnukeit\b", "block")  # applies_to defaults to ["*"]
        bare_ctx = ToolContext(agent_id="z", roots=(workspace,))  # role="" -- the default
        bash_tool = builtin_registry().get("bash")
        assert bash_tool is not None
        assert evaluate_tool_call(bash_tool, {"command": "ls nukeit"}, bare_ctx).decision == "deny"


class TestBlockAndRequireApprovalActions:
    """Acceptance: a block action denies; a require_approval action asks and
    then executes iff granted."""

    def test_block_action_denies_outright_and_handler_never_runs(self, ctx: ToolContext) -> None:
        _write_policy("hard-block", r"\bnuke\b", "block", message="absolutely not")
        ran = {"handler": False}
        registry = ToolRegistry()
        registry.register(_recording_tool("custom", "write", ran))

        res = dispatch_tool(
            _call("custom", json.dumps({"x": "please nuke everything"})), ctx, registry
        )

        assert res.denied and not res.executed and ran["handler"] is False


class TestWaitForApprovalUnit:
    """Direct unit coverage of core/approval.py's new synchronous waiter.
    Every test here injects sleep/clock explicitly -- none ever sleeps for
    real, and none depends on TOOL_APPROVAL_TIMEOUT."""

    def _token(self) -> str:
        return _approval.approval_create("demo", "implementer", "do the risky thing")

    def test_already_granted_returns_immediately_without_sleeping(self) -> None:
        token = self._token()
        _approval.approval_grant(token)
        sleeps: list[float] = []
        result = _approval.wait_for_approval(
            token, timeout=10, poll_interval=1, sleep=sleeps.append, clock=lambda: 0.0
        )
        assert result == _approval.ApprovalWaitResult("granted", token)
        assert sleeps == []

    def test_a_grant_arriving_during_a_poll_is_seen_next_iteration(self) -> None:
        token = self._token()

        def _sleep_and_grant(_seconds: float) -> None:
            _approval.approval_grant(token)

        result = _approval.wait_for_approval(
            token, timeout=10, poll_interval=1, sleep=_sleep_and_grant, clock=lambda: 0.0
        )
        assert result.state == "granted" and not result.timed_out

    def test_already_denied_returns_immediately(self) -> None:
        token = self._token()
        _approval.approval_deny(token)
        result = _approval.wait_for_approval(
            token, timeout=10, poll_interval=1, sleep=lambda s: None, clock=lambda: 0.0
        )
        assert result == _approval.ApprovalWaitResult("denied", token)

    def test_timeout_resolves_to_denied_and_never_sleeps_past_the_deadline(self) -> None:
        token = self._token()
        ticks = iter([0.0, 100.0])  # deadline computed at 0.0 + 10; next check is past it
        sleeps: list[float] = []
        result = _approval.wait_for_approval(
            token, timeout=10, poll_interval=1, sleep=sleeps.append, clock=lambda: next(ticks)
        )
        assert result == _approval.ApprovalWaitResult("denied", token, timed_out=True)
        assert sleeps == []
        # Fail-closed: the record itself is now denied, never left pending.
        assert _approval.approval_get(token)["state"] == "denied"

    def test_timeout_writes_the_same_audit_entry_the_sweep_writes(self) -> None:
        token = self._token()
        ticks = iter([0.0, 100.0])
        _approval.wait_for_approval(
            token, timeout=10, poll_interval=1, sleep=lambda s: None, clock=lambda: next(ticks)
        )
        entries = [e for e in _audit.read_audit() if e["action"] == "approval.deny"]
        assert (
            entries
            and f"token={token}" in entries[-1]["detail"]
            and "channel=timeout" in entries[-1]["detail"]
        )

    def test_poll_interval_is_honoured_not_busy_spun(self) -> None:
        token = self._token()
        sleeps: list[float] = []
        ticks = iter([0.0, 1.0, 2.0, 100.0])
        _approval.wait_for_approval(
            token, timeout=10, poll_interval=3, sleep=sleeps.append, clock=lambda: next(ticks)
        )
        assert sleeps == [3, 3]


class TestDispatchToolApprovalRouting:
    """End-to-end through the real dispatch_tool chokepoint: an `ask`
    verdict blocks on the real approval store and either executes (granted)
    or stays refused (denied/timeout) -- with the module-level `_time`
    monkeypatched, so this still never sleeps for real."""

    def test_require_approval_call_executes_once_granted(
        self, ctx: ToolContext, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(_cfg, "TOOL_APPROVAL_TIMEOUT", 10, raising=True)
        _write_policy("custom-approve-write", r"launch-codes", "require_approval")

        def _grant_the_pending_call(_seconds: float) -> None:
            pending = _approval.list_pending()
            assert pending, "dispatch_tool should have created a pending approval by now"
            assert 'custom x="launch-codes"' in pending[0]["action"]
            _approval.approval_grant(pending[0]["token"])

        monkeypatch.setattr(
            _approval,
            "_time",
            types.SimpleNamespace(sleep=_grant_the_pending_call, monotonic=_real_time.monotonic),
            raising=True,
        )

        ran = {"handler": False}
        registry = ToolRegistry()
        registry.register(_recording_tool("custom", "write", ran))

        res = dispatch_tool(_call("custom", json.dumps({"x": "launch-codes"})), ctx, registry)

        assert ran["handler"] is True
        assert res.executed and res.ok and res.decision == "allow"

    def test_require_approval_call_stays_refused_when_denied(
        self, ctx: ToolContext, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(_cfg, "TOOL_APPROVAL_TIMEOUT", 10, raising=True)
        _write_policy("custom-approve-write-2", r"launch-codes", "require_approval")

        def _deny_the_pending_call(_seconds: float) -> None:
            pending = _approval.list_pending()
            _approval.approval_deny(pending[0]["token"])

        monkeypatch.setattr(
            _approval,
            "_time",
            types.SimpleNamespace(sleep=_deny_the_pending_call, monotonic=_real_time.monotonic),
            raising=True,
        )

        ran = {"handler": False}
        registry = ToolRegistry()
        registry.register(_recording_tool("custom", "write", ran))

        res = dispatch_tool(_call("custom", json.dumps({"x": "launch-codes"})), ctx, registry)

        assert ran["handler"] is False
        assert res.denied and not res.executed

    def test_an_unanswered_approval_times_out_to_denied_and_does_not_execute(
        self, ctx: ToolContext
    ) -> None:
        """Acceptance: approval timeout denies and does not execute. The
        module default TOOL_APPROVAL_TIMEOUT=0 from `_hermetic` above makes
        this resolve on the very first deadline check -- no sleep, real or
        fake, is ever needed."""
        _write_policy("custom-approve-write-3", r"launch-codes", "require_approval")
        ran = {"handler": False}
        registry = ToolRegistry()
        registry.register(_recording_tool("custom", "write", ran))

        res = dispatch_tool(_call("custom", json.dumps({"x": "launch-codes"})), ctx, registry)

        assert ran["handler"] is False
        assert res.denied and not res.executed
        assert "approval" in res.reason.lower()


class TestAuditTrail:
    """Acceptance: every gated decision leaves an audit entry."""

    def test_a_classifier_gated_call_is_audited_end_to_end(self, ctx: ToolContext) -> None:
        res = dispatch_tool(_call("bash", json.dumps({"command": "rm x"})), ctx, builtin_registry())
        assert res.denied
        actions = _audit_actions()
        assert "tool.ask" in actions  # the gate's own decision
        assert "approval.deny" in actions  # the timeout resolution

    def test_a_warn_hit_leaves_a_record_even_though_the_call_still_runs(
        self, ctx: ToolContext
    ) -> None:
        _write_policy("noisy-warn", r"\bwarnme\b", "warn")
        res = dispatch_tool(
            _call("bash", json.dumps({"command": "ls warnme"})), ctx, builtin_registry()
        )
        assert res.executed and res.decision == "allow"
        assert "tool.warn" in _audit_actions()

    def test_a_block_decision_is_audited_with_secrets_redacted(self, ctx: ToolContext) -> None:
        _write_policy("block-secret-write", r"topsecret", "block")
        secret = "api_key=abcdefghijklmnopqrstuvwxyz0123456789"
        res = dispatch_tool(
            _call("write", json.dumps({"path": "notes.txt", "content": f"topsecret {secret}"})),
            ctx,
            builtin_registry(),
        )
        assert res.denied
        entries = [e for e in _audit.read_audit() if e["action"] == "tool.deny"]
        assert entries
        assert secret not in entries[-1]["detail"]
        assert "[REDACTED]" in entries[-1]["detail"]

    def test_an_allowed_call_with_no_policy_hit_is_not_audited(self, ctx: ToolContext) -> None:
        res = dispatch_tool(_call("bash", json.dumps({"command": "ls"})), ctx, builtin_registry())
        assert res.decision == "allow" and res.executed
        assert _audit_actions() == []
