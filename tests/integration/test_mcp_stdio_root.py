"""A stdio MCP server spawned for a turn starts in that turn's resolved root
(`edges/adapters/mcp_client.py`, `core/mcp_tools.py`, `DocketDriver.run_turn`)."""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path
from typing import Any

import pytest
from tests.unit.core.test_mcp_tools import _final, _ScriptedBackend, _write_meta

import docket.core.mcp_tools as _mt
from docket.core.tools import ToolContext, ToolOutcome, ToolRegistry
from docket.edges.adapters import mcp_client as _client
from docket.edges.adapters.docket_runtime import DocketDriver, _load_mcp_tools

SUBJECT = "docket.edges.adapters.mcp_client"

_needs_sdk = pytest.mark.skipif(
    not _client._sdk_available(), reason="the optional mcp SDK is absent"
)

_SERVER = textwrap.dedent(
    """
    import os
    from mcp.server.mcpserver import MCPServer

    app = MCPServer("cwdprobe")

    @app.tool()
    def where() -> str:
        return os.getcwd()

    app.run("stdio")
    """
)


@_needs_sdk
def test_stdio_params_carry_the_given_directory(tmp_path: Path) -> None:
    config = _mt.McpServerConfig(name="s", command="stub")
    assert _client._stdio_params(config, cwd=str(tmp_path)).cwd == str(tmp_path)
    assert _client._stdio_params(config).cwd is None


@_needs_sdk
def test_a_real_stdio_server_starts_in_the_root_and_elsewhere_outside_a_turn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    script = tmp_path / "server.py"
    script.write_text(_SERVER)
    root = tmp_path / "root"
    root.mkdir()
    here = tmp_path / "elsewhere"
    here.mkdir()
    monkeypatch.chdir(here)
    config = _mt.McpServerConfig(name="probe", command=sys.executable, args=[str(script)])

    in_turn = _client.call_remote_tool(config, "where", {}, 30.0, cwd=str(root))
    outside = _client.call_remote_tool(config, "where", {}, 30.0)

    assert in_turn.ok, in_turn.error
    assert Path(in_turn.content).resolve() == root.resolve()
    assert outside.ok, outside.error
    assert Path(outside.content).resolve() == here.resolve()


def test_load_mcp_tools_hands_the_root_to_listing_and_calls() -> None:
    seen: dict[str, Any] = {}

    def _list(config: Any, timeout: float, cwd: str | None = None) -> _mt.McpListResult:
        seen["list"] = cwd
        return _mt.McpListResult(ok=True, tools=(_mt.McpRemoteTool("t", "d"),))

    def _call(config: Any, name: str, args: Any, timeout: float, cwd: str | None = None) -> Any:
        seen["call"] = cwd
        return ToolOutcome(True, content="ok")

    registry = ToolRegistry()
    _mt.load_mcp_tools(
        registry,
        servers=[_mt.McpServerConfig(name="s", command="stub")],
        list_tools=_list,
        call_tool=_call,
        cwd="/some/root",
    )
    tool = registry.get("mcp__s__t")
    assert tool is not None
    tool.handler({}, ToolContext(agent_id="a", session_key="k", roots=(Path("/x"),)))
    assert seen == {"list": "/some/root", "call": "/some/root"}


def test_the_driver_passes_its_resolved_root_down(tmp_path: Path) -> None:
    code = tmp_path / "code"
    code.mkdir()
    _write_meta("impl-1", role="implementer", codebase=str(code))
    got: dict[str, Any] = {}

    def _loader(registry: Any, role: str, project: str, cwd: str | None = None) -> list[Any]:
        got["cwd"] = cwd
        return []

    backend = _ScriptedBackend([_final("done")])
    DocketDriver(backend_factory=lambda model: backend, mcp_loader=_loader).run_turn(
        "impl-1", "agent:impl-1:default", "go", 30
    )
    assert got["cwd"] == str(code)


def test_the_default_loader_forwards_cwd_and_omits_it_when_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    def _spy(registry: Any, **kw: Any) -> list[Any]:
        calls.append(kw)
        return []

    monkeypatch.setattr(_mt, "load_mcp_tools", _spy)
    _load_mcp_tools(ToolRegistry(), "implementer", "", cwd="/r")
    _load_mcp_tools(ToolRegistry(), "implementer", "")
    assert calls[0]["cwd"] == "/r"
    assert "cwd" not in calls[1]
