"""The tool step (`agent/loop_steps.py`): batch gating, one atomic append, no-progress."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from docket.agent import loop_steps as _steps
from docket.agent.loop_budget import TurnBudget
from docket.agent.loop_state import TurnState
from docket.agent.loop_steps import ToolStep, _ProgressDetector
from docket.agent.loop_types import LoopConfig
from docket.agent.ports import CapabilityGap, ChatMessage, TokenUsage, ToolCall, assistant
from docket.agent.tools.builtins.toolbox import ToolOutcome
from docket.agent.tools.capability_gap import PodOffer
from docket.agent.tools.registry import Tool, ToolRegistry
from docket.kernel import untrusted

SUBJECT = "docket.agent.loop_steps"

MakeState = Callable[..., TurnState]


def _echo_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        Tool(
            name="echo",
            description="Echo the given text back.",
            parameters={"type": "object", "properties": {"text": {"type": "string"}}},
            handler=lambda args, ctx: ToolOutcome(ok=True, content=str(args.get("text", ""))),
            kind="read",
        )
    )
    return registry


class TestProgressDetector:
    """A round counts as repeated when its canonical fingerprint was already seen."""

    def _round(self, args: str = '{"a": 1}', output: str = "same") -> list[Any]:
        call = ToolCall(id="c", name="echo", arguments=args)
        return [_ProgressDetector.entry(call, True, output)]

    def test_arguments_are_compared_canonically(self) -> None:
        assert self._round('{"a": 1, "b": 2}') == self._round('{"b":2,"a":1}')

    def test_the_limit_trips_on_consecutive_repeats_only(self) -> None:
        detector = _ProgressDetector(limit=2)
        assert not detector.observe(self._round())
        assert not detector.observe(self._round())
        assert not detector.observe(self._round(output="different"))
        assert not detector.observe(self._round())
        assert detector.observe(self._round())
        assert "2 consecutive tool rounds repeated" in detector.error()

    def test_a_zero_limit_disables_the_check(self) -> None:
        detector = _ProgressDetector(limit=0)
        for _ in range(5):
            assert not detector.observe(self._round())


def _framed_hi(state: Any) -> str:
    """The echo tool's result as the turn frames it, with the turn's delimiter."""
    return untrusted.frame("result of echo", "hi", delimiter=state.untrusted_delimiter)


class TestDispatchToolBatch:
    """A batch is either wholly dispatched and persisted once, or not dispatched at all."""

    def test_a_batch_over_the_tool_call_ceiling_dispatches_nothing_and_selects_the_landing(
        self, make_turn_state: MakeState, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        appended: list[Any] = []
        monkeypatch.setattr(_steps, "append_messages", lambda *a, **k: appended.append(a))
        state = make_turn_state(
            LoopConfig(max_tool_calls=2), registry=_echo_registry(), tool_calls_executed=1
        )
        calls = [ToolCall(id=f"c{i}", name="echo", arguments="{}") for i in range(2)]
        stop = ToolStep(state, TurnBudget(state)).dispatch_tool_batch(
            [], assistant("", calls), TokenUsage()
        )
        assert stop is None
        assert state.landing == "max_tool_calls"
        assert "none of this batch was executed" in state.landing_error
        assert state.tool_calls_executed == 1
        assert appended == []

    def test_an_executed_batch_is_persisted_as_one_atomic_unit(
        self, make_turn_state: MakeState, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        appended: list[list[ChatMessage]] = []
        monkeypatch.setattr(
            _steps, "append_messages", lambda key, msgs, **kw: appended.append(list(msgs))
        )
        state = make_turn_state(registry=_echo_registry())
        message = assistant("plan", [ToolCall(id="c1", name="echo", arguments='{"text": "hi"}')])
        messages: list[ChatMessage] = []
        stop = ToolStep(state, TurnBudget(state)).dispatch_tool_batch(
            messages, message, TokenUsage()
        )
        assert stop is None
        assert state.tool_calls_executed == 1
        assert len(appended) == 1
        assert [m.role for m in appended[0]] == ["assistant", "tool"]
        assert messages == appended[0]
        assert appended[0][1].content == _framed_hi(state)

    def test_the_persisted_results_are_byte_identical_to_what_dispatch_returned(
        self, make_turn_state: MakeState, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A due budget notice is a request matter: it is not appended to a stored result."""
        appended: list[list[ChatMessage]] = []
        monkeypatch.setattr(
            _steps, "append_messages", lambda key, msgs, **kw: appended.append(list(msgs))
        )
        state = make_turn_state(
            LoopConfig(max_tool_calls=4), registry=_echo_registry(), tool_calls_executed=2
        )
        message = assistant("", [ToolCall(id="c1", name="echo", arguments='{"text": "hi"}')])
        messages: list[ChatMessage] = []
        assert (
            ToolStep(state, TurnBudget(state)).dispatch_tool_batch(messages, message, TokenUsage())
            is None
        )
        assert [m.content for m in appended[0] if m.role == "tool"] == [_framed_hi(state)]
        assert messages[-1].content == _framed_hi(state)
        assert not state.notice_sent

    def test_consecutive_denials_reach_the_configured_limit(
        self, make_turn_state: MakeState, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(_steps, "append_messages", lambda *a, **k: None)
        state = make_turn_state(LoopConfig(max_consecutive_tool_denials=1), registry=ToolRegistry())
        message = assistant("", [ToolCall(id="c1", name="missing", arguments="{}")])
        stop = ToolStep(state, TurnBudget(state)).dispatch_tool_batch([], message, TokenUsage())
        assert stop is not None
        assert stop.stop_reason == "tool_denials"
        assert "count=1" in stop.error


class TestCapabilityMissingStop:
    """A gap in the pod's configuration ends the turn after its batch is persisted."""

    def _state(self, make_turn_state: MakeState) -> TurnState:
        registry = _echo_registry()
        registry.offer = PodOffer(
            pod="demo",
            holdable=frozenset({"echo", "write"}),
            record_sets=frozenset(),
            fetch_declarable=False,
        )
        return make_turn_state(registry=registry)

    def test_the_second_call_meeting_a_gap_stops_the_turn_after_the_batch(
        self, make_turn_state: MakeState, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        appended: list[list[ChatMessage]] = []
        monkeypatch.setattr(
            _steps, "append_messages", lambda key, msgs, **kw: appended.append(list(msgs))
        )
        state = self._state(make_turn_state)
        calls = [
            ToolCall(id="c1", name="echo", arguments='{"text": "hi"}'),
            ToolCall(id="c2", name="write", arguments="{}"),
            ToolCall(id="c3", name="echo", arguments='{"text": "again"}'),
        ]
        stop = ToolStep(state, TurnBudget(state)).dispatch_tool_batch(
            [], assistant("", calls), TokenUsage()
        )

        assert stop is not None
        assert stop.ok is False
        assert stop.stop_reason == "capability_missing"
        assert stop.failure_kind == "capability_missing"
        assert isinstance(stop.capability_gap, CapabilityGap)
        assert (stop.capability_gap.kind, stop.capability_gap.name) == ("tool", "write")
        assert stop.error == f"implementer needs tool 'write': {stop.capability_gap.fix}"
        assert [m.role for m in appended[0]] == ["assistant", "tool", "tool", "tool"]

    def test_a_denial_that_is_not_a_gap_does_not_stop_the_turn(
        self, make_turn_state: MakeState, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(_steps, "append_messages", lambda *a, **k: None)
        state = self._state(make_turn_state)
        message = assistant("", [ToolCall(id="c1", name="teleport", arguments="{}")])

        assert (
            ToolStep(state, TurnBudget(state)).dispatch_tool_batch([], message, TokenUsage())
            is None
        )


class TestStopIfNoProgress:
    """The detector is created lazily from the config and ends the turn at its limit."""

    def test_repeated_rounds_end_the_turn_with_no_progress(
        self, make_turn_state: MakeState
    ) -> None:
        state = make_turn_state(LoopConfig(no_progress_rounds=1))
        step = ToolStep(state, TurnBudget(state))
        entries = [_ProgressDetector.entry(ToolCall(id="c", name="echo"), True, "x")]
        assert step.stop_if_no_progress(entries) is None
        stop = step.stop_if_no_progress(entries)
        assert stop is not None
        assert stop.stop_reason == "no_progress"
