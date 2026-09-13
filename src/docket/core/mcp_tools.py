"""MCP client: pluggable external tool servers, gated like a built-in. docket owns the loop, the tool
registry, tool dispatch and every gate; MCP is only a tool *transport*, rented -- docket stays the
dispatcher. This module adapts a configured server's tools into ordinary ``core.tools.Tool``
objects, registered into a ``ToolRegistry`` so every call still passes through
``core.tools.dispatch_tool``. **Wired to the live turn path**: ``DocketDriver.run_turn`` loads MCP
tools before ``core/agent_loop.py``'s role-narrowing step; every adapted tool registers
``kind="write"`` unconditionally (:func:`_build_tool`), so a role denied ``write`` loses every MCP
tool too, since ``kind`` is shared narrowing data. See specs/functional/mcp-client.spec.md for the
namespacing rule that makes a built-in collision structurally impossible, failure isolation
(:func:`load_mcp_tools` never raises; a bad server is skipped and recorded, bounded by
``MCP_CLIENT_TIMEOUT_S``), and untrusted-description screening through
``core.policy.policy_eval_detail(role, "pre_input", ..., trusted=False)`` before registration."""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

import docket.config as _cfg
from docket.core import policy as _policy
from docket.core.audit import audit_log
from docket.core.tools import Tool, ToolContext, ToolRegistry
from docket.edges import store as _store
from docket.edges.adapters.toolbox import ToolOutcome

__all__ = [
    "NAMESPACE_PREFIX",
    "McpListResult",
    "McpRemoteTool",
    "McpServerConfig",
    "McpServerLoadResult",
    "McpServerRegistry",
    "McpToolSkip",
    "add_mcp_server",
    "load_mcp_servers",
    "load_mcp_tools",
    "namespaced_tool_name",
    "remove_mcp_server",
]

# Every adapted tool name starts with this. No built-in tool name does (they
# are bare words: "read", "write", "edit", "glob", "grep", "bash"), so this
# prefix alone makes a collision with a built-in structurally impossible --
# see specs/functional/mcp-client.spec.md (namespacing).
NAMESPACE_PREFIX = "mcp__"

# A configured server's *local* name is docket-owned config, not remote input,
# but it still ends up as a path-like fragment in a tool name shown to a
# model -- restrict it to an unambiguous charset rather than trusting an
# operator not to fat-finger something that renders confusingly.
_NAME_RE = re.compile(r"[A-Za-z0-9_-]+")


# ── config: docket-owned state, persisted through edges/store.py ────────────


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

    def resolved_timeout(self) -> float:
        """The actual per-call bound this server's calls will honor.

        Never trusts a configured ``timeout`` outright: it is clamped to
        :data:`docket.config.MCP_CLIENT_MAX_TIMEOUT_S` so one server's config (careless or
        hostile) cannot buy itself an effectively unbounded wait."""
        requested = self.timeout if self.timeout > 0 else _cfg.MCP_CLIENT_TIMEOUT_S
        return min(requested, _cfg.MCP_CLIENT_MAX_TIMEOUT_S)


class McpServerRegistry(BaseModel):
    """The on-disk shape of :data:`docket.config.MCP_SERVERS_FILE`."""

    model_config = ConfigDict(populate_by_name=True)

    servers: list[McpServerConfig] = Field(default_factory=list)


def load_mcp_servers() -> list[McpServerConfig]:
    """The configured MCP servers, in on-disk order. Empty when unconfigured."""
    data = _store.read_json(_cfg.MCP_SERVERS_FILE)
    return McpServerRegistry.model_validate(data).servers


def add_mcp_server(config: McpServerConfig) -> None:
    """Add one server config. Raises ``ValueError`` on a bad/duplicate name.

    Lock-safe: uses ``edges/store.py``'s ``read_modify_write`` so two concurrent ``add`` calls
    cannot race each other into losing an entry."""
    if not config.name:
        raise ValueError("MCP server name is required")
    if not _NAME_RE.fullmatch(config.name):
        raise ValueError(
            f"MCP server name {config.name!r} must contain only letters, digits, '-' or '_'"
        )

    def _add(current: dict[str, Any]) -> dict[str, Any]:
        reg = McpServerRegistry.model_validate(current)
        if any(s.name == config.name for s in reg.servers):
            raise ValueError(f"an MCP server named {config.name!r} is already configured")
        reg.servers.append(config)
        return reg.model_dump(by_alias=True)

    _store.read_modify_write(_cfg.MCP_SERVERS_FILE, _add)


def remove_mcp_server(name: str) -> bool:
    """Remove a configured server by name. Returns False if it wasn't there."""
    removed = False

    def _remove(current: dict[str, Any]) -> dict[str, Any] | None:
        nonlocal removed
        reg = McpServerRegistry.model_validate(current)
        kept = [s for s in reg.servers if s.name != name]
        if len(kept) == len(reg.servers):
            return None  # nothing changes -- read_modify_write leaves the file untouched
        removed = True
        return McpServerRegistry(servers=kept).model_dump(by_alias=True)

    _store.read_modify_write(_cfg.MCP_SERVERS_FILE, _remove)
    return removed


def namespaced_tool_name(server_name: str, remote_tool_name: str) -> str:
    """The name an adapted tool is registered under -- see specs/functional/mcp-client.spec.md's
    "Namespacing" section."""
    return f"{NAMESPACE_PREFIX}{server_name}__{remote_tool_name}"


# ── the port this module programs against (implemented in edges/) ──────────


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


# The two operations `edges/adapters/mcp_client.py` implements. Injectable so
# this module's own tests never touch the real SDK/a subprocess -- the
# "stub at the SDK boundary" this card's tests are required to use.
ListToolsFn = Callable[[McpServerConfig, float], McpListResult]
CallToolFn = Callable[[McpServerConfig, str, dict[str, Any], float], ToolOutcome]


