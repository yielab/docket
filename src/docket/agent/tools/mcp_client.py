"""MCP client adapter.

The one shipped implementation of ``agent/tools/mcp_tools.py``'s two-function port
(``ListToolsFn``/``CallToolFn``) -- the only module in docket that knows the
MCP wire protocol exists, or that a subprocess is involved at all. Mirrors
``models/adapters/openai_http.py``'s split: the port's pure types live in ``agent/tools/mcp_tools.py``,
every protocol/SDK-specific detail lives here.

**Subprocess-per-exchange, on purpose** (``lifetime: call``; ``hop`` is :class:`HopSessions`). Each
public function here spawns a fresh stdio subprocess for exactly one exchange (list the tool
catalog, or call one tool) and tears it down again -- no connection is kept open between calls. That costs a little latency in exchange for real isolation: a
misbehaving server cannot corrupt a *stateful* connection some later,
unrelated call would otherwise inherit, and a killed/hung server cannot leak
past its own bounded timeout into anything else docket is doing. Every
exchange is wrapped in ``anyio.fail_after``, so an unresponsive server is
cancelled and reported as unavailable rather than left to block a turn.

**Optional dependency.** The official ``mcp`` SDK (``docket[mcp]``, see
``pyproject.toml``) is not a base dependency. Both public functions probe for
it and import it lazily, guarded by ``try``/``except ImportError`` -- the same
pattern ``interfaces/cli/commands/mcp.py`` already uses on the server side. A missing SDK comes
back as ordinary data (``MISSING_SDK_HINT`` in the result's ``error``), never
a bare traceback.

**Never raises.** A bad server, a missing SDK, a timeout, or a malformed
response all come back as an ordinary failed result. ``agent/tools/mcp_tools.py``'s
``load_mcp_tools`` and, for a call, ``agent/tools/registry.py``'s ``dispatch_tool`` (via
the ``Tool.handler`` built from this module's ``call_remote_tool``) both
expect "the server is unavailable" to be data, not an exception that unwinds
a turn.
"""

from __future__ import annotations

import concurrent.futures
import contextlib
from collections.abc import Callable
from pathlib import Path
from typing import Any

from docket.agent.tools.mcp_types import McpListResult, McpRemoteTool, StdioLaunch
from docket.kernel import ids as _ids
from docket.kernel.errors import Refused, Unavailable
from docket.kernel.mcp import McpServerConfig
from docket.kernel.ports import jail as _jail
from docket.kernel.tool_outcome import ToolOutcome, bounded_text

MISSING_SDK_HINT = (
    "The 'mcp' package is not installed -- an MCP tool server needs the optional MCP extra.\n"
    "Install it with:  pip install 'docket[mcp]'\n"
    "(uv projects:      uv sync --extra mcp   or   uv pip install 'docket[mcp]')"
)


def _sdk_available() -> bool:
    """True when the optional MCP client stack can actually be imported."""
    try:
        import anyio  # noqa: F401
        import mcp.client.stdio  # noqa: F401
    except ImportError:
        return False
    return True


def _truncate(text: str) -> str:
    # Resolved per call (in `bounded_text`): operators tune the cap to the active endpoint's
    # window, and tests may change it after this module is imported.
    return bounded_text(text)


def _stdio_params(config: McpServerConfig, launch: StdioLaunch | None = None) -> Any:
    """Build the SDK's spawn parameters for *config*. With *launch* the server starts in its
    ``cwd``, and inside the turn's jail when the turn is isolated.
    Imported lazily -- only called once ``_sdk_available()`` has confirmed the SDK."""
    from mcp.client.stdio import StdioServerParameters

    command, args = config.command, list(config.args)
    if launch is not None and launch.sandbox == "auto":
        command, args = _jailed_command(config, launch)
    return StdioServerParameters(
        command=command,
        args=args,
        env=dict(config.env) or None,
        cwd=launch.cwd if launch is not None else None,
    )


