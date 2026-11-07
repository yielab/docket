"""``docket pod check --posture``: the three powers a pod holds, and the warning at all three."""

from __future__ import annotations

from pathlib import Path

from tests.support.cli import invoke_pod
from tests.support.pods import build_pod
from tests.support.pods import seed_empty_home as _seed

from docket.kernel.mcp import McpServerConfig
from docket.teams import fleet as _fleet
from docket.teams import mcp_servers as _mcp_servers
from docket.teams import pod

SUBJECT = "docket.interfaces.cli.commands.pod_config"

_WARNING = "holds untrusted input, private data and an outward action together"


def _research_pod(*, send: bool) -> None:
    build_pod("proj", pod.DEFAULT_POD_ROLES, codebase="/src/proj")
    _fleet.meta_set("proj-lead", "network", "none")
    assert invoke_pod(["set", "fetchDomains", "docs.python.org", "--pod", "proj"]).exit_code == 0
    kind = "send" if send else "write"
    _mcp_servers.write_pod_mcp_servers(
        "proj",
        [McpServerConfig(name="mail", command="true", kind=kind, env={"TOKEN": "secret:mail"})],
    )


def test_all_three_powers_print_and_warn(tmp_path: Path) -> None:
    with _seed(tmp_path):
        _research_pod(send=True)
        result = invoke_pod(["check", "--posture", "--pod", "proj"])
    assert result.exit_code == 0, result.output
    assert "Untrusted input: web read of docs.python.org" in result.output
    assert "Private data:" in result.output
    assert "Outward action:  MCP server mail (send)" in result.output
    assert _WARNING in result.output


def test_two_powers_print_without_the_warning(tmp_path: Path) -> None:
    with _seed(tmp_path):
        _research_pod(send=False)
        result = invoke_pod(["check", "--posture", "--pod", "proj"])
    assert result.exit_code == 0, result.output
    assert "Untrusted input: web read of docs.python.org" in result.output
    assert "Outward action:  none" in result.output
    assert _WARNING not in result.output


def test_the_dry_run_still_needs_its_text_and_role(tmp_path: Path) -> None:
    with _seed(tmp_path):
        build_pod("proj", pod.DEFAULT_POD_ROLES, codebase="/src/proj")
        assert invoke_pod(["check", "--pod", "proj"]).exit_code == 2
        assert invoke_pod(["check", "ls", "--pod", "proj"]).exit_code == 2
