"""An MCP server declared ``lifetime: hop`` keeps one stdio session for the hop's calls; a ``call``
server (the default) spawns a subprocess per call. The oracle is a fake stdio server that counts the
calls it has answered, and the trace's ``process_*`` events."""

from __future__ import annotations

import os
import signal
import sys
import textwrap
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from tests.support.llm import RecordingScriptedBackend as _ScriptedBackend
from tests.support.llm import final as _final
from tests.support.pods import write_meta_overrides as _write_meta
from tests.support.trace import trace_events

from docket.agent.ports import ChatResponse, TokenUsage, ToolCall, assistant
from docket.agent.tools import mcp_client as _client
from docket.agent.tools import mcp_tools as _mt
from docket.agent.tools.registry import ToolContext, ToolRegistry, dispatch_tool
from docket.hops.application.driver import DocketDriver
from docket.kernel import mcp as _mcp
from docket.teams import fleet as _fleet
from docket.teams import mcp_servers as _mcp_servers

SUBJECT = "docket.agent.tools.mcp_client"

pytestmark = pytest.mark.skipif(
    not _client._sdk_available(), reason="the optional mcp SDK is absent"
)

_SERVER = textwrap.dedent(
    """
    import asyncio
    import os
    from mcp.server.mcpserver import MCPServer

    app = MCPServer("counter")
    calls = 0

    @app.tool()
    def count() -> str:
        global calls
        calls += 1
        return f"n={calls}"

    @app.tool()
    def pid() -> str:
        return str(os.getpid())

    @app.tool()
    def die() -> str:
        os._exit(3)

    @app.tool()
    async def slow() -> str:
        await asyncio.sleep(30)
        return "late"

    app.run("stdio")
    """
)


@pytest.fixture
def server_script(tmp_path: Path) -> Path:
    script = tmp_path / "counter_server.py"
    script.write_text(_SERVER)
    return script


def _config(script: Path, lifetime: str, **kw: Any) -> _mcp.McpServerConfig:
    return _mcp.McpServerConfig(
        name="counter",
        command=sys.executable,
        args=[str(script)],
        kind="read",
        timeout=kw.pop("timeout", 30.0),
        lifetime=lifetime,  # type: ignore[arg-type]
        **kw,
    )


class _Hop:
    """One hop: a registry loaded from *config* over the real transport, and a context whose
    ``on_process`` events are recorded."""

    def __init__(self, config: _mcp.McpServerConfig, root: Path) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []
        self.ctx = ToolContext(
            agent_id="a",
            role="implementer",
            project="p",
            roots=(root,),
            on_process=lambda kind, data: self.events.append((kind, data)),
        )
        self.registry = ToolRegistry()
        reports = _mt.load_mcp_tools(self.registry, servers=[config], role="implementer")
        assert reports[0].ok, reports[0].error

    def call(self, tool: str) -> Any:
        return dispatch_tool(
            ToolCall(id=f"c-{tool}", name=f"mcp__counter__{tool}", arguments="{}"),
            self.ctx,
            self.registry,
        )

    def end(self) -> None:
        self.ctx.mcp_sessions.close_all(self.ctx.on_process, reason="turn_end")


@pytest.fixture
def hops(tmp_path: Path) -> Iterator[list[_Hop]]:
    opened: list[_Hop] = []
    yield opened
    for hop in opened:
        hop.end()


def _hop(hops: list[_Hop], config: _mcp.McpServerConfig, root: Path) -> _Hop:
    hop = _Hop(config, root)
    hops.append(hop)
    return hop


class TestCallIsTheDefault:
    def test_a_config_without_the_field_is_call(self, server_script: Path) -> None:
        assert _mcp.McpServerConfig(name="x", command="y").lifetime == "call"

    def test_each_call_of_a_call_server_sees_a_fresh_process(
        self, server_script: Path, hops: list[_Hop], tmp_path: Path
    ) -> None:
        hop = _hop(hops, _config(server_script, "call"), tmp_path)

        first, second = hop.call("count"), hop.call("count")

        assert (first.content, second.content) == ("n=1", "n=1")
        assert hop.events == []


class TestHopKeepsOneSession:
    def test_calls_of_a_hop_share_the_server_and_the_next_hop_starts_afresh(
        self, server_script: Path, hops: list[_Hop], tmp_path: Path
    ) -> None:
        config = _config(server_script, "hop")
        hop = _hop(hops, config, tmp_path)

        outputs = [hop.call("count").content for _ in range(2)]
        hop.end()
        next_hop = _hop(hops, config, tmp_path)

        assert outputs == ["n=1", "n=2"]
        assert next_hop.call("count").content == "n=1"

    def test_the_session_is_closed_once_and_traced_like_a_process(
        self, server_script: Path, hops: list[_Hop], tmp_path: Path
    ) -> None:
        hop = _hop(hops, _config(server_script, "hop"), tmp_path)
        hop.call("count")
        hop.call("count")

        hop.end()
        hop.end()

        assert [k for k, _ in hop.events] == ["started", "exited"]
        assert hop.events[0][1] == {"tool": "mcp", "server": "counter"}
        assert hop.events[1][1] == {"tool": "mcp", "server": "counter", "reason": "turn_end"}

    def test_a_hop_that_never_calls_the_server_opens_nothing(
        self, server_script: Path, hops: list[_Hop], tmp_path: Path
    ) -> None:
        hop = _hop(hops, _config(server_script, "hop"), tmp_path)

        hop.end()

        assert hop.events == []


