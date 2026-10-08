"""``docket setup mcp``: list, add and remove over the MCP client configuration."""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from docket.cli import app
from docket.core import mcp_tools as _mt

SUBJECT = "docket.cli._setup_mcp"

_runner = CliRunner()


def test_add_keeps_everything_after_the_separator_verbatim() -> None:
    result = _runner.invoke(
        app,
        ["setup", "mcp", "add", "search", "--env", "K=v", "--kind", "read", "--", "srv", "-y", "x"],
    )
    assert result.exit_code == 0, result.output
    (server,) = _mt.load_mcp_servers()
    assert (server.command, server.args, server.env, server.kind) == (
        "srv",
        ["-y", "x"],
        {"K": "v"},
        "read",
    )


def test_list_masks_env_values() -> None:
    _runner.invoke(app, ["setup", "mcp", "add", "s", "--env", "API=tok-secret", "--", "srv"])
    result = _runner.invoke(app, ["setup", "mcp", "list"])
    assert "API" in result.output and "tok-secret" not in result.output


@pytest.mark.parametrize(
    "args",
    [
        ["add", "s", "--kind", "bogus", "--", "cmd"],
        ["add", "s", "--env", "NOVALUE", "--", "cmd"],
        ["add", "not a valid name!", "--", "cmd"],
        ["add", "s"],
        ["remove", "ghost"],
    ],
)
def test_a_bad_call_is_refused_and_writes_nothing(args: list[str]) -> None:
    result = _runner.invoke(app, ["setup", "mcp", *args])
    assert result.exit_code != 0
    assert _mt.load_mcp_servers() == []


def test_remove_deletes_a_configured_server() -> None:
    _runner.invoke(app, ["setup", "mcp", "add", "weather", "--", "npx"])
    assert _runner.invoke(app, ["setup", "mcp", "remove", "weather"]).exit_code == 0
    assert _mt.load_mcp_servers() == []


def test_list_json_is_one_document_with_masked_env() -> None:
    _runner.invoke(app, ["setup", "mcp", "add", "s", "--env", "API=tok-secret", "--", "srv"])
    result = _runner.invoke(app, ["setup", "mcp", "list", "--json"])
    assert result.exit_code == 0
    servers = json.loads(result.stdout)
    assert [s["name"] for s in servers] == ["s"] and servers[0]["env"] == {"API": "****"}