def _default_list_tools() -> ListToolsFn:
    from docket.edges.adapters import mcp_client as _client

    return _client.list_remote_tools


def _default_call_tool() -> CallToolFn:
    from docket.edges.adapters import mcp_client as _client

    return _client.call_remote_tool


# ── screening a remote tool's description before it reaches a model ────────


def _screen_description(role: str, server_name: str, remote: McpRemoteTool) -> str | None:
    """Run one remote tool's name+description through the `pre_input` policy hook. Returns a
    skip reason if the tool must not be registered, else ``None``. See
    specs/functional/mcp-client.spec.md's "Untrusted tool descriptions" section."""
    text = f"{remote.name}: {remote.description}"
    hit = _policy.policy_eval_detail(role, "pre_input", text, trusted=False)
    if hit.action in ("block", "require_approval"):
        audit_log(
            "mcp_client.tool_description_blocked",
            f"server={server_name!r} tool={remote.name!r} "
            f"policy={hit.policy_id!r} action={hit.action}",
        )
        return f"description blocked by policy {hit.policy_id!r} (action={hit.action})"
    if hit.action in ("warn", "redact"):
        audit_log(
            "mcp_client.tool_description_warn",
            f"server={server_name!r} tool={remote.name!r} "
            f"policy={hit.policy_id!r} action={hit.action}",
        )
    return None


def _build_tool(
    name: str,
    remote: McpRemoteTool,
    config: McpServerConfig,
    call_tool: CallToolFn,
    timeout: float,
) -> Tool:
    """Adapt one remote tool into an ordinary ``core.tools.Tool``.

    ``kind="write"`` always -- never ``"exec"``: `evaluate_tool_call` routes ``exec``-kind tools
    through the shell-command classifier, which reads ``args["command"]`` and would not find one
    here. `write` still passes through the full `pre_tool_call` policy gate; it is simply not
    additionally classified as a shell command, which is correct -- an MCP tool call is not one."""
    parameters = remote.parameters
    if not isinstance(parameters, dict) or parameters.get("type") != "object":
        parameters = {"type": "object", "properties": {}, "required": []}

    def _handler(args: dict[str, Any], _ctx: ToolContext) -> ToolOutcome:
        # No policy/approval logic here -- by the time a handler runs,
        # dispatch_tool has already gated the call. This closure only ever
        # runs the underlying protocol exchange, exactly like a built-in
        # tool's own handler in core/tools.py's builtin_registry().
        return call_tool(config, remote.name, args, timeout)

    description = f"[MCP:{config.name}] {remote.description}".strip()
    return Tool(
        name=name, description=description, parameters=parameters, handler=_handler, kind="write"
    )


# ── the orchestration `core/agent_loop.py` will call once wired ────────────


@dataclass(frozen=True)
class McpToolSkip:
    """One tool that was not registered, and why."""

    tool_name: str
    reason: str


@dataclass
class McpServerLoadResult:
    """Outcome of loading one configured server's tools into a registry."""

    server: str
    ok: bool
    registered: tuple[str, ...] = ()
    skipped: tuple[McpToolSkip, ...] = ()
    error: str = ""


def load_mcp_tools(
    registry: ToolRegistry,
    *,
    servers: Sequence[McpServerConfig] | None = None,
    list_tools: ListToolsFn | None = None,
    call_tool: CallToolFn | None = None,
    role: str = "",
) -> list[McpServerLoadResult]:
    """Connect to every configured MCP server, enumerate its tools, and register each as a
    namespaced :class:`~docket.core.tools.Tool` into *registry* via its public
    :meth:`~docket.core.tools.ToolRegistry.register`.

    Intended to be called once against a freshly built registry (typically
    ``core.tools.builtin_registry()``) -- built-ins should already be present, since a namespaced
    MCP name can never collide with one (see specs/functional/mcp-client.spec.md's "Namespacing"
    section), but a name already present in *registry* for any other reason is skipped, never
    overwritten: this function only ever adds. Never raises. *servers* defaults to
    :func:`load_mcp_servers`; *list_tools*/*call_tool* default to the real
    ``edges/adapters/mcp_client.py`` implementations, resolved lazily so importing this module
    never requires the optional ``mcp`` SDK to be installed; tests inject fakes here instead."""
    if servers is None:
        servers = load_mcp_servers()
    if list_tools is None:
        list_tools = _default_list_tools()
    if call_tool is None:
        call_tool = _default_call_tool()

    reports: list[McpServerLoadResult] = []
    for config in servers:
        timeout = config.resolved_timeout()
        try:
            listing = list_tools(config, timeout)
        except Exception as ex:  # a broken adapter must never take the whole load down
            listing = McpListResult(ok=False, error=f"{type(ex).__name__}: {ex}")

        if not listing.ok:
            audit_log("mcp_client.unavailable", f"server={config.name!r}: {listing.error}")
            reports.append(McpServerLoadResult(config.name, ok=False, error=listing.error))
            continue

        registered: list[str] = []
        skipped: list[McpToolSkip] = []
        for remote in listing.tools:
            name = namespaced_tool_name(config.name, remote.name)

            if name in registry:
                skipped.append(McpToolSkip(name, "a tool with this name is already registered"))
                continue

            skip_reason = _screen_description(role, config.name, remote)
            if skip_reason is not None:
                skipped.append(McpToolSkip(name, skip_reason))
                continue

            registry.register(_build_tool(name, remote, config, call_tool, timeout))
            registered.append(name)

        reports.append(
            McpServerLoadResult(
                config.name, ok=True, registered=tuple(registered), skipped=tuple(skipped)
            )
        )

    return reports
