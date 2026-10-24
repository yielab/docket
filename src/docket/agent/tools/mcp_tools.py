"""MCP client: pluggable external tool servers, gated like a built-in. docket owns the loop, the tool
registry, tool dispatch and every gate; MCP is only a tool *transport*, rented -- docket stays the
dispatcher. This module adapts a configured server's tools into ordinary ``agent.tools.registry.Tool``
objects, registered into a ``ToolRegistry`` so every call still passes through
``agent.tools.registry.dispatch_tool``. **Wired to the live turn path**: ``DocketDriver.run_turn`` loads MCP
tools before ``agent/loop.py``'s role-narrowing step; every adapted tool registers its
server's declared ``kind`` (:func:`_build_tool`, ``McpServerConfig.kind``, defaulting to
``"write"``), so a role denied ``write`` loses every MCP tool from a server left at the default.
A server may also narrow *which* of its tools get registered via ``McpServerConfig.tools``. See
specs/functional/mcp-client.spec.md for the namespacing rule, failure isolation
(:func:`load_mcp_tools` never raises), and untrusted-description screening through
``governance.policy.policy_eval_detail(role, "pre_input", ..., trusted=False)`` before registration."""

from __future__ import annotations

import functools
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol

from docket.agent.ports import tool_gate
from docket.agent.tools.builtins.toolbox import ToolOutcome
from docket.agent.tools.registry import Tool, ToolContext, ToolRegistry
from docket.agent.tools.screening import screen_tool_result
from docket.kernel.mcp import McpServerConfig

__all__ = [
    "NAMESPACE_PREFIX",
    "McpListResult",
    "McpRemoteTool",
    "McpServerConfig",
    "McpServerLoadResult",
    "McpToolSkip",
    "StdioLaunch",
    "load_mcp_tools",
    "namespaced_tool_name",
]

# Every adapted tool name starts with this. No built-in tool name does (they
# are bare words: "read", "write", "edit", "glob", "grep", "bash"), so this
# prefix alone makes a collision with a built-in structurally impossible --
# see specs/functional/mcp-client.spec.md (namespacing).
NAMESPACE_PREFIX = "mcp__"


def namespaced_tool_name(server_name: str, remote_tool_name: str) -> str:
    """The name an adapted tool is registered under -- see specs/functional/mcp-client.spec.md's
    "Namespacing" section."""
    return f"{NAMESPACE_PREFIX}{server_name}__{remote_tool_name}"


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


class ListToolsFn(Protocol):
    def __call__(
        self, config: McpServerConfig, timeout: float, launch: StdioLaunch | None = None
    ) -> McpListResult: ...


class CallToolFn(Protocol):
    def __call__(
        self,
        config: McpServerConfig,
        name: str,
        arguments: dict[str, Any],
        timeout: float,
        launch: StdioLaunch | None = None,
    ) -> ToolOutcome: ...


def _default_list_tools() -> ListToolsFn:
    from docket.agent.tools import mcp_client as _client

    return _client.list_remote_tools


def _default_call_tool() -> CallToolFn:
    from docket.agent.tools import mcp_client as _client

    return _client.call_remote_tool


# ── screening a remote tool's description before it reaches a model ────────


def _screen_description(
    role: str, server_name: str, remote: McpRemoteTool, *, project: str = ""
) -> str | None:
    """Run one remote tool's name+description through the `pre_input` policy hook (the calling
    pod's policies included); returns a skip reason if the tool must not be registered, else
    ``None``. See specs/functional/mcp-client.spec.md "Untrusted tool descriptions"."""
    hit = tool_gate.screen_untrusted(
        role,
        f"{remote.name}: {remote.description}",
        project=project,
        detail=f"server={server_name!r} tool={remote.name!r}",
        blocked_action="mcp_client.tool_description_blocked",
        warn_action="mcp_client.tool_description_warn",
    )
    if hit.action in ("block", "require_approval"):
        return f"description blocked by policy {hit.policy_id!r} (action={hit.action})"
    return None


def _screen_result(
    role: str, server_name: str, tool_name: str, outcome: ToolOutcome, *, project: str = ""
) -> ToolOutcome:
    """Screen one remote tool result as untrusted input through the `pre_input` hook: block
    refuses, redact strips secrets, warn passes; each non-allow hit is audited. See the spec's
    "Untrusted tool results" section."""
    return screen_tool_result(
        role,
        outcome,
        source=f"MCP server {server_name!r}",
        detail=f"server={server_name!r} tool={tool_name!r}",
        blocked_action="mcp_client.tool_result_blocked",
        warn_action="mcp_client.tool_result_warn",
        project=project,
    )


