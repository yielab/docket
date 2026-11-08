"""docket start --mcp -- expose the control plane as an MCP server over stdio. Every call goes
through the same governance spine a CLI call does and audit-logs into the same tamper-evident
chain; dispatch, delegate and resolve call the exact same application functions the CLI and HTTP
API call. A server, never a host. stdio discipline: tool functions never touch `docket.interfaces.cli.render.ui`;
stdout is reserved for JSON-RPC once the server runs. The `mcp` SDK is optional, imported lazily
in `serve_stdio()` guarded by `try/except ImportError`; a missing SDK prints `MISSING_SDK_HINT`.
The lower half of this module configures the external MCP servers docket connects to."""

from __future__ import annotations

import contextlib
import functools
import sys
from collections.abc import Callable
from typing import Any

from docket.governance.audit import audit_log
from docket.hops.application import interruptions as _interruptions
from docket.hops.application import sweep as _sweep
from docket.interfaces.cli.commands import status as _status
from docket.interfaces.http.routes import health as _health
from docket.kernel import clock as _clock
from docket.kernel import threads as _threads
from docket.kernel.errors import DispatchError, DocketError, InvalidInput
from docket.operator import build_inbox, escalation_page
from docket.tasks.application import lifecycle as _lifecycle
from docket.tasks.application import queue as _queue
from docket.tasks.application import runs as _runs
from docket.tasks.application.escalations import resolve
from docket.tasks.application.repository import TaskRepository

# mcp>=2.0.0 (see pyproject.toml's [project.optional-dependencies]) — targets
# the 2.x line's `mcp.server.MCPServer`, the decorator/`add_tool`-based server
# that replaced `mcp.server.fastmcp.FastMCP` (renamed/relocated, not
# redesigned) when the SDK's 2.0 rework removed the `fastmcp` module outright.
MISSING_SDK_HINT = (
    "The 'mcp' package is not installed — `docket start --mcp` needs the optional MCP extra.\n"
    "Install it with:  pip install 'docket[mcp]'\n"
    "(uv projects:      uv sync --extra mcp   or   uv pip install 'docket[mcp]')"
)


class McpToolError(InvalidInput):
    """A tool's domain validation or lookup failed. Raised so success stays the bare shape in
    specs/api/mcp-server.spec.md; ``_build_server`` re-raises it as the SDK's ``ToolError``, the
    one exception whose message reaches the client."""


def _audit(tool: str, detail: str = "") -> None:
    """Write one audit-log entry for an MCP tool call, unconditionally, first thing —
    so a call is recorded even if the operation later fails. ``action`` is
    ``mcp.<tool>``; ``detail`` never carries a secret, only ids/names (audit.spec.md)."""
    audit_log(f"mcp.{tool}", detail)


# ── tool implementations (pure — no MCP SDK import; fully unit-testable) ────


def tool_status() -> dict[str, Any]:
    """Fleet-wide status snapshot: channels, every agent's
    model/registration. Identical shape to
    `docket start`'s `GET /status.json` (see serve-read-api.spec.md)."""
    _audit("status")

    return _health.build_status()


def tool_pods() -> dict[str, Any]:
    """List every provisioned pod (project) and its member roster (id, role, model)."""
    _audit("pods")
    return {"pods": _queue.pod_roster()}


def _queue_dump(project: str) -> dict[str, Any]:
    records = TaskRepository.for_pod(project).list()
    return {
        "project": project,
        "tasks": [r.model_dump(by_alias=True, mode="json") for r in records],
    }


def tool_queue(project: str) -> dict[str, Any]:
    """Show a pod's task queue (all statuses, not just pending). Read-only."""
    _audit("queue", f"project={project}")
    return _queue_dump(project)


def tool_retry(project: str, task_id: str) -> dict[str, Any]:
    """Move one ``blocked`` or ``failed`` task back to ``pending`` (mirrors
    `docket task retry`) -- an error if it is in any other status. Returns the pod's queue."""
    _audit("retry", f"project={project} task={task_id}")
    if not _lifecycle.retry_task(project, task_id):
        raise McpToolError(f"'{task_id}' is not a failed or blocked task in pod '{project}'.")
    return _queue_dump(project)