def _jailed_command(config: McpServerConfig, launch: StdioLaunch) -> tuple[str, list[str]]:
    """The jail's argv for *config*'s server. Fails closed: isolation is on, so no backend means
    no spawn rather than an unjailed one."""
    roots = launch.roots or ((Path(launch.cwd),) if launch.cwd else ())
    if not roots:
        raise Refused("isolation is on but the turn has no root to jail the server to")
    backend = _jail.sandbox_availability().backend
    server = [config.command, *config.args]
    if backend in ("landlock", "seatbelt"):
        tmp = _jail.jail_tmp_dir(roots, None)
        build = (
            _jail.landlock_command_argv if backend == "landlock" else _jail.seatbelt_command_argv
        )
        env = ["env", *(f"{k}={v}" for k, v in _jail.tmp_environment(tmp).items())]
        argv = build((*roots, tmp), [*env, *server], launch.network, launch.read_only)
    elif backend == "docker":
        name = _ids.new_short_id("docket-mcp")
        argv = _jail.docker_command_argv(
            name, roots, server, dict(config.env), launch.network, launch.read_only
        )
    else:
        raise Unavailable(
            "isolation is on but no sandbox backend is usable; use Linux 5.13+ (landlock) or "
            "macOS (seatbelt), or choose docker with 'docket setup sandbox backend docker'"
        )
    return argv[0], argv[1:]


async def _list_tools_async(
    config: McpServerConfig, timeout: float, launch: StdioLaunch | None = None
) -> McpListResult:
    import anyio
    from mcp.client import Client
    from mcp.client.stdio import stdio_client

    try:
        with anyio.fail_after(timeout):
            async with Client(stdio_client(_stdio_params(config, launch))) as client:
                result = await client.list_tools()
    except TimeoutError:
        return McpListResult(
            ok=False, error=f"MCP server {config.name!r} timed out after {timeout:.0f}s"
        )
    except Exception as ex:  # spawn failure, protocol error, malformed response, ...
        return McpListResult(
            ok=False, error=f"MCP server {config.name!r} failed: {type(ex).__name__}: {ex}"
        )

    tools = tuple(
        McpRemoteTool(
            name=t.name,
            description=t.description or "",
            parameters=t.input_schema if isinstance(t.input_schema, dict) else {},
        )
        for t in result.tools
    )
    return McpListResult(ok=True, tools=tools)


def list_remote_tools(
    config: McpServerConfig, timeout: float, launch: StdioLaunch | None = None
) -> McpListResult:
    """Connect to *config*, list its tools, disconnect. Never raises.

    *timeout* bounds the whole exchange (spawn + handshake + list +
    teardown) -- a server that never answers is cancelled, not awaited
    forever.
    """
    if not _sdk_available():
        return McpListResult(ok=False, error=MISSING_SDK_HINT)
    import anyio

    try:
        return anyio.run(_list_tools_async, config, timeout, launch)
    except Exception as ex:  # last-resort safety net; this function must never raise
        return McpListResult(ok=False, error=f"{type(ex).__name__}: {ex}")


def _render_content(result: Any) -> str:
    """Flatten a ``CallToolResult``'s content blocks into text for the model.

    Only text blocks carry text; anything else (image/audio/resource) is
    summarized by its block type rather than silently dropped, so the model
    at least knows the tool returned something it cannot see verbatim.
    """
    parts: list[str] = []
    for block in result.content:
        text = getattr(block, "text", None)
        if isinstance(text, str):
            parts.append(text)
        else:
            parts.append(f"[{getattr(block, 'type', 'content')} content omitted]")
    return "\n".join(parts) if parts else "(no output)"


def _outcome_of(result: Any) -> ToolOutcome:
    """A ``CallToolResult`` as the model-visible outcome, truncated to the output ceiling."""
    text = _truncate(_render_content(result))
    if getattr(result, "is_error", False):
        return ToolOutcome(False, error=text or "tool reported an error")
    return ToolOutcome(True, content=text)


