"""MCP client adapter (ROADMAP Phase 19 P19-10 / D-19).

The one shipped implementation of ``core/mcp_tools.py``'s two-function port
(``ListToolsFn``/``CallToolFn``) -- the only module in docket that knows the
MCP wire protocol exists, or that a subprocess is involved at all. Mirrors
``edges/adapters/llm.py``'s split: the port's pure types live in ``core/``,
every protocol/SDK-specific detail lives here.

**Subprocess-per-exchange, on purpose.** Each public function here spawns a
fresh stdio subprocess for exactly one exchange (list the tool catalog, or
call one tool) and tears it down again -- no connection is kept open between
calls. That costs a little latency in exchange for real isolation: a
misbehaving server cannot corrupt a *stateful* connection some later,
unrelated call would otherwise inherit, and a killed/hung server cannot leak
past its own bounded timeout into anything else docket is doing. Every
exchange is wrapped in ``anyio.fail_after``, so an unresponsive server is
cancelled and reported as unavailable rather than left to block a turn.

**Optional dependency.** The official ``mcp`` SDK (``docket[mcp]``, see
``pyproject.toml``) is not a base dependency. Both public functions probe for
it and import it lazily, guarded by ``try``/``except ImportError`` -- the same
pattern ``cli/_mcp.py`` already uses on the server side. A missing SDK comes
back as ordinary data (``MISSING_SDK_HINT`` in the result's ``error``), never
a bare traceback.

**Never raises.** A bad server, a missing SDK, a timeout, or a malformed
response all come back as an ordinary failed result. ``core/mcp_tools.py``'s
``load_mcp_tools`` and, for a call, ``core/tools.py``'s ``dispatch_tool`` (via
the ``Tool.handler`` built from this module's ``call_remote_tool``) both
expect "the server is unavailable" to be data, not an exception that unwinds
a turn.
"""

from __future__ import annotations

from typing import Any

from docket.core.mcp_tools import McpListResult, McpRemoteTool, McpServerConfig
from docket.edges.adapters.toolbox import ToolOutcome

MISSING_SDK_HINT = (
    "The 'mcp' package is not installed -- an MCP tool server needs the optional MCP extra.\n"
    "Install it with:  pip install 'docket[mcp]'\n"
    "(uv projects:      uv sync --extra mcp   or   uv pip install 'docket[mcp]')"
)

# A remote tool's output is fed straight into a model's context, exactly like
# a built-in tool's (see edges/adapters/toolbox.py's own MAX_OUTPUT_CHARS) --
# an unbounded result from an external server is a context-budget failure
# waiting to happen, and nothing upstream of this module would catch it.
MAX_OUTPUT_CHARS = 30_000


def _sdk_available() -> bool:
    """True when the optional MCP client stack can actually be imported."""
    try:
        import anyio  # noqa: F401
        import mcp.client.stdio  # noqa: F401
    except ImportError:
        return False
    return True


def _truncate(text: str) -> str:
    if len(text) <= MAX_OUTPUT_CHARS:
        return text
    dropped = len(text) - MAX_OUTPUT_CHARS
    return f"{text[:MAX_OUTPUT_CHARS]}\n\n[truncated: {dropped} more characters]"


def _stdio_params(config: McpServerConfig) -> Any:
    """Build the SDK's spawn parameters for *config*. Imported lazily -- this
    is only ever called after ``_sdk_available()`` has already confirmed the
    SDK is importable."""
    from mcp.client.stdio import StdioServerParameters

    return StdioServerParameters(
        command=config.command,
        args=list(config.args),
        env=dict(config.env) or None,
    )


async def _list_tools_async(config: McpServerConfig, timeout: float) -> McpListResult:
    import anyio
    from mcp.client import Client
    from mcp.client.stdio import stdio_client

    try:
        with anyio.fail_after(timeout):
            async with Client(stdio_client(_stdio_params(config))) as client:
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


def list_remote_tools(config: McpServerConfig, timeout: float) -> McpListResult:
    """Connect to *config*, list its tools, disconnect. Never raises.

    *timeout* bounds the whole exchange (spawn + handshake + list +
    teardown) -- a server that never answers is cancelled, not awaited
    forever.
    """
    if not _sdk_available():
        return McpListResult(ok=False, error=MISSING_SDK_HINT)
    import anyio

    try:
        return anyio.run(_list_tools_async, config, timeout)
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


async def _call_tool_async(
    config: McpServerConfig, name: str, arguments: dict[str, Any], timeout: float
) -> ToolOutcome:
    import anyio
    from mcp.client import Client
    from mcp.client.stdio import stdio_client

    try:
        with anyio.fail_after(timeout):
            async with Client(stdio_client(_stdio_params(config))) as client:
                result = await client.call_tool(name, arguments)
    except TimeoutError:
        return ToolOutcome(
            False, error=f"MCP server {config.name!r} timed out after {timeout:.0f}s"
        )
    except Exception as ex:
        return ToolOutcome(
            False, error=f"MCP server {config.name!r} call failed: {type(ex).__name__}: {ex}"
        )

    text = _truncate(_render_content(result))
    if getattr(result, "is_error", False):
        return ToolOutcome(False, error=text or "tool reported an error")
    return ToolOutcome(True, content=text)


def call_remote_tool(
    config: McpServerConfig, name: str, arguments: dict[str, Any], timeout: float
) -> ToolOutcome:
    """Connect to *config*, call one tool, disconnect. Never raises.

    This is the function ``core/mcp_tools.py`` closes over to build each
    adapted ``Tool``'s handler -- by the time it runs, ``core/tools.py``'s
    ``dispatch_tool`` has already gated the call; this function only performs
    the underlying protocol exchange, exactly as a built-in tool's handler in
    ``edges/adapters/toolbox.py`` only performs its own I/O.
    """
    if not _sdk_available():
        return ToolOutcome(False, error=MISSING_SDK_HINT)
    import anyio

    try:
        return anyio.run(_call_tool_async, config, name, arguments, timeout)
    except Exception as ex:
        return ToolOutcome(False, error=f"{type(ex).__name__}: {ex}")
