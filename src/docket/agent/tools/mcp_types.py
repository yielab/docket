from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

# ── the port this module programs against (implemented in agent/tools/mcp_client.py) ──────────


@dataclass(frozen=True)
class McpRemoteTool:
    """One tool exactly as a remote server advertised it -- before namespacing
    or any policy screening."""

    name: str
    description: str = ""
    parameters: dict[str, Any] = field(default_factory=dict)


@dataclass
class McpListResult:
    """Outcome of asking one server for its tool list. Never raised -- a
    connection/protocol failure is ordinary data here, not an exception."""

    ok: bool
    tools: tuple[McpRemoteTool, ...] = ()
    error: str = ""


# The two operations `agent/tools/mcp_client.py` implements. Injectable so
# this module's own tests never touch the real SDK/a subprocess -- the
# "stub at the SDK boundary" this card's tests are required to use.
@dataclass(frozen=True)
class StdioLaunch:
    """How a turn starts its stdio servers: the directory, and the jail (when ``sandbox`` is
    ``"auto"``) with its roots and network mode. A runtime value, never stored in a config."""

    cwd: str | None = None
    sandbox: Literal["auto", "off"] = "off"
    network: bool = True
    roots: tuple[Path, ...] = ()
    read_only: tuple[Path, ...] = ()
