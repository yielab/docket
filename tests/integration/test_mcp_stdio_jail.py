"""A stdio MCP server starts in the turn's jail (`edges/adapters/mcp_client.py::_stdio_params`):
the turn's backend, roots and network mode, unless the operator declared the server
`isolate: false`; with isolation off the server's own argv is untouched."""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

import docket.config as _cfg
import docket.core.mcp_tools as _mt
from docket.cli import _mcp
from docket.core import audit as _audit
from docket.edges.adapters import mcp_client as _client
from docket.edges.adapters import system

SUBJECT = "docket.edges.adapters.mcp_client"

_needs_sdk = pytest.mark.skipif(
    not _client._sdk_available(), reason="the optional mcp SDK is absent"
)
_needs_bwrap = pytest.mark.skipif(
    not system.bwrap_available(),
    reason="bwrap not installed, or this host disallows unprivileged user namespaces",
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
        s = socket.socket()
        s.settimeout(2)
        try:
            s.connect(("1.1.1.1", 53))
        except OSError as ex:
            return f"network-error {ex.errno}"
        finally:
            s.close()
        return "connected"

    app.run("stdio")
    """
)


@pytest.fixture(autouse=True)
def _hermetic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_cfg, "MCP_SERVERS_FILE", tmp_path / "mcp-servers.json", raising=True)
    monkeypatch.setattr(_cfg, "AUDIT_LOG", tmp_path / "audit.log", raising=True)
    monkeypatch.delenv("DOCKET_SANDBOX_BACKEND", raising=False)


@pytest.fixture
def server(tmp_path: Path) -> _mt.McpServerConfig:
    script = tmp_path / "server.py"
    script.write_text(_SERVER)
    return _mt.McpServerConfig(name="probe", command=sys.executable, args=[str(script)])


@pytest.fixture
def root(tmp_path: Path) -> Path:
    path = tmp_path / "root"
    path.mkdir()
    return path


def _launch(root: Path, network: bool = True, sandbox: str = "auto") -> _mt.StdioLaunch:
    return _mt.StdioLaunch(
        cwd=str(root),
        sandbox=sandbox,  # type: ignore[arg-type]
        network=network,
        roots=(root,),
    )


def test_isolation_off_leaves_the_servers_own_argv_byte_identical(root: Path) -> None:
    config = _mt.McpServerConfig(name="s", command="npx", args=["-y", "srv", "--flag"])
    for launch in (None, _launch(root, sandbox="off"), _launch(root, network=False, sandbox="off")):
        params = _client._stdio_params(config, launch)
        assert (params.command, params.args) == ("npx", ["-y", "srv", "--flag"])


def test_an_isolate_false_server_is_never_wrapped(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DOCKET_SANDBOX_BACKEND", "bwrap")
    config = _mt.McpServerConfig(name="s", command="npx", args=["a"], isolate=False)
    params = _client._stdio_params(config, _launch(root))
    assert (params.command, params.args) == ("npx", ["a"])


def test_a_jailed_server_is_wrapped_by_bwrap_with_the_turns_roots_and_network(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DOCKET_SANDBOX_BACKEND", "bwrap")
    config = _mt.McpServerConfig(name="s", command="npx", args=["a", "b"])
    open_net = _client._stdio_params(config, _launch(root))
    cut_net = _client._stdio_params(config, _launch(root, network=False))
    assert open_net.command == "bwrap"
    assert open_net.args[-3:] == ["npx", "a", "b"]
    assert "--share-net" in open_net.args
    assert "--share-net" not in cut_net.args
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
    with pytest.raises(RuntimeError, match="no sandbox backend"):
        _client._stdio_params(config, _launch(root))


@_needs_sdk
@_needs_bwrap
def test_a_jailed_server_cannot_write_outside_the_roots_and_an_unjailed_one_can(
    tmp_path: Path, root: Path, server: _mt.McpServerConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DOCKET_SANDBOX_BACKEND", "bwrap")
    inside = root / "in.txt"
    outside = tmp_path / "out.txt"

    ok = _client.call_remote_tool(server, "write", {"path": str(inside)}, 30.0, _launch(root))
    assert ok.ok and inside.exists(), ok.error
    jailed = _client.call_remote_tool(server, "write", {"path": str(outside)}, 30.0, _launch(root))
    assert not (jailed.ok and outside.exists())

    free = server.model_copy(update={"isolate": False})
    unjailed = _client.call_remote_tool(free, "write", {"path": str(outside)}, 30.0, _launch(root))
    assert unjailed.ok and outside.exists(), unjailed.error


@_needs_sdk
@_needs_bwrap
def test_under_network_none_a_jailed_server_cannot_open_a_socket(
    root: Path, server: _mt.McpServerConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DOCKET_SANDBOX_BACKEND", "bwrap")
    out = _client.call_remote_tool(server, "dial", {}, 30.0, _launch(root, network=False))
    assert out.ok, out.error
    assert out.content.startswith("network-error"), out.content


@_needs_sdk
@_needs_bwrap
def test_listing_works_through_the_jail(
    root: Path, server: _mt.McpServerConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DOCKET_SANDBOX_BACKEND", "bwrap")
    listing = _client.list_remote_tools(server, 30.0, _launch(root))
    assert listing.ok, listing.error
    assert {t.name for t in listing.tools} == {"write", "dial"}


def test_no_isolate_flag_is_stored_audited_and_shown(capsys: pytest.CaptureFixture[str]) -> None:
    assert _mcp.run_mcp("servers", ["add", "free", "--no-isolate", "--", "srv", "x"]) == 0
    assert _mcp.run_mcp("servers", ["add", "caged", "--", "srv"]) == 0
    by_name = {s.name: s for s in _mt.load_mcp_servers()}
    assert by_name["free"].isolate is False
    assert by_name["caged"].isolate is True
    details = [e["detail"] for e in _audit.read_audit() if e["action"] == "mcp_servers.add"]
    assert any("name='free'" in d and "isolate=no" in d for d in details)
    assert any("name='caged'" in d and "isolate=yes" in d for d in details)
    capsys.readouterr()
    _mcp.run_mcp("servers", ["list"])
    listed = capsys.readouterr().out
    assert listed.count("isolate: no") == 1


def test_a_config_written_before_the_field_existed_loads_as_isolated() -> None:
    config = _mt.McpServerConfig.model_validate({"name": "old", "command": "srv"})
    assert config.isolate is True
