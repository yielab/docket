"""Fixtures shared by the agent-loop tests."""

from __future__ import annotations

import dataclasses
from collections.abc import Iterator
from pathlib import Path

import pytest

from docket.agent.tools.builtins.toolbox import ToolOutcome
from docket.agent.tools.registry import Tool as _Tool
from docket.agent.tools.registry import ToolContext, ToolRegistry
from docket.kernel.home import Home, current_home, use_home


@pytest.fixture(autouse=True)
def _isolate_stores(tmp_path: Path) -> Iterator[None]:
    with (
        use_home(Home(tmp_path)),
        use_home(dataclasses.replace(current_home(), tool_approval_timeout=0)),
    ):
        yield


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "notes.md").write_text("alpha\nbeta\n")
    return ws


@pytest.fixture
def registry() -> ToolRegistry:
    """A tiny registry with one harmless read-only tool -- enough to exercise
    dispatch without pulling in bash/exec classification noise."""
    reg = ToolRegistry()
    reg.register(
        _Tool(
            name="echo",
            description="Echo the given text back.",
            parameters={
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
            handler=lambda args, ctx: ToolOutcome(ok=True, content=str(args.get("text", ""))),
            kind="read",
        )
    )
    return reg


@pytest.fixture
def ctx(workspace: Path) -> ToolContext:
    return ToolContext(
        agent_id="demo-agent", role="implementer", project="demo", roots=(workspace,), timeout=10
    )