async def _call_tool_async(
    config: McpServerConfig,
    name: str,
    arguments: dict[str, Any],
    timeout: float,
    launch: StdioLaunch | None = None,
) -> ToolOutcome:
    import anyio
    from mcp.client import Client
    from mcp.client.stdio import stdio_client

    try:
        with anyio.fail_after(timeout):
            async with Client(stdio_client(_stdio_params(config, launch))) as client:
                result = await client.call_tool(name, arguments)
    except TimeoutError:
        return ToolOutcome(
            False, error=f"MCP server {config.name!r} timed out after {timeout:.0f}s"
        )
    except Exception as ex:
        return ToolOutcome(
            False, error=f"MCP server {config.name!r} call failed: {type(ex).__name__}: {ex}"
        )

    return _outcome_of(result)


def call_remote_tool(
    config: McpServerConfig,
    name: str,
    arguments: dict[str, Any],
    timeout: float,
    launch: StdioLaunch | None = None,
) -> ToolOutcome:
    """Connect to *config*, call one tool, disconnect. Never raises.

    This is the function ``agent/tools/mcp_tools.py`` closes over to build each
    adapted ``Tool``'s handler -- by the time it runs, ``agent/tools/registry.py``'s
    ``dispatch_tool`` has already gated the call; this function only performs
    the underlying protocol exchange, exactly as a built-in tool's handler in
    ``agent/tools/builtins/toolbox.py`` only performs its own I/O.
    """
    if not _sdk_available():
        return ToolOutcome(False, error=MISSING_SDK_HINT)
    import anyio

    try:
        return anyio.run(_call_tool_async, config, name, arguments, timeout, launch)
    except Exception as ex:
        return ToolOutcome(False, error=f"{type(ex).__name__}: {ex}")


# ── lifetime: hop -- one stdio session answers the hop's calls ─────────────────────────────────

_PROBE_TIMEOUT_S = 5.0
# The JSON-RPC code the SDK raises for a request on a connection whose server has gone.
_CONNECTION_CLOSED = -32000
_CLOSE_GRACE_S = 10.0

OnProcess = Callable[[str, dict[str, Any]], None]


class _Session:
    """One open stdio session: a client held open by a task on a private event loop (a blocking
    portal's thread), so the dispatching thread stays synchronous and each call is one
    ``portal.call``. The SDK's context is entered and left by that one task."""

    def __init__(self, config: McpServerConfig) -> None:
        self.config = config
        self._cm: Any = None
        self._portal: Any = None
        self._serving: concurrent.futures.Future[None] | None = None
        self._stop: Any = None
        self._client: Any = None

    async def _serve(
        self, launch: StdioLaunch | None, opened: concurrent.futures.Future[None]
    ) -> None:
        import anyio
        from mcp.client import Client
        from mcp.client.stdio import stdio_client

        self._stop = anyio.Event()
        try:
            async with Client(stdio_client(_stdio_params(self.config, launch))) as client:
                self._client = client
                opened.set_result(None)
                await self._stop.wait()
        except Exception as ex:  # spawn failure, handshake failure, jail refusal
            if not opened.done():
                opened.set_exception(ex)

    def open(self, launch: StdioLaunch | None, timeout: float) -> str:
        """Start the server and complete the handshake within *timeout*; ``""`` on success, else
        the error text (the session is then already closed)."""
        from anyio.from_thread import start_blocking_portal

        opened: concurrent.futures.Future[None] = concurrent.futures.Future()
        self._cm = start_blocking_portal()
        self._portal = self._cm.__enter__()
        self._serving = self._portal.start_task_soon(self._serve, launch, opened)
        name = self.config.name
        try:
            opened.result(timeout)
        except TimeoutError:
            self.close()
            return f"MCP server {name!r} timed out after {timeout:.0f}s"
        except Exception as ex:
            self.close()
            return f"MCP server {name!r} call failed: {type(ex).__name__}: {ex}"
        return ""

    def call(self, name: str, arguments: dict[str, Any], timeout: float) -> Any:
        import anyio

        async def _call() -> Any:
            with anyio.fail_after(timeout):
                return await self._client.call_tool(name, arguments)

        return self._portal.call(_call)

    def responds(self) -> bool:
        """Whether the server still answers: a listing that bypasses the SDK's cache is a request
        on the wire. A closed connection or a hung server does not answer; an error reply does."""
        import anyio
        from mcp.shared.exceptions import MCPError

        async def _probe() -> None:
            with anyio.fail_after(_PROBE_TIMEOUT_S):
                await self._client.list_tools(cache_mode="bypass")

        try:
            self._portal.call(_probe)
        except MCPError as ex:
            return ex.code != _CONNECTION_CLOSED
        except Exception:
            return False
        return True

    def close(self) -> None:
        """Let the serving task leave the SDK's context (which ends the server), then stop the
        loop. Never raises; a task that does not leave in time is cancelled."""
        try:
            if self._stop is not None:
                self._portal.call(self._stop.set)
            if self._serving is not None:
                self._serving.result(_CLOSE_GRACE_S)
        except Exception:
            if self._serving is not None:
                self._serving.cancel()
        finally:
            with contextlib.suppress(Exception):
                self._cm.__exit__(None, None, None)


