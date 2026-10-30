"""One fake MCP command declared ``read`` and again ``send`` makes two servers whose tools carry
their server's kind, the registry offers both, and a role reaches the ``send`` one only by naming it.
The oracle is a real stdio server listed through the real client."""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest
from tests.support.roles import write_role_overlay

from docket.agent.tools import mcp_client as _client
from docket.agent.tools import mcp_tools as _mt
from docket.hops.application.builtin_tools import builtin_registry
from docket.kernel import mcp as _mcp
from docket.kernel.home import Home, use_home
from docket.teams.role_composer import registry_for_role

SUBJECT = "docket.agent.tools.mcp_tools"

pytestmark = pytest.mark.skipif(
    not _client._sdk_available(), reason="the optional mcp SDK is absent"
)

_SERVER = textwrap.dedent(
    """
    from mcp.server.mcpserver import MCPServer

    app = MCPServer("mailbox")

    @app.tool()
    def fetch_mail() -> str:
        return "one message"

    @app.tool()
    def send_mail(to: str) -> str:
        return f"sent to {to}"

    app.run("stdio")
    """
)


def _server(script: Path, name: str, kind: str) -> _mcp.McpServerConfig:
    return _mcp.McpServerConfig(
        name=name,
        command=sys.executable,
        args=[str(script)],
        kind=kind,  # type: ignore[arg-type]
    )


def test_one_command_declared_read_and_send_makes_two_servers_whose_tools_carry_their_kinds(
    tmp_path: Path,
) -> None:
    script = tmp_path / "mailbox.py"
    script.write_text(_SERVER)
    registry = builtin_registry()

    reports = _mt.load_mcp_tools(
        registry, servers=[_server(script, "inbox", "read"), _server(script, "outbox", "send")]
    )

    assert [(r.server, r.ok, r.kind) for r in reports] == [
        ("inbox", True, "read"),
        ("outbox", True, "send"),
    ]
    assert registry.get("mcp__inbox__fetch_mail").kind == "read"  # type: ignore[union-attr]
    assert registry.get("mcp__outbox__send_mail").kind == "send"  # type: ignore[union-attr]
    assert registry.get("mcp__outbox__fetch_mail").kind == "send"  # type: ignore[union-attr]


def test_a_role_reaches_the_send_tool_only_by_naming_it(tmp_path: Path) -> None:
    script = tmp_path / "mailbox.py"
    script.write_text(_SERVER)
    registry = builtin_registry()
    _mt.load_mcp_tools(registry, servers=[_server(script, "outbox", "send")])
    with use_home(Home(tmp_path / ".docket")):
        write_role_overlay("acme", "plain", [], extra="tools: [read]\n")
        write_role_overlay("acme", "actor", [], extra="tools: [read, mcp__outbox__send_mail]\n")

        plain = registry_for_role(registry, "plain", project="acme")
        actor = registry_for_role(registry, "actor", project="acme")

    assert plain.names() == ["read"]
    assert sorted(actor.names()) == ["mcp__outbox__send_mail", "read"]
