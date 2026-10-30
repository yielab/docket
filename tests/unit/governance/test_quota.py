"""A send quota: N executions per pod per window, counted after the handler ran."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from docket.agent.ports import ToolCall
from docket.agent.tools.builtins.toolbox import ToolOutcome
from docket.agent.tools.registry import Pregrant, Tool, ToolContext, ToolRegistry, dispatch_tool
from docket.governance import approval_pregrant as _pregrant
from docket.governance import audit as _audit
from docket.governance import gate as _gate
from docket.governance import policy as _policy
from docket.governance import quota as _quota
from docket.kernel.clock import use_clock
from docket.kernel.home import current_home
from docket.kernel.operator_contract import canonical_args_digest

SUBJECT = "docket.governance.quota"

SEND = "mcp__outbox__send"
LIMIT_DAY = "kind: policy\nname: send-cap\nappliesTo: [actor]\nlimit: {kind: send, count: 2, per: day}\nthen: block\n"


@dataclass
class _Clock:
    at: datetime = field(default_factory=lambda: datetime(2026, 10, 30, 9, 0, tzinfo=UTC))

    def now(self) -> datetime:
        return self.at

    def monotonic(self) -> float:
        return self.at.timestamp()


@pytest.fixture()
def clock() -> Any:
    fake = _Clock()
    with use_clock(fake):
        yield fake


def _policy_file(text: str, name: str = "send-cap.yaml") -> None:
    directory = current_home().policies_dir
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_text(text, encoding="utf-8")


def _ctx(pod: str = "demo", *grants: Pregrant) -> ToolContext:
    return ToolContext(
        agent_id=f"{pod}-actor", role="actor", project=pod, approval_mode="refuse", pregrants=grants
    )


def _rows(pod: str = "demo") -> list[dict[str, Any]]:
    return _quota.quota_rows(pod, _policy.limits_for(None, pod))


def _world() -> tuple[ToolRegistry, list[dict[str, Any]]]:
    sent: list[dict[str, Any]] = []

    def handler(args: dict[str, Any], _ctx: ToolContext) -> ToolOutcome:
        sent.append(args)
        return ToolOutcome(ok=True, content="sent")

    registry = ToolRegistry()
    registry.register(
        Tool(SEND, "send", {"type": "object", "properties": {}}, handler, kind="send")
    )
    return registry, sent


def _send(registry: ToolRegistry, ctx: ToolContext, n: int, *, grant: bool = True) -> Any:
    """Send call number *n*, pre-granted by a person unless *grant* is False."""
    args = {"to": "guest@example.test", "n": n}
    if grant:
        digest = canonical_args_digest(SEND, args)
        token = _pregrant.create_pregrant(ctx.project, ctx.role, SEND, digest, channel="cli")
        ctx.pregrants = (*ctx.pregrants, Pregrant(token, SEND, digest))
    return dispatch_tool(ToolCall(f"c{n}", SEND, json.dumps(args)), ctx, registry)


class TestTheClause:
    @pytest.mark.parametrize(
        "limit",
        [
            "{kind: send, count: 2, per: day}",
            "{tool: mcp__outbox__send, count: 5, per: hour}",
        ],
    )
    def test_a_valid_limit_passes_the_validator(self, limit: str) -> None:
        _policy_file(f"kind: policy\nname: cap\nappliesTo: [actor]\nlimit: {limit}\nthen: block\n")

        assert _policy.validate_policy(current_home().policies_dir / "send-cap.yaml") == ""

    @pytest.mark.parametrize(
        ("body", "needle"),
        [
            ("limit: {kind: send, count: 0, per: day}", "count"),
            ("limit: {kind: send, count: true, per: day}", "count"),
            ("limit: {kind: send, count: 2, per: week}", "per"),
            ("limit: {kind: write, count: 2, per: day}", "kind"),
            ("limit: {count: 2, per: day}", "kind"),
            ("limit: {kind: send, tool: x, count: 2, per: day}", "kind"),
            ("limit: {tool: '', count: 2, per: day}", "tool"),
            ("limit: {kind: send, count: 2, per: day, burst: 1}", "burst"),
            ("limit: 3", "limit"),
            ("limit: {kind: send, count: 2, per: day}\nwhen: {tool: x}", "when"),
            ("limit: {kind: send, count: 2, per: day}\non: output", "on"),
        ],
    )
    def test_a_malformed_limit_is_rejected_naming_the_field(self, body: str, needle: str) -> None:
        _policy_file(f"kind: policy\nname: cap\nappliesTo: [actor]\n{body}\nthen: block\n")

        error = _policy.validate_policy(current_home().policies_dir / "send-cap.yaml")

        assert error and needle in error

    def test_a_limit_that_does_not_block_is_rejected(self) -> None:
        _policy_file(
            "kind: policy\nname: cap\nappliesTo: [actor]\nlimit: {kind: send, count: 2, per: day}\nthen: ask\n"
        )

        assert "block" in _policy.validate_policy(current_home().policies_dir / "send-cap.yaml")

    def test_a_limit_does_not_fire_as_a_match(self) -> None:
        _policy_file(LIMIT_DAY)

        hit = _policy.policy_eval_detail(
            "actor",
            "pre_tool_call",
            f"{SEND} to='x'",
            project="demo",
            call=_policy.ToolCallFacts(tool=SEND, args={}, branch_of=lambda: ""),
        )

        assert hit.action == "allow" and hit.policy_id == ""


class TestTheCount:
    def test_two_sends_run_and_the_third_is_blocked_naming_the_count_and_window(
        self, clock: _Clock
    ) -> None:
        _policy_file(LIMIT_DAY)
        registry, sent = _world()
        ctx = _ctx()

        first, second = _send(registry, ctx, 1), _send(registry, ctx, 2)
        third = _send(registry, ctx, 3)

        assert first.executed and second.executed and not third.executed
        assert len(sent) == 2
        assert third.denied and third.denial_kind == "gate_denied"
        assert "2/2 per day" in third.reason and third.policy_id == "send-cap"

    def test_the_blocked_send_is_audited_as_a_block_and_opens_no_approval(
        self, clock: _Clock
    ) -> None:
        _policy_file(LIMIT_DAY)
        registry, _sent = _world()
        ctx = _ctx()
        _send(registry, ctx, 1)
        _send(registry, ctx, 2)

        _send(registry, ctx, 3, grant=False)

        rows = [e for e in _audit.read_audit() if e["action"] == "tool.send"]
        assert len(rows) == 3
        assert "decision=deny" in rows[-1]["detail"]
        assert "policy_id='send-cap' policy_action='block'" in rows[-1]["detail"]
        assert "tool.ask" not in [e["action"] for e in _audit.read_audit()][-3:]

    def test_a_refused_action_does_not_count(self, clock: _Clock) -> None:
        _policy_file(LIMIT_DAY)
        _policy_file(
            "kind: policy\nname: no-ana\nappliesTo: [actor]\nwhen: {matches: ana@}\nthen: block\n",
            "no-ana.yaml",
        )
        registry, sent = _world()
        ctx = _ctx()
        denied = dispatch_tool(
            ToolCall("c0", SEND, json.dumps({"to": "ana@example.test"})), ctx, registry
        )
        unasked = _send(registry, ctx, 1, grant=False)  # refuse mode, no pre-grant: nobody asked

        assert denied.denied and unasked.denied and not sent
        assert _rows()[0]["used"] == 0
        assert _send(registry, ctx, 2).executed and _send(registry, ctx, 3).executed

    def test_the_window_rolls(self, clock: _Clock) -> None:
        _policy_file(LIMIT_DAY)
        registry, sent = _world()
        ctx = _ctx()
        _send(registry, ctx, 1)
        clock.at += timedelta(hours=20)
        _send(registry, ctx, 2)
        assert _send(registry, ctx, 3).denied

        clock.at += timedelta(hours=5)  # the first send is now 25 hours old

        assert _send(registry, ctx, 4).executed
        assert len(sent) == 3
        assert _send(registry, ctx, 5).denied  # the second (5 hours old) and the fourth

    def test_an_hour_limit_rolls_within_the_day(self, clock: _Clock) -> None:
        _policy_file(LIMIT_DAY.replace("count: 2, per: day", "count: 1, per: hour"))
        registry, _sent = _world()
        ctx = _ctx()
        _send(registry, ctx, 1)
        assert "1/1 per hour" in _send(registry, ctx, 2).reason

        clock.at += timedelta(minutes=61)

        assert _send(registry, ctx, 3).executed

    def test_the_counter_is_the_pods(self, clock: _Clock) -> None:
        _policy_file(LIMIT_DAY)
        registry, _sent = _world()
        busy, other = _ctx("busy"), _ctx("other")
        _send(registry, busy, 1)
        _send(registry, busy, 2)

        assert _send(registry, busy, 3).denied
        assert _send(registry, other, 4).executed

    def test_a_tool_limit_counts_only_that_tool(self, clock: _Clock) -> None:
        _policy_file(
            f"kind: policy\nname: one\nappliesTo: [actor]\nlimit: {{tool: {SEND}, count: 1, per: day}}\nthen: block\n"
        )
        registry, _sent = _world()
        ctx = _ctx()
        _send(registry, ctx, 1)

        assert _send(registry, ctx, 2).denied
        rows = _rows()
        assert rows == [{"scope": SEND, "used": 1, "count": 1, "per": "day"}]

    def test_a_pod_without_a_quota_counts_nothing_that_blocks(self, clock: _Clock) -> None:
        registry, _sent = _world()
        ctx = _ctx()

        assert all(_send(registry, ctx, n).executed for n in range(1, 6))
        assert _rows() == []

    def test_the_counter_lives_under_the_state_dir_and_survives_a_bad_file(
        self, clock: _Clock
    ) -> None:
        _policy_file(LIMIT_DAY)
        registry, _sent = _world()
        _send(registry, _ctx(), 1)

        counter = current_home().quota_file
        assert counter.is_file() and counter.is_relative_to(current_home().state_dir)

        counter.write_text("{not json", encoding="utf-8")
        assert _rows()[0]["used"] == 0

    def test_a_gate_that_only_governs_does_not_count(self, clock: _Clock) -> None:
        _policy_file(LIMIT_DAY)
        call = _gate.GateCall(
            Tool(SEND, "", {}, lambda a, c: ToolOutcome(ok=True), kind="send"), "c", {}
        )

        for _ in range(3):
            _gate.govern(call, _ctx())

        assert _rows()[0]["used"] == 0
