"""Shared fixtures for the turn loop's collaborators (``agent/loop_*.py``)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from docket.agent.loop_state import TurnState
from docket.agent.loop_types import LoopConfig
from docket.agent.ports import ChatResponse
from docket.agent.tools.registry import ToolContext, ToolRegistry


class NoBackend:
    """A backend that must never be called: the collaborators under test make no exchange."""

    def complete(self, *args: object, **kwargs: object) -> ChatResponse:
        raise AssertionError("this test makes no backend call")


@pytest.fixture
def make_turn_state(tmp_path: Path) -> Callable[..., TurnState]:
    """Build a ``TurnState`` with a frozen clock; keyword arguments override its fields."""

    def build(cfg: LoopConfig | None = None, **overrides: Any) -> TurnState:
        fields: dict[str, Any] = {
            "backend": NoBackend(),
            "ctx": ToolContext(
                agent_id="demo-agent", role="implementer", project="demo", roots=(tmp_path,)
            ),
            "session_key": "agent:demo-agent:demo",
            "cfg": cfg or LoopConfig(),
            "clock": lambda: 0.0,
            "started": 0.0,
            "project": "demo",
            "trace_key": "agent:demo-agent:demo",
            "context_window": None,
            "output_reserve": 100,
            "request_max_tokens": None,
            "call_max_tokens": None,
            "registry": ToolRegistry(),
            "system_prompt": "",
            "tool_specs": [],
        }
        fields.update(overrides)
        return TurnState(**fields)

    return build