def _build_tool(
    name: str,
    remote: McpRemoteTool,
    config: McpServerConfig,
    call_tool: CallToolFn,
    timeout: float,
) -> Tool:
    """Adapt one remote tool into an ordinary ``agent.tools.registry.Tool``.

    ``kind`` is the *server's* declared ``McpServerConfig.kind`` -- ``"read"`` or ``"write"``,
    defaulting to ``"write"`` -- never ``"exec"``: `evaluate_tool_call` routes ``exec``-kind tools
    through the shell-command classifier, which reads ``args["command"]`` and would not find one
    here. Either kind still passes through the full `pre_tool_call` policy gate; a declared
    ``"read"`` kind is simply not additionally classified as a shell command and is excluded from
    a role's ``write``-implied denial, which is correct -- an MCP tool call is not a shell
    command, and `kind` is an operator assertion about the server, not a docket-verified fact."""
    parameters = remote.parameters
    if not isinstance(parameters, dict) or parameters.get("type") != "object":
        parameters = {"type": "object", "properties": {}, "required": []}

    def _handler(args: dict[str, Any], ctx: ToolContext) -> ToolOutcome:
        # dispatch_tool has already gated the call; this runs the protocol exchange, then
        # screens what the remote server sent back, which is untrusted like its description.
        outcome = call_tool(config, remote.name, args, timeout)
        return _screen_result(ctx.role, config.name, remote.name, outcome, project=ctx.project)

    description = f"[MCP:{config.name}] {remote.description}".strip()
    return Tool(
        name=name,
        description=description,
        parameters=parameters,
        handler=_handler,
        kind=config.kind,
    )


# ── the orchestration `agent/loop.py` calls ───────────────────────────


@dataclass(frozen=True)
class McpToolSkip:
    """One tool that was not registered, and why."""

    tool_name: str
    reason: str


@dataclass
class McpServerLoadResult:
    """Outcome of loading one configured server's tools into a registry. ``kind`` names the
    server's declared trust level at load time."""

    server: str
    ok: bool
    kind: Literal["read", "write"] = "write"
    registered: tuple[str, ...] = ()
    skipped: tuple[McpToolSkip, ...] = ()
    error: str = ""


def load_mcp_tools(
    registry: ToolRegistry,
    *,
    servers: Sequence[McpServerConfig],
    list_tools: ListToolsFn | None = None,
    call_tool: CallToolFn | None = None,
    role: str = "",
    project: str = "",
    launch: StdioLaunch | None = None,
) -> list[McpServerLoadResult]:
    """Connect to every configured MCP server, enumerate its tools, and register each as a
    namespaced :class:`~docket.agent.tools.registry.Tool` into *registry* via its public
    :meth:`~docket.agent.tools.registry.ToolRegistry.register`.

    Intended to be called once against a freshly built registry (typically
    ``agent.tools.registry.builtin_registry()``) -- built-ins should already be present, since a namespaced
    MCP name can never collide with one (see specs/functional/mcp-client.spec.md's "Namespacing"
    section), but a name already present in *registry* for any other reason is skipped, never
    overwritten: this function only ever adds. Never raises. *servers* is the catalog the caller
    selected (``teams.mcp_servers.load_mcp_servers``); *list_tools*/*call_tool* default to the real
    ``agent/tools/mcp_client.py`` implementations, resolved lazily so importing this module
    never requires the optional ``mcp`` SDK to be installed; tests inject fakes here instead. *launch*, when given, is how every stdio server is
    started for this load and for the calls it adapts; it is never stored."""
    if list_tools is None:
        list_tools = _default_list_tools()
    if call_tool is None:
        call_tool = _default_call_tool()
    if launch is not None:
        list_tools = functools.partial(list_tools, launch=launch)
        call_tool = functools.partial(call_tool, launch=launch)

    reports: list[McpServerLoadResult] = []
    for config in servers:
        timeout = config.resolved_timeout()
        try:
            listing = list_tools(config, timeout)
        except Exception as ex:  # a broken adapter must never take the whole load down
            listing = McpListResult(ok=False, error=f"{type(ex).__name__}: {ex}")

        if not listing.ok:
            tool_gate.audit_event(
                "mcp_client.unavailable", f"server={config.name!r}: {listing.error}"
            )
            reports.append(
                McpServerLoadResult(config.name, ok=False, kind=config.kind, error=listing.error)
            )
            continue

        registered: list[str] = []
        skipped: list[McpToolSkip] = []
        for remote in listing.tools:
            name = namespaced_tool_name(config.name, remote.name)

            if name in registry:
                skipped.append(McpToolSkip(name, "a tool with this name is already registered"))
                continue

            if config.tools and remote.name not in config.tools:
                skipped.append(McpToolSkip(name, "not in the server's `tools` list"))
                continue

            skip_reason = _screen_description(role, config.name, remote, project=project)
            if skip_reason is not None:
                skipped.append(McpToolSkip(name, skip_reason))
                continue

            registry.register(_build_tool(name, remote, config, call_tool, timeout))
            registered.append(name)

        reports.append(
            McpServerLoadResult(
                config.name,
                ok=True,
                kind=config.kind,
                registered=tuple(registered),
                skipped=tuple(skipped),
            )
        )

    return reports