class HopSessions:
    """The hop's open ``lifetime: hop`` sessions by server name (``ToolContext.mcp_sessions``);
    reuse, restart and close are specified in mcp-client.spec.md Requirements 42-46. Never raises."""

    def __init__(self) -> None:
        self._open: dict[str, _Session] = {}
        self._lost: set[str] = set()

    def call(
        self,
        config: McpServerConfig,
        name: str,
        arguments: dict[str, Any],
        timeout: float,
        launch: StdioLaunch | None = None,
        on_process: OnProcess | None = None,
    ) -> ToolOutcome:
        if not _sdk_available():
            return ToolOutcome(False, error=MISSING_SDK_HINT)
        try:
            return self._call(config, name, arguments, timeout, launch, on_process)
        except Exception as ex:
            return ToolOutcome(False, error=f"{type(ex).__name__}: {ex}")

    def _call(
        self,
        config: McpServerConfig,
        name: str,
        arguments: dict[str, Any],
        timeout: float,
        launch: StdioLaunch | None,
        on_process: OnProcess | None,
    ) -> ToolOutcome:
        server = config.name
        session = self._open.get(server)
        if session is not None and not session.responds():
            self._end(server, on_process, reason="died")
            session = None
        note = ""
        if session is None:
            session = _Session(config)
            error = session.open(launch, timeout)
            if error:
                return ToolOutcome(False, error=error)
            self._open[server] = session
            _report(on_process, "started", server)
            if server in self._lost:
                self._lost.discard(server)
                note = (
                    f"[MCP server {server!r} was restarted: its state from earlier calls "
                    "in this hop is gone]\n"
                )
        try:
            outcome = _outcome_of(session.call(name, arguments, timeout))
        except TimeoutError:
            self._end(server, on_process, reason="timeout")
            return ToolOutcome(False, error=f"MCP server {server!r} timed out after {timeout:.0f}s")
        except Exception as ex:
            if session.responds():
                return ToolOutcome(
                    False, error=f"MCP server {server!r} call failed: {type(ex).__name__}: {ex}"
                )
            self._end(server, on_process, reason="died")
            return ToolOutcome(
                False,
                error=f"MCP server {server!r} ended during the call; its state is gone and the "
                "next call restarts it",
            )
        if note:
            return ToolOutcome(
                outcome.ok,
                content=note + outcome.content if outcome.ok else "",
                error="" if outcome.ok else note + outcome.error,
            )
        return outcome

    def _end(self, server: str, on_process: OnProcess | None, *, reason: str) -> None:
        session = self._open.pop(server, None)
        if session is None:
            return
        session.close()
        self._lost.add(server)
        _report(on_process, "exited", server, reason=reason)

    def close_all(self, on_process: OnProcess | None, *, reason: str) -> None:
        """Close every open session, reporting each once with *reason*."""
        for server in list(self._open):
            self._end(server, on_process, reason=reason)
        self._lost.clear()


def _report(on_process: OnProcess | None, kind: str, server: str, **extra: str) -> None:
    if on_process is not None:
        on_process(kind, {"tool": "mcp", "server": server, **extra})
