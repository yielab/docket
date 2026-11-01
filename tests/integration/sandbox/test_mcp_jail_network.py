"""A jailed stdio MCP server shares the turn's network: under `none` it reaches no TCP address,
loopback included, while an open network lets the same tool connect to a loopback listener."""

from __future__ import annotations

import contextlib
import socket
import sys
import textwrap
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from docket.agent.tools import mcp_client as _client
from docket.agent.tools import mcp_types as _mcp_types
from docket.kernel import mcp as _mcp
from docket.sandbox import landlock

SUBJECT = "docket.agent.tools.mcp_client"

_needs_landlock = pytest.mark.skipif(
    not landlock.landlock_available(), reason="landlock is not available on this host"
)
_needs_sdk = pytest.mark.skipif(
    not _client._sdk_available(), reason="the optional mcp SDK is absent"
)

_SERVER = textwrap.dedent(
    """
    import errno
    import socket
    from mcp.server.mcpserver import MCPServer

    app = MCPServer("netprobe")

    @app.tool()
    def reach(host: str, port: int) -> str:
        try:
            with socket.create_connection((host, port), timeout=3) as s:
                s.sendall(b"hello")
        except OSError as e:
            return "ERR " + errno.errorcode.get(e.errno or 0, str(e.errno))
        return "CONNECTED"

    app.run("stdio")
    """
)


@contextmanager
def _listener() -> Iterator[tuple[int, list[bytes]]]:
    """A loopback listener on a free port; yields the port and every byte string it received."""
    received: list[bytes] = []
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(5)
    srv.settimeout(0.2)
    stop = threading.Event()

    def serve() -> None:
        while not stop.is_set():
            try:
                conn, _ = srv.accept()
            except OSError:
                continue
            with conn:
                conn.settimeout(2)
                with contextlib.suppress(OSError):
                    received.append(conn.recv(64))

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    try:
        yield srv.getsockname()[1], received
    finally:
        stop.set()
        thread.join(timeout=5)
        srv.close()


def _reach(tmp_path: Path, port: int, *, network: bool) -> str:
    script = tmp_path / "server.py"
    script.write_text(_SERVER)
    config = _mcp.McpServerConfig(name="probe", command=sys.executable, args=[str(script)])
    launch = _mcp_types.StdioLaunch(
        cwd=str(tmp_path), sandbox="auto", network=network, roots=(tmp_path,)
    )
    outcome = _client.call_remote_tool(
        config, "reach", {"host": "127.0.0.1", "port": port}, 30.0, launch
    )
    assert outcome.ok, outcome.error
    return outcome.content


@_needs_landlock
@_needs_sdk
class TestAJailedStdioServerAndTheLoopback:
    def test_under_network_none_the_tool_gets_eperm_and_the_listener_hears_nothing(
        self, tmp_path: Path
    ) -> None:
        with _listener() as (port, received):
            content = _reach(tmp_path, port, network=False)
        assert content == "ERR EPERM"
        assert received == []

    def test_with_the_network_open_the_same_tool_reaches_the_listener(self, tmp_path: Path) -> None:
        with _listener() as (port, received):
            content = _reach(tmp_path, port, network=True)
        assert content == "CONNECTED"
        assert received == [b"hello"]