def tool_delegate(project: str, description: str, priority: str = "normal") -> dict[str, Any]:
    """Queue a new task for a pod's Lead. ``priority`` is high/normal/low (default
    normal); ``description`` is capped at 500 chars — the same limits
    `docket task add` enforces. Returns the created task record."""
    _audit("delegate", f"project={project}")
    if not description:
        raise McpToolError("description is required")
    if len(description) > 500:
        raise McpToolError(f"Description too long ({len(description)} chars). Limit: 500.")
    if priority not in ("high", "normal", "low"):
        raise McpToolError(f"Invalid priority '{priority}'. Use: high | normal | low")
    try:
        task, _created = _queue.enqueue_task_once(project, description, priority, channel="mcp")
    except DispatchError as exc:
        raise McpToolError(str(exc)) from exc
    return task.model_dump(by_alias=True, mode="json")


def tool_dispatch(project: str, resume: bool = False, timeout: int | None = None) -> dict[str, Any]:
    """Trigger a pod's real dispatch pipeline, gated exactly like the CLI/webhook via the
    same `hops.application.sweep.dispatch_pod`. Runs in a background thread; poll `runs` for the
    outcome. See specs/api/mcp-server.spec.md."""
    _audit("dispatch", f"project={project} resume={resume} timeout={timeout}")
    if timeout is not None and timeout <= 0:
        raise McpToolError("timeout must be a positive integer number of seconds.")

    record = _runs.create_run("mcp", project)

    def _run() -> None:
        _runs.execute(
            record["id"],
            lambda: _sweep.dispatch_pod(
                project,
                resume=resume,
                turn_timeout=timeout,
                verify_timeout=timeout,
            ),
        )

    _threads.start_thread(_run)
    return {"ok": True, "run": record["id"], "project": project, "status": "dispatched"}


def tool_runs(project: str | None = None, run_id: str | None = None) -> dict[str, Any]:
    """List dispatch run records newest-first (optionally filtered to one
    project), or fetch a single record by ``run_id``."""
    _audit("runs", f"project={project or ''} id={run_id or ''}")
    if run_id:
        rec = _runs.get_run(run_id)
        if rec is None:
            raise McpToolError(f"Unknown run: {run_id}")
        return rec
    return {"runs": _runs.list_runs(project)}


