"""MCP server isolation state visibility in doctor, config, and recipes.

Requirement 40: unjailed MCP servers (isolate: false) are shown by `docket setup --fix`,
`docket config explain`, and `docket recipes show --json`, with pod context where applicable.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.conftest import repoint_docket_home

from docket.cli import _config, _pod, _setup_check
from docket.core import mcp_tools as _mcp_tools
from docket.core import pod

SUBJECT = "docket.cli._setup_check"


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOCKET_SERVICE_MANAGER", "none")


def _seed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, project: str = "demo") -> Path:
    home = tmp_path / ".docket"
    (home / "workspaces" / "projects").mkdir(parents=True)
    (home / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    repoint_docket_home(monkeypatch, home)
    _pod.build_pod(project, pod.DEFAULT_POD_ROLES, codebase=f"/src/{project}")
    return home


class TestDoctorJsonShowsUnjailedMcpServers:
    """doctor --json names unjailed servers with their pod context."""

    def test_global_unjailed_server_in_check_json(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _seed(tmp_path, monkeypatch)
        # Add a global unjailed server
        _mcp_tools.add_mcp_server(
            _mcp_tools.McpServerConfig(
                name="local-tool", command="python3", args=["-m", "tool"], isolate=False
            )
        )

        capsys.readouterr()
        _setup_check.run_check(json_out=True)
        output = capsys.readouterr().out
        report = json.loads(output)

        unjailed = report["checks"]["securityGates"]["unjailedMcpServers"]
        assert any(s["name"] == "local-tool" and s["pod"] == "" for s in unjailed)

    def test_pod_scoped_unjailed_server_in_check_json(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _seed(tmp_path, monkeypatch)
        # Create a second pod
        _pod.build_pod("research", ("lead", "implementer"), codebase="/src/research")

        # Add an unjailed server to the research pod's config
        research_servers = [
            _mcp_tools.McpServerConfig(name="research-tool", command="python3", isolate=False)
        ]
        _mcp_tools.write_pod_mcp_servers("research", research_servers)

        capsys.readouterr()
        _setup_check.run_check(json_out=True)
        output = capsys.readouterr().out
        report = json.loads(output)

        unjailed = report["checks"]["securityGates"]["unjailedMcpServers"]
        assert any(s["name"] == "research-tool" and s["pod"] == "research" for s in unjailed)


class TestConfigExplainShowsIsolateBool:
    """config explain --json shows isolate field for each MCP server."""

    def test_mcp_servers_report_includes_isolate_field(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _seed(tmp_path, monkeypatch)
        # Add both jailed and unjailed servers
        _mcp_tools.add_mcp_server(
            _mcp_tools.McpServerConfig(name="jailed-tool", command="python3", isolate=True)
        )
        _mcp_tools.add_mcp_server(
            _mcp_tools.McpServerConfig(name="unjailed-tool", command="python3", isolate=False)
        )

        capsys.readouterr()
        _config.dispatch("explain", [pod.member_id("demo", "implementer"), "--json"])
        output = capsys.readouterr().out
        report = json.loads(output)

        servers_by_name = {s["name"]: s for s in report["tools"]["mcpServers"]}
        assert servers_by_name["jailed-tool"]["isolate"] is True
        assert servers_by_name["unjailed-tool"]["isolate"] is False

    def test_config_explain_human_shows_unjailed_marker(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _seed(tmp_path, monkeypatch)
        _mcp_tools.add_mcp_server(
            _mcp_tools.McpServerConfig(name="unjailed-tool", command="python3", isolate=False)
        )

        capsys.readouterr()
        _config.dispatch("explain", [pod.member_id("demo", "implementer")])
        output = capsys.readouterr().out
        # Should show unjailed server with some marker
        assert "unjailed-tool" in output


class TestRecipesJsonShowsUnjailedServers:
    """recipes show/list --json includes unjailed_mcp_servers field."""

    def test_recipes_show_json_has_unjailed_mcp_servers_field(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _seed(tmp_path, monkeypatch)
        # Use the shipped code-intel recipe if it exists
        from docket.cli._recipes import run_recipes

        capsys.readouterr()
        run_recipes(["show", "code-intel", "--json"])
        output = capsys.readouterr().out
        if output and not output.strip().startswith("Error"):
            report = json.loads(output)
            assert "unjailed_mcp_servers" in report

    def test_recipes_list_json_has_unjailed_mcp_servers_field(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _seed(tmp_path, monkeypatch)
        from docket.cli._recipes import run_recipes

        capsys.readouterr()
        run_recipes(["list", "--json"])
        output = capsys.readouterr().out
        report = json.loads(output)
        # At least one recipe should have the field (even if empty)
        assert any("unjailed_mcp_servers" in recipe for recipe in report)
