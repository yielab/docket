"""The `no_progress` stop: a turn whose rounds keep repeating already-seen results stops.

Drives the real `run_agent_turn` with a scripted chat port; the loop's other bounds are
covered in `tests/integration/test_agent_loop.py`.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

import pytest
from tests.conftest import repoint_docket_home

import docket.config as _cfg
from docket.core import agent_loop as _loop
from docket.core.llm import (
    ChatMessage,
    ChatResponse,
    TokenUsage,
    ToolCall,
    ToolSpec,
    assistant,
)
from docket.core.tools import Tool as _Tool
from docket.core.tools import ToolContext, ToolRegistry
from docket.edges.adapters.toolbox import ToolOutcome

SUBJECT = "docket.core.agent_loop"


class _Backend:
    """Answers each round from *script*(round_number); a ``None`` step is the final message."""

    def __init__(self, script: Callable[[int], tuple[str, str] | None]) -> None:
        self._script = script
        self.rounds = 0

    def complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        tools: Sequence[ToolSpec] = (),
        max_tokens: int | None = None,
        temperature: float | None = None,
        timeout: int = 120,
    ) -> ChatResponse:
        self.rounds += 1
        step = self._script(self.rounds)
        usage = TokenUsage(input_tokens=10, output_tokens=5)
        if step is None:
            return ChatResponse(
                ok=True, message=assistant("done"), finish_reason="stop", usage=usage
            )
        name, args = step
        call = ToolCall(id=f"c{self.rounds}", name=name, arguments=args)
        return ChatResponse(
            ok=True,
            message=assistant("", tool_calls=[call]),
            finish_reason="tool_calls",
            usage=usage,
        )


@pytest.fixture(autouse=True)
def _isolate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repoint_docket_home(monkeypatch, tmp_path / "home")


@pytest.fixture
def registry() -> ToolRegistry:
    state = {"file": "A"}

    def _read(args: dict[str, object], ctx: ToolContext) -> ToolOutcome:
        return ToolOutcome(ok=True, content=state["file"])

    def _edit(args: dict[str, object], ctx: ToolContext) -> ToolOutcome:
        state["file"] = str(args["to"])
        return ToolOutcome(ok=True, content=f"wrote {args['to']}")

    reg = ToolRegistry()
    schema = {"type": "object", "properties": {}}
    reg.register(_Tool(name="read", description="Read.", parameters=schema, handler=_read))
    reg.register(_Tool(name="edit", description="Edit.", parameters=schema, handler=_edit))
    return reg


@pytest.fixture
def ctx(tmp_path: Path) -> ToolContext:
    return ToolContext(
        agent_id="demo-agent", role="implementer", project="demo", roots=(tmp_path,), timeout=10
    )


def _run(
    backend: _Backend, registry: ToolRegistry, ctx: ToolContext, **cfg: int
) -> _loop.AgentLoopResult:
    config = _loop.LoopConfig(max_iterations=50, max_tool_calls=500, **cfg)
    return _loop.run_agent_turn(backend, registry, ctx, "agent:demo:default", "go", config=config)


def test_repeating_the_same_read_stops_after_n_plus_one_rounds(
    registry: ToolRegistry, ctx: ToolContext
) -> None:
    backend = _Backend(lambda n: ("read", '{"n": 1}'))
    result = _run(backend, registry, ctx, no_progress_rounds=3)
    assert result.ok is False
    assert result.stop_reason == "no_progress"
    assert result.failure_kind == "invalid_output"
    assert "read" in result.error
    assert backend.rounds == 4  # one new round, then three repeats


def test_argument_key_order_does_not_hide_a_repeat(
    registry: ToolRegistry, ctx: ToolContext
) -> None:
    args = ['{"a": 1, "b": 2}', '{"b": 2, "a": 1}']
    backend = _Backend(lambda n: ("read", args[n % 2]))
    result = _run(backend, registry, ctx, no_progress_rounds=2)
    assert result.stop_reason == "no_progress"
    assert backend.rounds == 3


def test_an_edit_flipping_a_file_back_and_forth_stops(
    registry: ToolRegistry, ctx: ToolContext
) -> None:
    flips = [("edit", '{"to": "B"}'), ("edit", '{"to": "A"}')]
    backend = _Backend(lambda n: flips[(n - 1) % 2])
    result = _run(backend, registry, ctx, no_progress_rounds=3)
    assert result.stop_reason == "no_progress"
    assert "edit" in result.error
    assert backend.rounds == 5  # two new rounds, then three repeats


def test_results_that_differ_every_round_reach_the_final_message(
    registry: ToolRegistry, ctx: ToolContext
) -> None:
    def script(n: int) -> tuple[str, str] | None:
        return None if n > 8 else ("edit", json.dumps({"to": f"v{n}"}))

    result = _run(_Backend(script), registry, ctx, no_progress_rounds=3)
    assert result.ok is True
    assert result.stop_reason == "final_message"


def test_a_new_round_resets_the_repeat_count(registry: ToolRegistry, ctx: ToolContext) -> None:
    seq = [("read", '{"n": 1}')] * 3 + [("read", '{"n": 2}')] + [("read", '{"n": 1}')] * 2
    backend = _Backend(lambda n: seq[n - 1] if n <= len(seq) else None)
    result = _run(backend, registry, ctx, no_progress_rounds=3)
    assert result.stop_reason == "final_message"


def test_zero_disables_the_check(registry: ToolRegistry, ctx: ToolContext) -> None:
    backend = _Backend(lambda n: ("read", '{"n": 1}') if n <= 10 else None)
    result = _run(backend, registry, ctx, no_progress_rounds=0)
    assert result.stop_reason == "final_message"
    assert backend.rounds == 11


def test_default_comes_from_the_config_constant() -> None:
    assert _loop.LoopConfig().no_progress_rounds == _cfg.AGENT_LOOP_NO_PROGRESS_ROUNDS == 3


def test_env_override_is_honoured(tmp_path: Path) -> None:
    code = (
        "import docket.config as c; from docket.core.agent_loop import LoopConfig;"
        "print(c.AGENT_LOOP_NO_PROGRESS_ROUNDS, LoopConfig().no_progress_rounds)"
    )
    env = {**os.environ, "AGENT_LOOP_NO_PROGRESS_ROUNDS": "7", "DOCKET_HOME": str(tmp_path)}
    out = subprocess.run(
        [sys.executable, "-c", code], env=env, capture_output=True, text=True, check=True
    )
    assert out.stdout.split() == ["7", "7"]
