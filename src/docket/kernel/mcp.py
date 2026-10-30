from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from docket.kernel.home import current_home

# An `env` value `secret:<name>` names a stored secret; docket resolves it when a turn loads the
# server and never writes the value (specs/functional/mcp-client.spec.md Requirements 47-50).
SECRET_PREFIX = "secret:"
SECRET_NAME_RE = re.compile(r"[A-Za-z0-9_.-]+")
_CREDENTIAL_SUFFIXES = ("_TOKEN", "_KEY", "_SECRET", "_PASSWORD")


def secret_reference(value: str) -> str | None:
    """The secret name *value* refers to (possibly empty or malformed), else ``None`` for a literal."""
    return value[len(SECRET_PREFIX) :] if value.startswith(SECRET_PREFIX) else None


def is_credential_name(var: str) -> bool:
    """Whether the environment variable *var* is named like a credential."""
    return var.upper().endswith(_CREDENTIAL_SUFFIXES)


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
    # as "write", matching 1.1.0-1.4.0's unconditional behavior exactly. "send" marks a server
    # whose tools act outside the machine; only a role naming one holds it.
    kind: Literal["read", "write", "send"] = "write"
    # Non-empty = the exhaustive allow-list of this server's remote tool
    # names to register; every other advertised tool is skipped (recorded
    # in McpServerLoadResult.skipped), never silently dropped. Empty (the
    # default) means "register everything advertised" -- today's behavior.
    tools: list[str] = Field(default_factory=list)
    # "call" (the default) spawns one subprocess per exchange; "hop" keeps one stdio session open
    # for the hop's calls and closes it where the hop ends (specs/functional/mcp-client.spec.md
    # Requirements 41-46). A listing is always one subprocess.
    lifetime: Literal["call", "hop"] = "call"

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