class TestAServerThatDies:
    def test_a_server_killed_between_calls_is_restarted_and_the_call_says_so(
        self, server_script: Path, hops: list[_Hop], tmp_path: Path
    ) -> None:
        hop = _hop(hops, _config(server_script, "hop"), tmp_path)
        assert hop.call("count").content == "n=1"
        os.kill(int(hop.call("pid").content), signal.SIGKILL)
        time.sleep(0.5)

        after = hop.call("count")

        assert after.ok, after.error
        assert "restarted" in after.content and "state" in after.content
        assert after.content.endswith("n=1")
        assert hop.call("count").content == "n=2"
        assert [k for k, _ in hop.events] == ["started", "exited", "started"]
        assert hop.events[1][1]["reason"] == "died"

    def test_a_server_that_dies_during_a_call_fails_that_call_and_the_next_restarts(
        self, server_script: Path, hops: list[_Hop], tmp_path: Path
    ) -> None:
        hop = _hop(hops, _config(server_script, "hop"), tmp_path)
        hop.call("count")

        dying = hop.call("die")
        after = hop.call("count")

        assert not dying.ok and "state is gone" in (dying.error or "")
        assert after.ok and "restarted" in after.content and after.content.endswith("n=1")
        assert [k for k, _ in hop.events] == ["started", "exited", "started"]
        assert hop.events[1][1]["reason"] == "died"

    def test_a_call_that_times_out_ends_the_session(
        self, server_script: Path, hops: list[_Hop], tmp_path: Path
    ) -> None:
        hop = _hop(hops, _config(server_script, "hop", timeout=4.0), tmp_path)

        slow = hop.call("slow")

        assert not slow.ok and "timed out" in (slow.error or "")
        assert [k for k, _ in hop.events] == ["started", "exited"]
        assert hop.events[1][1]["reason"] == "timeout"


class TestAServerThatCannotStart:
    def test_a_hop_server_that_will_not_start_fails_the_call_like_a_call_server(
        self, hops: list[_Hop], tmp_path: Path
    ) -> None:
        config = _mcp.McpServerConfig(
            name="counter", command="/no/such/binary", lifetime="hop", kind="read", timeout=5.0
        )
        listing = _mt.McpListResult(ok=True, tools=(_mt.McpRemoteTool("count"),))
        registry = ToolRegistry()
        _mt.load_mcp_tools(
            registry, servers=[config], list_tools=lambda c, t, launch=None: listing, role="r"
        )
        ctx = ToolContext(agent_id="a", role="implementer", project="p", roots=(tmp_path,))

        res = dispatch_tool(
            ToolCall(id="c1", name="mcp__counter__count", arguments="{}"), ctx, registry
        )

        assert not res.ok and "counter" in (res.error or "")
        ctx.mcp_sessions.close_all(None, reason="turn_end")


def _call(call_id: str, tool: str) -> ChatResponse:
    return ChatResponse(
        ok=True,
        message=assistant(
            "", tool_calls=[ToolCall(id=call_id, name=f"mcp__counter__{tool}", arguments="{}")]
        ),
        finish_reason="tool_calls",
        usage=TokenUsage(5, 5),
    )


class TestThroughTheDriver:
    def test_a_turn_calls_the_server_twice_over_one_session_and_traces_one_stop(
        self, server_script: Path, tmp_path: Path
    ) -> None:
        _fleet.disable_sandbox_isolation()
        code = tmp_path / "code"
        code.mkdir()
        _write_meta("impl-1", role="implementer", codebase=str(code))
        _mcp_servers.add_mcp_server(_config(server_script, "hop"))
        backend = _ScriptedBackend([_call("c1", "count"), _call("c2", "count"), _final("done")])

        res = DocketDriver(backend_factory=lambda model: backend).run_turn(
            "impl-1", "agent:impl-1:default", "go", 60
        )

        assert res.ok, res.error
        replies = [m.content for call in backend.calls[1:] for m in call if m.role == "tool"]
        assert "n=1" in replies[0] and "n=2" in replies[-1]
        marks = [e for e in trace_events("impl-1") if e["event_type"].startswith("process_")]
        assert [e["event_type"] for e in marks] == ["process_started", "process_exited"]
        assert marks[1]["payload"] == {"tool": "mcp", "server": "counter", "reason": "turn_end"}
