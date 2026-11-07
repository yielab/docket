"""The three powers a pod holds, and the warning when it holds all three."""

from __future__ import annotations

from pathlib import Path

from docket.governance import secrets as _secrets
from docket.kernel.home import Home, current_home, use_home
from docket.kernel.mcp import McpServerConfig
from docket.platform import store as _store
from docket.teams import mcp_servers as _mcp_servers
from docket.teams import posture as _posture

SUBJECT = "docket.teams.posture"


def _pod(*, kind: str = "codebase", **meta: object) -> None:
    """Pod ``p`` of workspace *kind* on the current home, with *meta* on its Lead."""
    path = current_home().meta_path("p-lead")
    path.parent.mkdir(parents=True, exist_ok=True)
    _store.write_json(path, {"kind": "project", "scope": "project", "workspaceKind": kind, **meta})


def _server(name: str, kind: str, env: dict[str, str] | None = None) -> McpServerConfig:
    return McpServerConfig(name=name, command="true", kind=kind, env=env or {})


def test_a_bare_codebase_pod_with_no_network_holds_only_private_data(tmp_path: Path) -> None:
    with use_home(Home(tmp_path / ".docket")):
        _pod(network="none")
        held = _posture.powers("p")
    assert held.untrusted_input == ()
    assert held.private_data == ("the codebase",)
    assert held.outward == ()
    assert held.warning() == ""


def test_a_web_read_a_secret_and_a_send_server_hold_all_three(tmp_path: Path) -> None:
    with use_home(Home(tmp_path / ".docket")):
        _pod(network="none", fetchDomains="docs.python.org")
        _mcp_servers.write_pod_mcp_servers(
            "p", [_server("mail", "send", {"MAIL_TOKEN": "secret:mail"})]
        )
        held = _posture.powers("p")
    assert held.untrusted_input == ("web read of docs.python.org",)
    assert any("MAIL_TOKEN" in line for line in held.private_data)
    assert held.outward == ("MCP server mail (send)",)
    assert held.holds_all
    warning = held.warning()
    assert warning.startswith("holds untrusted input, private data and an outward action")
    assert "MCP server mail (send)" in warning


def test_dropping_the_send_server_clears_the_warning(tmp_path: Path) -> None:
    with use_home(Home(tmp_path / ".docket")):
        _pod(network="none", fetchDomains="docs.python.org")
        _mcp_servers.write_pod_mcp_servers("p", [_server("mail", "write", {"T": "secret:mail"})])
        held = _posture.powers("p")
    assert held.outward == ()
    assert held.warning() == ""


def test_a_read_server_is_untrusted_input_and_a_stored_secret_name_is_private_data(
    tmp_path: Path,
) -> None:
    with use_home(Home(tmp_path / ".docket")):
        _pod(kind="workdir", network="none")
        _secrets.save_secrets({"API_KEY": "x"})
        _mcp_servers.write_pod_mcp_servers("p", [_server("feed", "read", {"API_KEY": "literal"})])
        held = _posture.powers("p")
    assert held.untrusted_input == ("MCP server feed (read)",)
    assert held.private_data == ("secret API_KEY injected into MCP server feed",)
    assert held.outward == ("a folder outside the repository (workDir)",)
    assert held.holds_all


def test_an_unselected_server_grants_nothing(tmp_path: Path) -> None:
    with use_home(Home(tmp_path / ".docket")):
        _pod(network="none", mcpServers="notes")
        _mcp_servers.write_pod_mcp_servers(
            "p", [_server("mail", "send"), _server("notes", "write")]
        )
        held = _posture.powers("p")
    assert held.outward == ()
