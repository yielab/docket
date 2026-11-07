"""The three powers a pod holds, from what it declares: untrusted input, private data and an
outward action (the Agents Rule of Two).

Holding two is a design; holding all three needs a person. This module names what grants each
power and words the warning; ``docket pod check --posture`` prints it and the lights-out profile
(``hops/gates/profile.py``) refuses a pod holding all three with the same words.
"""

from __future__ import annotations

from dataclasses import dataclass

from docket.governance import secrets as _secrets
from docket.kernel.mcp import McpServerConfig, secret_reference
from docket.teams import mcp_servers as _mcp_servers
from docket.teams import network_posture as _network_posture
from docket.teams import pod_settings as _pod_settings
from docket.teams.models import WorkspaceKind


@dataclass(frozen=True)
class Powers:
    """What grants each power to a pod; an empty tuple means the pod does not hold it."""

    untrusted_input: tuple[str, ...]
    private_data: tuple[str, ...]
    outward: tuple[str, ...]

    @property
    def holds_all(self) -> bool:
        return bool(self.untrusted_input and self.private_data and self.outward)

    def detail(self) -> str:
        """The sentence saying the pod holds all three, ``""`` when it does not."""
        if not self.holds_all:
            return ""
        return "holds untrusted input, private data and an outward action together"

    def fix(self) -> str:
        """What to drop, naming what grants each power, ``""`` when the pod holds fewer than three."""
        if not self.holds_all:
            return ""
        return "drop one: " + "; or ".join(
            f"{label} ({', '.join(granted)})"
            for label, granted in (
                ("the outward action", self.outward),
                ("the untrusted input", self.untrusted_input),
                ("the private data", self.private_data),
            )
        )

    def warning(self) -> str:
        """The one line ``pod check --posture`` prints, ``""`` when the pod holds fewer than three."""
        return f"{self.detail()}; {self.fix()}" if self.holds_all else ""


def _selected_servers(project: str) -> list[McpServerConfig]:
    """The MCP servers the pod's turns can use: its ``mcpServers`` selection, else every server."""
    try:
        selection = _pod_settings.PodSettings.load_for(project).mcp_servers
    except _pod_settings.PodSettingsError:
        selection = None
    return [
        s
        for s in _mcp_servers.load_mcp_servers(project)
        if selection is None or s.name in selection
    ]


def _injected_secrets(server: McpServerConfig, stored: set[str]) -> list[str]:
    return [
        var
        for var, value in server.env.items()
        if secret_reference(value) is not None or var in stored
    ]


def powers(project: str) -> Powers:
    """The powers *project* holds, from its settings, MCP servers, secrets and workspace."""
    servers = _selected_servers(project)
    stored = _secrets.secrets_keys()
    hosts = _network_posture.fetch_reach(project).hosts
    untrusted = [f"web read of {', '.join(hosts)}"] if hosts else []
    untrusted += [f"MCP server {s.name} (read)" for s in servers if s.kind == "read"]
    private = (
        ["the codebase"] if _pod_settings.workspace_kind(project) == WorkspaceKind.codebase else []
    )
    for server in servers:
        private += [
            f"secret {var} injected into MCP server {server.name}"
            for var in _injected_secrets(server, stored)
        ]
    outward = [f"MCP server {s.name} (send)" for s in servers if s.kind == "send"]
    if _pod_settings.effective_network(project)[0] != "none":
        outward.append("network open")
    if _pod_settings.workspace_kind(project) == WorkspaceKind.workdir:
        outward.append("a folder outside the repository (workDir)")
    return Powers(tuple(untrusted), tuple(private), tuple(outward))
