"""docket start --mcp -- expose the control plane as an MCP server over stdio. Every call goes
through the same governance spine a CLI call does and audit-logs into the same tamper-evident
chain; dispatch, delegate and approvals call the exact same `core/` functions the CLI and HTTP
API call. A server, never a host. stdio discipline: tool functions never touch `docket.ui`;
stdout is reserved for JSON-RPC once the server runs. The `mcp` SDK is optional, imported lazily
in `serve_stdio()` guarded by `try/except ImportError`; a missing SDK prints `MISSING_SDK_HINT`.
The lower half of this module configures the external MCP servers docket connects to."""

from __future__ import annotations

import contextlib
import datetime as _dt
import sys
import threading
from typing import Any

import docket.config as _cfg
from docket.core import answers as _answers
from docket.core import approval as _approval
from docket.core import dispatch as _dispatch
from docket.core import interruptions as _interruptions
from docket.core import runs as _runs
from docket.core import utils as _utils
from docket.core.audit import audit_log
from docket.edges import store as _store

# mcp>=2.0.0 (see pyproject.toml's [project.optional-dependencies]) — targets
# the 2.x line's `mcp.server.MCPServer`, the decorator/`add_tool`-based server
# that replaced `mcp.server.fastmcp.FastMCP` (renamed/relocated, not
# redesigned) when the SDK's 2.0 rework removed the `fastmcp` module outright.
MISSING_SDK_HINT = (
    "The 'mcp' package is not installed — `docket start --mcp` needs the optional MCP extra.\n"
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
    "inbox",
    "cost",
    "task_answer",
    "task_pregrant",
)


class McpToolError(RuntimeError):
    """A tool's domain validation or lookup failed. Raised (never an inline
    ``{"ok": false}``) so success stays the bare shape in specs/api/mcp-server.spec.md;
    the SDK turns the exception into an ``isError`` result carrying the message."""


def _audit(tool: str, detail: str = "") -> None:
    """Write one audit-log entry for an MCP tool call, unconditionally, first thing —
    so a call is recorded even if the operation later fails. ``action`` is
    ``mcp.<tool>``; ``detail`` never carries a secret, only ids/names (audit.spec.md)."""
    audit_log(f"mcp.{tool}", detail)


# ── tool implementations (pure — no MCP SDK import; fully unit-testable) ────


def tool_status() -> dict[str, Any]:
    """Fleet-wide status snapshot: channels, every agent's
    model/registration/cost, and total recorded spend. Identical shape to
    `docket start`'s `GET /status.json` (see serve-read-api.spec.md)."""
    _audit("status")
    from docket import serve as _serve

    return _serve.build_status()


def tool_pods() -> dict[str, Any]:
    """List every provisioned pod (project) and its member roster (id, role, model)."""
    _audit("pods")
    return {"pods": _dispatch.pod_roster()}


def tool_queue(project: str, retry_task_id: str | None = None) -> dict[str, Any]:
    """Show a pod's task queue (all statuses, not just pending). If ``retry_task_id`` is
    given, first moves that one ``blocked`` task back to ``pending`` (mirrors
    `docket task retry`) — an error if it isn't currently blocked."""
    detail = f"project={project}"
    if retry_task_id:
        detail += f" retry={retry_task_id}"
    _audit("queue", detail)
    if retry_task_id and not _dispatch.retry_task(project, retry_task_id):
        raise McpToolError(f"'{retry_task_id}' is not a blocked task in pod '{project}'.")
    return {"project": project, "tasks": _dispatch.read_tasks(project)}


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
        return _dispatch.enqueue_task(project, description, priority)
    except _dispatch.DispatchError as exc:
        raise McpToolError(str(exc)) from exc


def tool_dispatch(project: str, resume: bool = False, timeout: int | None = None) -> dict[str, Any]:
    """Trigger a pod's real dispatch pipeline, gated exactly like the CLI/webhook via the
    same `core.dispatch.dispatch_pod`. Runs in a background thread; poll `runs` for the
    outcome. See specs/api/mcp-server.spec.md."""
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


def tool_approvals_grant(token: str, option: str = "") -> dict[str, Any]:
    """Grant a pending approval token. Identical to `docket task approve`/`docket start`'s
    `POST /approvals/<token>` — same `core.approval.approval_grant` call (``channel="mcp"``)
    and `core.dispatch.resolve_waiting_approval` follow-up, resuming any task it gated.
    *option* ``approve_task`` also grants the same call for the rest of its task."""
    _audit("approvals_grant", f"token={token}")
    if option not in ("", "approve_once", "approve_task"):
        raise McpToolError(f"unknown option {option!r}: use approve_once or approve_task")
    try:
        if option == "approve_task":
            _approval.approval_set_option(token, option)
        _approval.approval_grant(token, channel="mcp")
    except _approval.ApprovalNoop as exc:
        _dispatch.resolve_waiting_approval(token, "granted")
        raise McpToolError(str(exc)) from exc
    except _approval.ApprovalError as exc:
        raise McpToolError(str(exc)) from exc
    _, note = _dispatch.resolve_waiting_approval_detail(token, "granted", channel="mcp")
    rec = _approval.approval_get(token)
    return {"ok": True, "token": token, "state": rec["state"], **({"note": note} if note else {})}


