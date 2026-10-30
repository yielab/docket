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

from pathlib import Path
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


class TestScopeOrder:
    """A pod's own server is read before the operator's, and wins a name collision."""

    def test_the_pods_server_comes_first_and_shadows_the_operators_of_that_name(self) -> None:
        _mcp_servers.add_mcp_server(_mcp.McpServerConfig(name="s", command="operator-cmd"))
        _mcp_servers.add_mcp_server(_mcp.McpServerConfig(name="t", command="operator-t"))
        _mcp_servers.write_pod_mcp_servers(
            "shop", [_mcp.McpServerConfig(name="s", command="pod-cmd")]
        )

        servers = _mcp_servers.load_mcp_servers("shop")

        assert [(s.name, s.command) for s in servers] == [("s", "pod-cmd"), ("t", "operator-t")]
        assert [s.command for s in _mcp_servers.load_mcp_servers("other")] == [
            "operator-cmd",
            "operator-t",
        ]


class TestServerDocument:
    """A ``kind: mcp-server`` document carries the declared kind (``access``) and the lifetime."""

    def test_access_send_and_lifetime_hop_load_and_round_trip(self, tmp_path: Path) -> None:
        path = tmp_path / "browser.yaml"
        path.write_text(
            "kind: mcp-server\nname: browser\ncommand: browse\naccess: send\nlifetime: hop\n"
        )

        config = _mcp_servers.load_mcp_server_document(path)

        assert (config.kind, config.lifetime) == ("send", "hop")
        again = _mcp_servers.McpServerDocument.model_validate(
            _mcp_servers.mcp_server_document(config)
        ).to_config()
        assert again == config

    def test_a_document_without_them_is_a_write_server_per_call(self, tmp_path: Path) -> None:
        path = tmp_path / "plain.yaml"
        path.write_text("kind: mcp-server\nname: plain\ncommand: run\n")

        config = _mcp_servers.load_mcp_server_document(path)

        assert (config.kind, config.lifetime) == ("write", "call")
        assert "lifetime" not in _mcp_servers.mcp_server_document(config)

    def test_an_access_outside_the_three_kinds_is_refused(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.yaml"
        path.write_text("kind: mcp-server\nname: bad\ncommand: run\naccess: post\n")

        with pytest.raises(_mcp_servers.McpServerDocError, match="access"):
            _mcp_servers.load_mcp_server_document(path)
