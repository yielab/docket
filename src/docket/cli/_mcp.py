"""docket mcp — expose the control plane as an MCP server (stdio).

ROADMAP Phase 18 L-3. `docket mcp serve` starts an MCP (Model Context
Protocol) stdio server so any MCP client (Claude Code, Codex, ...) can drive
docket's control plane *through* the same governance spine a CLI invocation
goes through — not around it:

- every tool call writes an audit-log entry (``core/audit.py``, action
  ``mcp.<tool>``) that participates in the same ``seq``/``prev_hash``
  tamper-evidence chain as every other audit entry (Phase 15 G-4);
- ``dispatch``/``delegate``/``approvals_grant``/``approvals_deny`` call the
  *exact same* ``core/`` functions the CLI and ``docket serve``'s HTTP API
  already call — no parallel approval or dispatch path, no auto-approve, no
  shortcut around a budget/approval gate;
- this module is a transport/presentation layer only (the ``cli/`` tier), like
  ``cli/_pod.py`` or ``serve.py`` — it reuses ``core/`` services directly and
  never duplicates their business logic; ``core/`` has no idea MCP exists.

**This is a server, never a host.** `docket mcp serve` exposes docket's own
control plane as MCP tools for an external client to call. It does NOT make
docket consume/execute other MCP servers' tools inside an agent turn — that
would be the "standalone-runtime trap" the ROADMAP's Phase 18 scope guard
explicitly refuses. Agent-side MCP *client* config is a separate, deliberately
unbuilt card (L-4, daemon-gated).

**stdio discipline.** An MCP stdio server speaks newline-delimited JSON-RPC on
stdout — any stray print corrupts the stream. This module's tool functions
never touch ``docket.ui`` (which prints Rich output to stdout) and return
plain data; the one startup line ``serve_stdio()`` prints goes to stderr.

**Optional dependency.** The official ``mcp`` Python SDK is not a base
dependency (kept out of the default install so ``pip install docket`` stays
light — the SDK pulls in starlette/uvicorn/cryptography/opentelemetry and
more). It is only imported inside ``serve_stdio()``, lazily, guarded by
``try/except ImportError`` — the same pattern ``core/pipeline.py`` and
``cli/_agents.py`` already use for the optional PyYAML dependency. Install
with ``pip install 'docket[mcp]'`` (or ``uv sync --extra mcp``); a missing SDK
prints ``MISSING_SDK_HINT`` instead of a bare traceback.
"""

from __future__ import annotations

import contextlib
import sys
import threading
from typing import Any

from docket.core import approval as _approval
from docket.core import dispatch as _dispatch
from docket.core import runs as _runs
from docket.core.audit import audit_log

# mcp>=1.2.0,<2.0.0 (see pyproject.toml's [project.optional-dependencies]) —
# pinned to the 1.x line's `mcp.server.fastmcp.FastMCP` decorator-based API,
# which this module is written against; `mcp` 2.0 replaced it with a
# lower-level, callback-based `Server` API this integration does not use.
MISSING_SDK_HINT = (
    "The 'mcp' package is not installed — `docket mcp serve` needs the optional MCP extra.\n"
    "Install it with:  pip install 'docket[mcp]'\n"
    "(uv projects:      uv sync --extra mcp   or   uv pip install 'docket[mcp]')"
)

_TOOL_NAMES: tuple[str, ...] = (
    "status",
    "pods",
    "queue",
    "delegate",
    "dispatch",
    "runs",
    "approvals_list",
    "approvals_grant",
    "approvals_deny",
    "cost",
)


class McpToolError(RuntimeError):
    """A tool's domain validation or lookup failed.

    Raised instead of returning an inline ``{"ok": false, ...}`` shape so a
    successful tool's return value stays the bare data shape documented in
    ``specs/api/mcp-server.spec.md`` (matching this project's "no envelope
    wrapper" JSON convention, ``cli-interface.spec.md``). The MCP SDK turns
    any raised exception from a tool function into an ``isError`` tool result
    carrying the message — the MCP-native way to signal "this call failed".
    """


def _audit(tool: str, detail: str = "") -> None:
    """Write one audit-log entry for an MCP tool call — unconditional, first thing.

    Every tool wrapper below calls this before doing any work, so a call is
    recorded even if the underlying operation goes on to fail or raise.
    ``action`` is ``mcp.<tool>`` (a new, dedicated action family — see
    audit.spec.md); ``detail`` never carries a secret value, only ids/names,
    matching every other ``audit_log`` call site in this project.
    """
    audit_log(f"mcp.{tool}", detail)


