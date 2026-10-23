"""A stdio MCP server starts in the turn's jail (`edges/adapters/mcp_client.py::_stdio_params`):
the turn's backend, roots and network mode, with no per-server opt-out; with isolation off the
server's own argv is untouched."""

from __future__ import annotations

import dataclasses
import sys
import textwrap
from collections.abc import Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner

import docket.agent.tools.mcp_tools as _mt
from docket.agent.tools import mcp_client as _client
from docket.governance import audit as _audit
from docket.interfaces.cli.app import app
from docket.kernel.errors import Unavailable
from docket.kernel.home import current_home, use_home
from docket.sandbox import landlock

SUBJECT = "docket.agent.tools.mcp_client"

# The launch argv is built as the SDK's StdioServerParameters: the optional [mcp] extra.
pytest.importorskip("mcp")

_needs_sdk = pytest.mark.skipif(
    not _client._sdk_available(), reason="the optional mcp SDK is absent"
)
_needs_landlock = pytest.mark.skipif(
    not landlock.landlock_available(), reason="landlock is not available on this host"
)

_SERVER = textwrap.dedent(
    """
    import socket
    from mcp.server.mcpserver import MCPServer

    app = MCPServer("jailprobe")

    @app.tool()
    def write(path: str) -> str:
        with open(path, "w") as fh:
            fh.write("x")
        return "wrote"

    @app.tool()
    def dial() -> str:
        try:
            s = socket.socket()
            s.settimeout(2)
            s.connect(("1.1.1.1", 53))
        except OSError as ex:
            return f"network-error {ex.errno}"
        return "connected"

    app.run("stdio")
    """
)


@pytest.fixture(autouse=True)
def _hermetic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    with use_home(
        dataclasses.replace(current_home(), mcp_servers_file_override=tmp_path / "mcp-servers.json")
    ):
        monkeypatch.delenv("DOCKET_SANDBOX_BACKEND", raising=False)
        yield


@pytest.fixture
def server(root: Path) -> _mt.McpServerConfig:
    script = root / "server.py"
    script.write_text(_SERVER)
    return _mt.McpServerConfig(name="probe", command=sys.executable, args=[str(script)])


@pytest.fixture
def root(tmp_path: Path) -> Path:
    path = tmp_path / "root"
    path.mkdir()
    return path


def _launch(
    root: Path, network: bool = True, sandbox: str = "auto", runtime: bool = False
) -> _mt.StdioLaunch:
    extra = (Path(sys.prefix), Path(sys.base_prefix)) if runtime else ()
    return _mt.StdioLaunch(
        cwd=str(root),
        sandbox=sandbox,  # type: ignore[arg-type]
        network=network,
        roots=(root, *extra),
    )


def test_isolation_off_leaves_the_servers_own_argv_byte_identical(root: Path) -> None:
    config = _mt.McpServerConfig(name="s", command="npx", args=["-y", "srv", "--flag"])
    for launch in (None, _launch(root, sandbox="off"), _launch(root, network=False, sandbox="off")):
        params = _client._stdio_params(config, launch)
        assert (params.command, params.args) == ("npx", ["-y", "srv", "--flag"])


def test_a_jailed_server_is_wrapped_by_landlock_with_the_turns_roots_and_network(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DOCKET_SANDBOX_BACKEND", "landlock")
    config = _mt.McpServerConfig(name="s", command="npx", args=["a", "b"])
    open_net = _client._stdio_params(config, _launch(root))
    cut_net = _client._stdio_params(config, _launch(root, network=False))
    assert open_net.command == sys.executable
    assert open_net.args[-3:] == ["npx", "a", "b"]
    assert open_net.args[open_net.args.index("--net") + 1] == "open"
    assert cut_net.args[cut_net.args.index("--net") + 1] == "none"
    assert str(root.resolve()) in open_net.args


def test_a_docker_wrapped_server_keeps_stdin_open_and_honours_network(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DOCKET_SANDBOX_BACKEND", "docker")
    config = _mt.McpServerConfig(name="s", command="srv", args=["a"], env={"K": "V"})
    params = _client._stdio_params(config, _launch(root, network=False))
    assert params.command == "docker"
    assert "-i" in params.args
    assert params.args[params.args.index("--network") + 1] == "none"
    assert "K=V" in params.args
    assert params.args[-2:] == ["srv", "a"]


def test_isolation_on_with_no_backend_refuses_rather_than_starting_unjailed(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DOCKET_SANDBOX_BACKEND", "none")
    config = _mt.McpServerConfig(name="s", command="srv")
    with pytest.raises(Unavailable, match="no sandbox backend"):
        _client._stdio_params(config, _launch(root))


@_needs_sdk
@_needs_landlock
def test_a_jailed_server_cannot_write_outside_the_roots(
    tmp_path: Path, root: Path, server: _mt.McpServerConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DOCKET_SANDBOX_BACKEND", "landlock")
    inside = root / "in.txt"
    outside = Path(sys.prefix).parent / f".jail-probe-{tmp_path.name}"

    ok = _client.call_remote_tool(
        server, "write", {"path": str(inside)}, 30.0, _launch(root, runtime=True)
    )
    assert ok.ok and inside.exists(), ok.error
    try:
        jailed = _client.call_remote_tool(
            server, "write", {"path": str(outside)}, 30.0, _launch(root, runtime=True)
        )
        assert not (jailed.ok and outside.exists())
    finally:
        outside.unlink(missing_ok=True)


@_needs_sdk
@_needs_landlock
def test_under_network_none_a_jailed_server_cannot_open_a_socket(
    root: Path, server: _mt.McpServerConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DOCKET_SANDBOX_BACKEND", "landlock")
    out = _client.call_remote_tool(
        server, "dial", {}, 30.0, _launch(root, network=False, runtime=True)
    )
    assert out.ok, out.error
    assert out.content.startswith("network-error"), out.content


@_needs_sdk
@_needs_landlock
def test_listing_works_through_the_jail(
    root: Path, server: _mt.McpServerConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DOCKET_SANDBOX_BACKEND", "landlock")
    listing = _client.list_remote_tools(server, 30.0, _launch(root, runtime=True))
    assert listing.ok, listing.error
    assert {t.name for t in listing.tools} == {"write", "dial"}


def test_the_no_isolate_flag_and_field_are_gone() -> None:
    runner = CliRunner()
    refused = runner.invoke(app, ["setup", "mcp", "add", "free", "--no-isolate", "--", "srv", "x"])
    assert refused.exit_code == 2
    assert "isolate" not in _mt.McpServerConfig.model_fields
    assert runner.invoke(app, ["setup", "mcp", "add", "caged", "--", "srv"]).exit_code == 0
    details = [e["detail"] for e in _audit.read_audit() if e["action"] == "mcp_servers.add"]
    assert any("name='caged'" in d and "isolate" not in d for d in details)
    assert "host" not in runner.invoke(app, ["setup", "mcp", "list"]).output
