"""Small readers of a ``ToolRegistry`` for tool tests."""

from __future__ import annotations

from docket.agent.tools.registry import Tool, ToolRegistry


def tool_named(registry: ToolRegistry, name: str) -> Tool:
    """The tool *name* in *registry*, which must hold it."""
    tool = registry.get(name)
    assert tool is not None
    return tool