def tool_resolve(
    escalation_id: str, option_id: str | None = None, content: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Settle one escalation: choose one of its options and give content. Identical to
    `POST /escalations/<id>` -- the same `resolve` (``channel="mcp"``, ``by="mcp"``) every
    surface calls."""
    _audit("resolve", f"escalation={escalation_id}")
    try:
        resolved = resolve(escalation_id, option_id, content, by="mcp", channel="mcp")
    except DocketError as exc:
        raise McpToolError(exc.message) from exc
    return {
        "ok": True,
        "escalation": resolved.escalation.id,
        "state": "resolved",
        **({"note": resolved.note} if resolved.note else {}),
    }


def tool_task_pregrant(
    project: str, task_id: str, command: str, tool: str = "bash"
) -> dict[str, Any]:
    """Record a single-use pre-grant for one command on one task, ahead of dispatch.
    Identical to `docket task pregrant` / `POST /tasks/<task_id>/pregrants`."""
    _audit("task_pregrant", f"project={project} task={task_id} tool={tool}")
    try:
        token = _interruptions.record_pregrant(
            project, task_id, command, tool=tool, channel="mcp", actor="mcp"
        )
    except _interruptions.InterruptionsError as exc:
        raise McpToolError(str(exc)) from exc
    return {"ok": True, "token": token, "task": task_id, "project": project}


def tool_inbox(since: str | None = None) -> dict[str, Any]:
    """The derived operator inbox: every pod's tasks needing a human, plus pending escalations,
    failed/done/running context, and a cursor. Identical shape to `docket start`'s `GET /inbox`."""
    _audit("inbox", f"since={since or ''}")

    view = build_inbox(now=_clock.iso(), since=since)
    return view.model_dump(by_alias=True, mode="json")


def tool_escalations(since: int | None = None) -> dict[str, Any]:
    """The escalation records after a cursor, each joined with the pause it names: identical to
    `docket start`'s `GET /escalations`. *since* is the `seq` to read after."""
    _audit("escalations", f"since={since if since is not None else ''}")
    page = escalation_page(since_seq=since)
    return page.model_dump(by_alias=True, mode="json")


def tool_usage(agent_id: str | None = None) -> dict[str, Any]:
    """**Measured** token usage — one agent or the whole fleet; docket returns no dollar figure
    (cost-tracking.spec.md)."""
    _audit("usage", f"agent={agent_id or ''}")
    snapshot = _status.usage_snapshot()
    if not agent_id:
        return snapshot
    agents: list[dict[str, Any]] = snapshot["agents"]
    for a in agents:
        if a["id"] == agent_id:
            return a
    raise McpToolError(f"Project '{agent_id}' not found.")


# Each tool by name, with whether it only reads: the read tools come first, and a read-only server
# registers those alone.
_TOOLS: dict[str, tuple[Callable[..., Any], bool]] = {
    "status": (tool_status, True),
    "pods": (tool_pods, True),
    "queue": (tool_queue, True),
    "runs": (tool_runs, True),
    "inbox": (tool_inbox, True),
    "escalations": (tool_escalations, True),
    "usage": (tool_usage, True),
    "delegate": (tool_delegate, False),
    "dispatch": (tool_dispatch, False),
    "retry": (tool_retry, False),
    "resolve": (tool_resolve, False),
    "task_pregrant": (tool_task_pregrant, False),
}


def tool_names(read_only: bool = False) -> tuple[str, ...]:
    """The names a server registers: the read tools alone when ``read_only``, else all."""
    return tuple(name for name, (_fn, reads) in _TOOLS.items() if reads or not read_only)


# ── SDK registration (only imported/executed when actually serving) ─────────


def _build_server(read_only: bool = False) -> Any:
    """Construct the MCPServer instance with its tools registered: every tool, or only the read
    tools when ``read_only``. Only called from ``serve_stdio()`` -- importing ``mcp`` at
    module level would make the optional dependency mandatory just to import ``docket.cli``."""
    from mcp.server import MCPServer
    from mcp.server.mcpserver.exceptions import ToolError

    def expected(fn: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(fn)
        def call(*args: Any, **kwargs: Any) -> Any:
            try:
                return fn(*args, **kwargs)
            except McpToolError as exc:
                raise ToolError(str(exc)) from exc

        return call

    if read_only:
        instructions = (
            "docket's control plane, read-only: pods, runs, escalations, the inbox, and token usage. "
            "Every call is audit-logged. This server cannot delegate, dispatch, retry or resolve."
        )
    else:
        instructions = (
            "docket's control plane: pods, dispatch, runs, escalations, the inbox, and token usage. "
            "Every call is audit-logged; dispatch/delegate/retry/resolve go through the "
            "exact same gates as the docket CLI -- nothing here bypasses an approval "
            "or budget check."
        )
    server = MCPServer(name="docket", instructions=instructions)

    for name in tool_names(read_only):
        server.add_tool(expected(_TOOLS[name][0]), name=name)
    return server


def serve_stdio(read_only: bool = False) -> int:
    """Run the MCP stdio server -- blocks until the client disconnects (Ctrl-C/EOF).
    ``read_only`` registers only the read tools. Returns 1 with an actionable hint (stderr) if the ``mcp`` SDK isn't installed,
    else 0. Never prints to stdout — that is the JSON-RPC transport once running."""
    try:
        server = _build_server(read_only)
    except ImportError:
        print(MISSING_SDK_HINT, file=sys.stderr)
        return 1

    names = tool_names(read_only)
    print(
        "docket start --mcp: stdio transport starting "
        f"({len(names)} tools: {', '.join(names)}) — Ctrl-C/EOF to stop",
        file=sys.stderr,
    )
    with contextlib.suppress(KeyboardInterrupt):
        server.run(transport="stdio")
    return 0