# ── tool implementations (pure — no MCP SDK import; fully unit-testable) ────


def tool_status() -> dict[str, Any]:
    """Fleet-wide status snapshot: gateway state, channels, every agent's
    model/registration/cost, and total recorded spend. Identical shape to
    `docket serve`'s `GET /status.json` (see serve-read-api.spec.md)."""
    _audit("status")
    from docket import serve as _serve

    return _serve.build_status()


def tool_pods() -> dict[str, Any]:
    """List every provisioned pod (project) and its member roster (id, role, model)."""
    _audit("pods")
    return {"pods": _dispatch.pod_roster()}


def tool_queue(project: str, retry_task_id: str | None = None) -> dict[str, Any]:
    """Show a pod's task queue (all statuses, not just pending).

    If ``retry_task_id`` is given, first moves that one ``blocked`` task back
    to ``pending`` (mirrors `docket pod <project> queue --retry <task-id>`) —
    a no-op-turned-error if the id doesn't exist or isn't currently blocked.
    """
    detail = f"project={project}"
    if retry_task_id:
        detail += f" retry={retry_task_id}"
    _audit("queue", detail)
    if retry_task_id and not _dispatch.retry_task(project, retry_task_id):
        raise McpToolError(f"'{retry_task_id}' is not a blocked task in pod '{project}'.")
    return {"project": project, "tasks": _dispatch.read_tasks(project)}


def tool_delegate(project: str, description: str, priority: str = "normal") -> dict[str, Any]:
    """Queue a new task for a pod's Lead to work through.

    ``priority`` is ``high``/``normal``/``low`` (default ``normal``);
    ``description`` is capped at 500 chars — the same limits
    `docket pod <project> delegate` enforces. Returns the created task record.
    """
    _audit("delegate", f"project={project}")
    if not description:
        raise McpToolError("description is required")
    if len(description) > 500:
        raise McpToolError(f"Description too long ({len(description)} chars). Limit: 500.")
    if priority not in ("high", "normal", "low"):
        raise McpToolError(f"Invalid priority '{priority}'. Use: high | normal | low")
    try:
        return _dispatch.enqueue_task(project, description, priority)
    except _dispatch.DispatchError as exc:
        raise McpToolError(str(exc)) from exc


def tool_dispatch(project: str, resume: bool = False, timeout: int | None = None) -> dict[str, Any]:
    """Trigger a pod's real dispatch pipeline — one real, costed agent turn per hop.

    Gated exactly like the CLI (`docket pod <project> dispatch`) and the
    `docket serve` webhook (`POST /dispatch/<project>`): this calls the same
    `core.dispatch.dispatch_pod`, so the budget cap, verifyCmd gate, Reviewer
    verdict gate, and Tester PASS/FAIL gate all apply unchanged — there is no
    MCP-specific dispatch path. A run record (source ``"mcp"``) is created
    *before* any work starts and its id returned immediately; the pipeline
    itself runs in a background thread (this call must not block on a real
    agent turn) — poll the ``runs`` tool with the returned id for the outcome.
    ``resume`` reclaims any task left ``failed`` with a stale claim; ``timeout``
    overrides both the agent-turn and verifyCmd timeout for this run only.
    """
    _audit("dispatch", f"project={project} resume={resume} timeout={timeout}")
    if timeout is not None and timeout <= 0:
        raise McpToolError("timeout must be a positive integer number of seconds.")

    record = _runs.create_run("mcp", project)

    def _run() -> None:
        _runs.execute(
            record["id"],
            lambda: _dispatch.dispatch_pod(
                project,
                resume=resume,
                turn_timeout=timeout,
                verify_timeout=timeout,
            ),
        )

    threading.Thread(target=_run, daemon=True).start()
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


def tool_approvals_list() -> dict[str, Any]:
    """List pending HITL approvals awaiting a grant/deny decision."""
    _audit("approvals_list")
    return {"pending": _approval.list_pending()}


def tool_approvals_grant(token: str) -> dict[str, Any]:
    """Grant a pending approval token.

    Identical to `docket approve <token>` / `docket serve`'s
    `POST /approvals/<token>` (``action: "grant"``) — same
    `core.approval.approval_grant` call, tagged ``channel="mcp"`` for the
    audit trail. No MCP-side auto-approve or bypass of any kind.
    """
    _audit("approvals_grant", f"token={token}")
    try:
        _approval.approval_grant(token, channel="mcp")
    except (_approval.ApprovalNoop, _approval.ApprovalError) as exc:
        raise McpToolError(str(exc)) from exc
    rec = _approval.approval_get(token)
    return {"ok": True, "token": token, "state": rec["state"]}


