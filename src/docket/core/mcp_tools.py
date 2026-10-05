"""MCP client: pluggable external tool servers, gated like a built-in. docket owns the loop, the tool
registry, tool dispatch and every gate; MCP is only a tool *transport*, rented -- docket stays the
dispatcher. This module adapts a configured server's tools into ordinary ``core.tools.Tool``
objects, registered into a ``ToolRegistry`` so every call still passes through
``core.tools.dispatch_tool``. **Wired to the live turn path**: ``DocketDriver.run_turn`` loads MCP
tools before ``core/agent_loop.py``'s role-narrowing step; every adapted tool registers its
server's declared ``kind`` (:func:`_build_tool`, ``McpServerConfig.kind``, defaulting to
``"write"``), so a role denied ``write`` loses every MCP tool from a server left at the default.
A server may also narrow *which* of its tools get registered via ``McpServerConfig.tools``. See
specs/functional/mcp-client.spec.md for the namespacing rule, failure isolation
(:func:`load_mcp_tools` never raises), and untrusted-description screening through
``core.policy.policy_eval_detail(role, "pre_input", ..., trusted=False)`` before registration."""

from __future__ import annotations

import functools
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

import docket.config as _cfg
from docket.core import policy as _policy
from docket.core.audit import audit_log
from docket.core.tools import Tool, ToolContext, ToolRegistry, screen_tool_result
from docket.edges import store as _store
from docket.edges.adapters.toolbox import ToolOutcome

