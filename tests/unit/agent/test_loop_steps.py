"""The tool step (`agent/loop_steps.py`): batch gating, one atomic append, no-progress."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from docket.agent import loop_steps as _steps
from docket.agent.loop_state import TurnState
from docket.agent.loop_steps import ToolStep, _ProgressDetector
from docket.agent.loop_types import LoopConfig
from docket.agent.ports import ChatMessage, TokenUsage, ToolCall, assistant
from docket.agent.tools.builtins.toolbox import ToolOutcome
from docket.agent.tools.registry import Tool, ToolRegistry

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


class TestDispatchToolBatch:
    """A batch is either wholly dispatched and persisted once, or not dispatched at all."""

    def test_a_batch_over_the_tool_call_ceiling_dispatches_nothing(
        self, make_turn_state: MakeState, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        appended: list[Any] = []
        monkeypatch.setattr(_steps, "append_messages", lambda *a, **k: appended.append(a))
        state = make_turn_state(
            LoopConfig(max_tool_calls=2), registry=_echo_registry(), tool_calls_executed=1
        )
        calls = [ToolCall(id=f"c{i}", name="echo", arguments="{}") for i in range(2)]
        stop = ToolStep(state).dispatch_tool_batch([], assistant("", calls), TokenUsage())
        assert stop is not None
        assert stop.stop_reason == "max_tool_calls"
        assert "none of this batch was executed" in stop.error
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
        stop = ToolStep(state).dispatch_tool_batch(messages, message, TokenUsage())
        assert stop is None
        assert state.tool_calls_executed == 1
        assert len(appended) == 1
        assert [m.role for m in appended[0]] == ["assistant", "tool"]
        assert messages == appended[0]
        assert appended[0][1].content == "hi"

    def test_consecutive_denials_reach_the_configured_limit(
        self, make_turn_state: MakeState, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(_steps, "append_messages", lambda *a, **k: None)
        state = make_turn_state(LoopConfig(max_consecutive_tool_denials=1), registry=ToolRegistry())
        message = assistant("", [ToolCall(id="c1", name="missing", arguments="{}")])
        stop = ToolStep(state).dispatch_tool_batch([], message, TokenUsage())
        assert stop is not None
        assert stop.stop_reason == "tool_denials"
        assert "count=1" in stop.error


class TestStopIfNoProgress:
    """The detector is created lazily from the config and ends the turn at its limit."""

    def test_repeated_rounds_end_the_turn_with_no_progress(
        self, make_turn_state: MakeState
    ) -> None:
        step = ToolStep(make_turn_state(LoopConfig(no_progress_rounds=1)))
        entries = [_ProgressDetector.entry(ToolCall(id="c", name="echo"), True, "x")]
        assert step.stop_if_no_progress(entries) is None
        stop = step.stop_if_no_progress(entries)
        assert stop is not None
        assert stop.stop_reason == "no_progress"
