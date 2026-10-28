"""MCP tools reachable in a live turn (`agent/tools/mcp_tools.py`).

Covers `DocketDriver.run_turn` calling `load_mcp_tools` via its
`mcp_loader` seam before per-turn role narrowing, every MCP-adapted tool
registering its server's declared `kind` (defaulting to `write`) so
`registry_for_role` excludes it by capability from a write-denied role
unless the server declares itself `kind: read`, and a server's `tools`
allow-list narrowing which of its advertised tools get registered at
all. No real subprocess.
"""

from __future__ import annotations

from typing import Any

import pytest
from tests.support.pods import write_meta_overrides as _write_meta

from docket.agent.tools import mcp_tools as _mt
from docket.agent.tools.registry import ToolRegistry
from docket.hops.application.driver_support import _load_mcp_tools
from docket.kernel import mcp as _mcp
from docket.tasks.domain.task import DispatchError
from docket.teams import mcp_servers as _mcp_servers
from docket.teams.pod import member_id as _pod_member_id

SUBJECT = "docket.teams.mcp_servers"


# ── a pod's own mcpServers selection narrows the catalog _load_mcp_tools reads ──


class TestPodScopedMcpServerSelection:
    """`_load_mcp_tools(registry, role, project)` filters the catalog by *project*'s
    pod `mcpServers` setting before folding servers into a turn's registry."""

    def _capture_servers(self, monkeypatch: pytest.MonkeyPatch) -> dict[str, tuple[str, ...]]:
        captured: dict[str, tuple[str, ...]] = {}

        def _fake_load_mcp_tools(
            registry: ToolRegistry,
            *,
            servers: Any = None,
            list_tools: Any = None,
            call_tool: Any = None,
            role: str = "",
            project: str = "",
        ) -> list[Any]:
            captured["names"] = tuple(s.name for s in (servers or []))
            return []

        monkeypatch.setattr(_mt, "load_mcp_tools", _fake_load_mcp_tools)
        return captured

    def test_a_selected_name_narrows_the_catalog(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _mcp_servers.add_mcp_server(_mcp.McpServerConfig(name="a", command="stub"))
        _mcp_servers.add_mcp_server(_mcp.McpServerConfig(name="b", command="stub"))
        _write_meta(_pod_member_id("shop", "lead"), role="lead", pod="shop", mcpServers="a")
        captured = self._capture_servers(monkeypatch)

        _load_mcp_tools(ToolRegistry(), "implementer", "shop")

        assert captured["names"] == ("a",)

    def test_no_pod_setting_loads_every_server(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _mcp_servers.add_mcp_server(_mcp.McpServerConfig(name="a", command="stub"))
        _mcp_servers.add_mcp_server(_mcp.McpServerConfig(name="b", command="stub"))
        captured = self._capture_servers(monkeypatch)

        _load_mcp_tools(ToolRegistry(), "implementer", "")

        assert captured["names"] == ("a", "b")

    def test_a_stale_selection_refuses_the_dispatch_naming_it(self) -> None:
        _mcp_servers.add_mcp_server(_mcp.McpServerConfig(name="a", command="stub"))
        _write_meta(_pod_member_id("shop", "lead"), role="lead", pod="shop", mcpServers="zzz")

        with pytest.raises(DispatchError, match="zzz"):
            _load_mcp_tools(ToolRegistry(), "implementer", "shop")
