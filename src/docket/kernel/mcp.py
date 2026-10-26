from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from docket.kernel.home import current_home

# ── config: docket-owned state, persisted through platform/store.py ────────────


class McpServerConfig(BaseModel):
    """One configured external MCP tool server (stdio transport only, today).

    ``name`` is chosen by the local operator at ``add_mcp_server`` time -- it is what
    :func:`namespaced_tool_name` uses, never anything the remote server itself reports (it has no
    way to influence its own namespace)."""

    model_config = ConfigDict(populate_by_name=True)

    name: str
    command: str
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    # 0 (the default) means "use MCP_CLIENT_TIMEOUT_S"; any value is still
    # clamped to MCP_CLIENT_MAX_TIMEOUT_S by resolved_timeout() below --
    # timeouts must be bounded regardless of what a config asks for.
    timeout: float = 0.0
    # Operator assertion, never inferred by connecting to the server (see
    # specs/functional/mcp-client.spec.md Requirement 32). "write" is the
    # fail-closed default -- a config from before this field existed loads
    # as "write", matching 1.1.0-1.4.0's unconditional behavior exactly.
    kind: Literal["read", "write"] = "write"
    # Non-empty = the exhaustive allow-list of this server's remote tool
    # names to register; every other advertised tool is skipped (recorded
    # in McpServerLoadResult.skipped), never silently dropped. Empty (the
    # default) means "register everything advertised" -- today's behavior.
    tools: list[str] = Field(default_factory=list)

    def resolved_timeout(self) -> float:
        """The actual per-call bound this server's calls will honor.

        Never trusts a configured ``timeout`` outright: it is clamped to
        :data:`Home.mcp_client_max_timeout_s` so one server's config (careless or
        hostile) cannot buy itself an effectively unbounded wait."""
        requested = self.timeout if self.timeout > 0 else current_home().mcp_client_timeout_s
        return min(requested, current_home().mcp_client_max_timeout_s)


class McpServerRegistry(BaseModel):
    """The on-disk shape of :data:`Home.mcp_servers_file`."""

    model_config = ConfigDict(populate_by_name=True)

    servers: list[McpServerConfig] = Field(default_factory=list)
