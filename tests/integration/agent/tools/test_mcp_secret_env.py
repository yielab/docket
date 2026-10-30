"""An MCP server's ``env`` value ``secret:<name>`` is resolved from the secret store when a turn
loads its servers. The oracle is a fake stdio server that echoes one environment variable, the
files docket wrote, and the trace and audit log."""

from __future__ import annotations

import json
import sys
import textwrap
from pathlib import Path

import pytest
from tests.support.llm import RecordingScriptedBackend as _ScriptedBackend
from tests.support.llm import final as _final
from tests.support.pods import write_meta_overrides as _write_meta
from tests.support.trace import audit_entries, trace_events
from tests.support.turns import run_turn, tool_replies, trace_text

from docket.agent.ports import ChatResponse, TokenUsage, ToolCall, assistant
from docket.agent.tools import mcp_client as _client
from docket.governance import audit as _audit
from docket.governance import secrets as _secrets
from docket.kernel import mcp as _mcp
from docket.kernel.home import current_home
from docket.teams import fleet as _fleet
from docket.teams import mcp_servers as _mcp_servers

SUBJECT = "docket.hops.application.driver_support"

pytestmark = pytest.mark.skipif(
    not _client._sdk_available(), reason="the optional mcp SDK is absent"
)

_VALUE = "crm-live-0123456789abcdef"

_SERVER = textwrap.dedent(
    """
    import os
    from mcp.server.mcpserver import MCPServer

    app = MCPServer("echo")

    @app.tool()
    def read_env(name: str) -> str:
        return "seen=" + os.environ.get(name, "")

    app.run("stdio")
    """
)


def _server(script: Path, name: str, env: dict[str, str]) -> _mcp.McpServerConfig:
    return _mcp.McpServerConfig(
        name=name, command=sys.executable, args=[str(script)], kind="read", timeout=30.0, env=env
    )


def _call(server: str) -> ChatResponse:
    call = ToolCall(
        id=f"c-{server}", name=f"mcp__{server}__read_env", arguments='{"name": "API_TOKEN"}'
    )
    return ChatResponse(
        ok=True,
        message=assistant("", tool_calls=[call]),
        finish_reason="tool_calls",
        usage=TokenUsage(5, 5),
    )


@pytest.fixture
def world(tmp_path: Path) -> Path:
    script = tmp_path / "echo_server.py"
    script.write_text(_SERVER)
    _fleet.disable_sandbox_isolation()
    code = tmp_path / "code"
    code.mkdir()
    _write_meta("impl-1", role="implementer", codebase=str(code))
    _secrets.save_secrets({"crm": _VALUE})
    return script


class TestAStoredSecretReachesTheServer:
    def test_the_server_sees_the_value_and_neither_the_config_nor_the_trace_holds_it(
        self, world: Path
    ) -> None:
        _mcp_servers.add_mcp_server(_server(world, "api", {"API_TOKEN": "secret:crm"}))
        backend = _ScriptedBackend([_call("api"), _final("done")])

        run_turn(backend)

        assert _VALUE in tool_replies(backend)[0]
        stored = json.loads(current_home().mcp_servers_file.read_text())
        assert stored["servers"][0]["env"] == {"API_TOKEN": "secret:crm"}
        assert _VALUE not in current_home().mcp_servers_file.read_text()
        results = [e for e in trace_events("impl-1") if e["event_type"] == "tool_result"]
        assert [(e["payload"]["tool"], e["payload"]["ok"]) for e in results] == [
            ("mcp__api__read_env", True)
        ]
        assert _VALUE not in _secrets.redact(tool_replies(backend)[0])
        assert _VALUE not in trace_text()
        assert _VALUE not in str(_audit.read_audit())


class TestAnUnknownSecret:
    def test_that_server_is_unavailable_naming_the_variable_and_others_still_load(
        self, world: Path
    ) -> None:
        _mcp_servers.add_mcp_server(_server(world, "api", {"API_TOKEN": "secret:ghost"}))
        _mcp_servers.add_mcp_server(_server(world, "good", {"API_TOKEN": "literal-token-value"}))
        backend = _ScriptedBackend([_call("good"), _final("done")])

        run_turn(backend)

        assert "seen=literal-token-value" in tool_replies(backend)[0]
        down = audit_entries("mcp_client.unavailable")
        assert len(down) == 1
        assert "api" in down[0]["detail"] and "API_TOKEN" in down[0]["detail"]
        assert "ghost" in down[0]["detail"]