def tool_approvals_deny(token: str) -> dict[str, Any]:
    """Deny a pending approval token.

    Identical to `docket deny <token>` / `docket serve`'s
    `POST /approvals/<token>` (``action: "deny"``) — same
    `core.approval.approval_deny` call, tagged ``channel="mcp"``.
    """
    _audit("approvals_deny", f"token={token}")
    try:
        _approval.approval_deny(token, channel="mcp")
    except (_approval.ApprovalNoop, _approval.ApprovalError) as exc:
        raise McpToolError(str(exc)) from exc
    rec = _approval.approval_get(token)
    return {"ok": True, "token": token, "state": rec["state"]}


def tool_cost(agent_id: str | None = None) -> dict[str, Any]:
    """Daemon-**recorded** USD spend — one agent (if ``agent_id`` is given) or
    the whole fleet. Never a projected/estimated figure and never a claimed
    dollar *savings* — see cost-tracking.spec.md."""
    _audit("cost", f"agent={agent_id or ''}")
    from docket.cli._cost import cost_snapshot

    snapshot = cost_snapshot()
    if not agent_id:
        return snapshot
    agents: list[dict[str, Any]] = snapshot["agents"]
    for a in agents:
        if a["id"] == agent_id:
            return a
    raise McpToolError(f"Project '{agent_id}' not found.")


# ── SDK registration (only imported/executed when actually serving) ─────────


def _build_server() -> Any:
    """Construct the FastMCP server instance with every tool registered.

    Only called from ``serve_stdio()`` — importing ``mcp`` at module level
    would make the optional dependency mandatory just to import
    ``docket.cli``.
    """
    from mcp.server.fastmcp import FastMCP

    server = FastMCP(
        name="docket",
        instructions=(
            "docket's control plane: pods, dispatch, runs, approvals, and cost. "
            "Every call is audit-logged; dispatch/delegate/approvals go through the "
            "exact same gates as the docket CLI — nothing here bypasses an approval "
            "or budget check."
        ),
    )

    server.add_tool(tool_status, name="status")
    server.add_tool(tool_pods, name="pods")
    server.add_tool(tool_queue, name="queue")
    server.add_tool(tool_delegate, name="delegate")
    server.add_tool(tool_dispatch, name="dispatch")
    server.add_tool(tool_runs, name="runs")
    server.add_tool(tool_approvals_list, name="approvals_list")
    server.add_tool(tool_approvals_grant, name="approvals_grant")
    server.add_tool(tool_approvals_deny, name="approvals_deny")
    server.add_tool(tool_cost, name="cost")
    return server


def serve_stdio() -> int:
    """Run `docket mcp serve` — blocks until the client disconnects (Ctrl-C/EOF).

    Returns 1 with an actionable hint (stderr) if the optional ``mcp`` SDK
    isn't installed; 0 on a clean shutdown. Never prints to stdout — that
    stream is the JSON-RPC transport once the server starts.
    """
    try:
        server = _build_server()
    except ImportError:
        print(MISSING_SDK_HINT, file=sys.stderr)
        return 1

    print(
        "docket mcp serve: stdio transport starting "
        f"({len(_TOOL_NAMES)} tools: {', '.join(_TOOL_NAMES)}) — Ctrl-C/EOF to stop",
        file=sys.stderr,
    )
    with contextlib.suppress(KeyboardInterrupt):
        server.run(transport="stdio")
    return 0


def run_mcp(sub: str | None, args: list[str]) -> int:
    """Dispatch `docket mcp <sub>`. Returns the process exit code.

    Only one subcommand exists today: ``serve``. Anything else prints usage
    to stderr (never stdout — see module docstring) and returns 1.
    """
    del args  # no flags yet; kept for the shared cli/*.py dispatch signature
    if sub == "serve":
        return serve_stdio()
    print(
        "Usage: docket mcp serve\n"
        "  Start an MCP (Model Context Protocol) stdio server exposing docket's\n"
        "  control plane as tools: " + ", ".join(_TOOL_NAMES),
        file=sys.stderr,
    )
    return 0 if sub is None else 1