__all__ = [
    "NAMESPACE_PREFIX",
    "McpListResult",
    "McpRemoteTool",
    "McpServerConfig",
    "McpServerDocError",
    "McpServerDocument",
    "McpServerLoadResult",
    "McpServerRegistry",
    "McpToolSkip",
    "StdioLaunch",
    "add_mcp_server",
    "load_mcp_server_document",
    "load_mcp_servers",
    "load_mcp_tools",
    "namespaced_tool_name",
    "pod_mcp_servers_file",
    "pod_scoped_owner",
    "remove_mcp_server",
    "write_pod_mcp_servers",
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
    # Operator assertion: False starts this stdio server on the host even when the turn is
    # isolated (specs/functional/mcp-client.spec.md Requirement 40). True, the default, jails it
    # like `bash`.
    isolate: bool = True

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


def pod_mcp_servers_file(project: str) -> Path:
    """Where *project*'s own pod-scoped servers live: ``<pod config dir>/mcp-servers.json``."""
    return _cfg.pod_config_dir(project) / "mcp-servers.json"


def load_pod_mcp_servers(project: str) -> list[McpServerConfig]:
    """*project*'s own pod-scoped servers, in on-disk order. Empty when it has none."""
    data = _store.read_json(pod_mcp_servers_file(project))
    return McpServerRegistry.model_validate(data).servers


def load_mcp_servers(project: str = "") -> list[McpServerConfig]:
    """The configured MCP servers, in on-disk order; empty when unconfigured. With *project*,
    the pod's own pod-scoped servers follow the global ones (a global name wins a collision)."""
    data = _store.read_json(_cfg.MCP_SERVERS_FILE)
    servers = McpServerRegistry.model_validate(data).servers
    if not project:
        return servers
    taken = {s.name for s in servers}
    return [*servers, *(s for s in load_pod_mcp_servers(project) if s.name not in taken)]


def write_pod_mcp_servers(project: str, servers: list[McpServerConfig]) -> None:
    """Replace *project*'s pod-scoped server file with *servers*, through ``edges/store.py``."""
    path = pod_mcp_servers_file(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    _store.write_json(path, McpServerRegistry(servers=servers))


def pod_scoped_owner(name: str, *, exclude: str = "") -> str:
    """The pod (other than *exclude*) whose pod-scoped file declares *name*, else ``""``."""
    if not _cfg.PODS_DIR.is_dir():
        return ""
    for entry in sorted(_cfg.PODS_DIR.iterdir()):
        if entry.name == exclude or not pod_mcp_servers_file(entry.name).is_file():
            continue
        if any(s.name == name for s in load_pod_mcp_servers(entry.name)):
            return entry.name
    return ""


class McpServerDocError(ValueError):
    """A ``kind: mcp-server`` document is unreadable or invalid; the message names the file."""


class McpServerDocument(BaseModel):
    """A ``kind: mcp-server`` document: the global server fields, with the read/write assertion
    under ``access`` because ``kind`` is the envelope."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["mcp-server"]
    name: str
    command: str
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    timeout: float = 0.0
    access: Literal["read", "write"] = "write"
    tools: list[str] = Field(default_factory=list)

    def to_config(self) -> McpServerConfig:
        return McpServerConfig(
            name=self.name,
            command=self.command,
            args=self.args,
            env=self.env,
            timeout=self.timeout,
            kind=self.access,
            tools=self.tools,
        )


def mcp_server_document(config: McpServerConfig) -> dict[str, Any]:
    """*config* as a ``kind: mcp-server`` document mapping (the inverse of ``to_config``)."""
    doc: dict[str, Any] = {"kind": "mcp-server", "name": config.name, "command": config.command}
    if config.args:
        doc["args"] = list(config.args)
    if config.env:
        doc["env"] = dict(config.env)
    if config.timeout:
        doc["timeout"] = config.timeout
    doc["access"] = config.kind
    if config.tools:
        doc["tools"] = list(config.tools)
    return doc


def load_mcp_server_document(path: str | Path) -> McpServerConfig:
    """Read *path* as a ``kind: mcp-server`` document. Raises ``McpServerDocError`` naming the
    file on any failure, including a name that would not be a legal server name."""
    p = Path(path)
    try:
        import yaml as _yaml  # type: ignore[import-untyped]

        raw = _yaml.safe_load(p.read_text(encoding="utf-8"))
    except ImportError:
        raise McpServerDocError(f"{p}: PyYAML not installed -- run: pip install pyyaml") from None
    except Exception as exc:
        raise McpServerDocError(f"{p}: cannot read document: {exc}") from exc
    if not isinstance(raw, dict):
        raise McpServerDocError(f"{p}: document must be a mapping")
    try:
        config = McpServerDocument.model_validate(raw).to_config()
    except ValidationError as exc:
        first = exc.errors()[0]
        field = ".".join(str(part) for part in first["loc"])
        raise McpServerDocError(f"{p}: {field}: {first['msg']}") from exc
    if not _NAME_RE.fullmatch(config.name):
        raise McpServerDocError(
            f"{p}: name {config.name!r} must contain only letters, digits, '-' or '_'"
        )
    return config


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
@dataclass(frozen=True)
class StdioLaunch:
    """How a turn starts its stdio servers: the directory, and the jail (when ``sandbox`` is
    ``"auto"``) with its roots and network mode. A runtime value, never stored in a config."""

    cwd: str | None = None
    sandbox: Literal["auto", "off"] = "off"
    network: bool = True
    roots: tuple[Path, ...] = ()


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


def _screen_result(
    role: str, server_name: str, tool_name: str, outcome: ToolOutcome
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
    )


def _build_tool(
    name: str,
    remote: McpRemoteTool,
    config: McpServerConfig,
    call_tool: CallToolFn,
    timeout: float,
) -> Tool:
    """Adapt one remote tool into an ordinary ``core.tools.Tool``.

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
        return _screen_result(ctx.role, config.name, remote.name, outcome)

    description = f"[MCP:{config.name}] {remote.description}".strip()
    return Tool(
        name=name,
        description=description,
        parameters=parameters,
        handler=_handler,
        kind=config.kind,
    )


# ── the orchestration `core/agent_loop.py` will call once wired ────────────


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
    servers: Sequence[McpServerConfig] | None = None,
    list_tools: ListToolsFn | None = None,
    call_tool: CallToolFn | None = None,
    role: str = "",
    launch: StdioLaunch | None = None,
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
    never requires the optional ``mcp`` SDK to be installed; tests inject fakes here instead. *launch*, when given, is how every stdio server is
    started for this load and for the calls it adapts; it is never stored."""
    if servers is None:
        servers = load_mcp_servers()
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
            audit_log("mcp_client.unavailable", f"server={config.name!r}: {listing.error}")
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

            skip_reason = _screen_description(role, config.name, remote)
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