def tool_approvals_deny(token: str) -> dict[str, Any]:
    """Deny a pending approval token. Identical to `docket task deny`/`docket start`'s
    `POST /approvals/<token>` — same `core.approval.approval_deny` call (``channel="mcp"``)
    and `core.dispatch.resolve_waiting_approval` follow-up, failing any task it gated."""
    _audit("approvals_deny", f"token={token}")
    try:
        _approval.approval_deny(token, channel="mcp")
    except _approval.ApprovalNoop as exc:
        _dispatch.resolve_waiting_approval(token, "denied")
        raise McpToolError(str(exc)) from exc
    except _approval.ApprovalError as exc:
        raise McpToolError(str(exc)) from exc
    _dispatch.resolve_waiting_approval(token, "denied")
    rec = _approval.approval_get(token)
    return {"ok": True, "token": token, "state": rec["state"]}


def tool_task_answer(
    project: str, task_id: str, action: str, content: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Answer a task's parked ``input`` question. Identical to `docket task answer`
    / `docket start`'s `POST /tasks/<task_id>/answer` -- same `core.answers.answer_task`
    call (``channel="mcp"``, ``actor="mcp"``)."""
    _audit("task_answer", f"project={project} task={task_id} action={action}")
    try:
        result = _answers.answer_task(project, task_id, action, content, channel="mcp", actor="mcp")
    except _answers.AnswerRejected as exc:
        raise McpToolError(f"answer blocked by policy '{exc.policy_id}'") from exc
    except _answers.AnswerError as exc:
        raise McpToolError(str(exc)) from exc
    return {"ok": True, "task": task_id, "project": project, "action": result.action}


def tool_task_pregrant(
    project: str, task_id: str, command: str, tool: str = "bash"
) -> dict[str, Any]:
    """Record a single-use pre-grant for one command on one task, ahead of dispatch.
    Identical to `docket task approve --for` / `POST /tasks/<task_id>/pregrants`."""
    _audit("task_pregrant", f"project={project} task={task_id} tool={tool}")
    try:
        token = _interruptions.record_pregrant(
            project, task_id, command, tool=tool, channel="mcp", actor="mcp"
        )
    except _interruptions.InterruptionsError as exc:
        raise McpToolError(str(exc)) from exc
    return {"ok": True, "token": token, "task": task_id, "project": project}


def tool_inbox(since: str | None = None) -> dict[str, Any]:
    """The derived operator inbox: every pod's tasks needing a human, plus pending approvals,
    failed/done/running context, and a cursor. Identical shape to `docket start`'s `GET /inbox`."""
    _audit("inbox", f"since={since or ''}")
    from docket.core import inbox as _inbox

    view = _inbox.build_inbox(now=_dt.datetime.now(_dt.UTC).isoformat(), since=since)
    return view.model_dump(by_alias=True, mode="json")


def _cost_row(agent_id: str) -> tuple[dict[str, Any], float]:
    raw = _store.read_json(_cfg.meta_path(agent_id))
    budget_raw = raw.get("budgetUsd")
    totals = _utils.aggregate_cost(agent_id)
    budget = float(budget_raw) if budget_raw and str(budget_raw) not in ("", "0") else None
    row = {
        "id": agent_id,
        "model": str(raw.get("model", _cfg.DEFAULT_MODEL)),
        "input": totals.input_tokens,
        "output": totals.output_tokens,
        "costUsd": round(totals.cost_usd, 6),
        "pricingKnown": True,
        "turns": totals.turns,
        "budgetUsd": budget,
    }
    return row, totals.cost_usd


def _cost_snapshot() -> dict[str, Any]:
    rows = [_cost_row(pid) for pid in _utils.project_ids()]
    return {"agents": [r for r, _ in rows], "totalUsd": round(sum(c for _, c in rows), 6)}


def tool_cost(agent_id: str | None = None) -> dict[str, Any]:
    """**Recorded** USD spend — one agent or the whole fleet; never a claimed dollar
    *savings* (cost-tracking.spec.md). Always ``0.0`` (``DocketDriver`` reports no real
    figure); the ``MODEL_PRICING`` estimate `docket status` shows is not returned here."""
    _audit("cost", f"agent={agent_id or ''}")
    snapshot = _cost_snapshot()
    if not agent_id:
        return snapshot
    agents: list[dict[str, Any]] = snapshot["agents"]
    for a in agents:
        if a["id"] == agent_id:
            return a
    raise McpToolError(f"Project '{agent_id}' not found.")


# ── SDK registration (only imported/executed when actually serving) ─────────


def _build_server() -> Any:
    """Construct the MCPServer instance with every tool registered. Only called from
    ``serve_stdio()`` — importing ``mcp`` at module level would make the optional
    dependency mandatory just to import ``docket.cli``."""
    from mcp.server import MCPServer

    server = MCPServer(
        name="docket",
        instructions=(
            "docket's control plane: pods, dispatch, runs, approvals, the inbox, and cost. "
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
    server.add_tool(tool_task_answer, name="task_answer")
    server.add_tool(tool_task_pregrant, name="task_pregrant")
    server.add_tool(tool_inbox, name="inbox")
    server.add_tool(tool_cost, name="cost")
    return server


def serve_stdio() -> int:
    """Run the MCP stdio server -- blocks until the client disconnects (Ctrl-C/EOF).
    Returns 1 with an actionable hint (stderr) if the ``mcp`` SDK isn't installed,
    else 0. Never prints to stdout — that is the JSON-RPC transport once running."""
    try:
        server = _build_server()
    except ImportError:
        print(MISSING_SDK_HINT, file=sys.stderr)
        return 1

    print(
        "docket start --mcp: stdio transport starting "
        f"({len(_TOOL_NAMES)} tools: {', '.join(_TOOL_NAMES)}) — Ctrl-C/EOF to stop",
        file=sys.stderr,
    )
    with contextlib.suppress(KeyboardInterrupt):
        server.run(transport="stdio")
    return 0
