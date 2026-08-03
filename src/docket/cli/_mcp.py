"""docket mcp — expose the control plane as an MCP server, or configure the
external MCP tool servers docket connects to as a *client*.

This module has two, deliberately unrelated halves:

- `docket mcp serve` (ROADMAP Phase 18 L-3): docket **as a server** — starts
  an MCP (Model Context Protocol) stdio server so any MCP client (Claude
  Code, Codex, ...) can drive docket's control plane *through* the same
  governance spine a CLI invocation goes through — not around it.
- `docket mcp servers add/list/remove` (ROADMAP Phase 19 P19-13): docket **as
  a client** — the CLI over `core/mcp_tools.py`'s `add_mcp_server`/
  `load_mcp_servers`/`remove_mcp_server` (P19-10), which shipped as tested,
  uncalled library functions. This half is pure presentation: it validates
  flags, builds an `McpServerConfig`, and calls the existing `core/`
  functions — it does not talk to a remote server itself (that happens later,
  when `core/agent_loop.py`, P19-5, calls `load_mcp_tools` to build a turn's
  registry) and it never touches `core/tools.py`.

**The payoff this CLI exists to unlock: browser support is configuration, not
code.** Point docket at the Playwright MCP server
(`docket mcp servers add playwright -- npx -y @playwright/mcp@latest`) and
P19-10's client gates every tool it advertises exactly like a built-in —
namespaced `mcp__playwright__<tool>`, so a remote server can never shadow
`bash`, still screened through the `prompt-injection` policy before
registration, still dispatched through the one chokepoint. The same is true
of a web-search MCP server. This is what decision D-19's "rent the protocol"
buys, and it is precisely why hand-rolling browser automation or a search
tool is on the never-build list (decision D-24) — see the recipe in
`specs/functional/mcp-client.spec.md`.

The `serve` half's own docstring below (unchanged from L-3) continues to
describe only that half:

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

**SDK version (Phase 18 L-6).** Targets the SDK's 2.x line (``mcp>=2.0.0``,
no ceiling) via ``mcp.server.MCPServer`` — the 2.0 rework's direct successor
to the 1.x line's ``mcp.server.fastmcp.FastMCP`` (``mcp.server.fastmcp`` was
removed outright in 2.0, not deprecated in place). The migration was a rename,
not a redesign: ``MCPServer`` keeps the same ergonomics this module already
used — ``MCPServer(name=..., instructions=...)``, ``add_tool(fn, name=...)``,
and ``server.run(transport="stdio")`` — confirmed by reading the installed
2.0.0 package directly (``mcp/server/mcpserver/server.py``), not assumed.
"""

from __future__ import annotations

import contextlib
import sys
import threading
from typing import Any

import docket.config as _cfg
from docket.core import approval as _approval
from docket.core import dispatch as _dispatch
from docket.core import mcp_tools as _mcp_tools
from docket.core import runs as _runs
from docket.core.audit import audit_log

# mcp>=2.0.0 (see pyproject.toml's [project.optional-dependencies]) — targets
# the 2.x line's `mcp.server.MCPServer`, the decorator/`add_tool`-based server
# that replaced `mcp.server.fastmcp.FastMCP` (renamed/relocated, not
# redesigned) when the SDK's 2.0 rework removed the `fastmcp` module outright.
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
    """Construct the MCPServer instance with every tool registered.

    Only called from ``serve_stdio()`` — importing ``mcp`` at module level
    would make the optional dependency mandatory just to import
    ``docket.cli``.
    """
    from mcp.server import MCPServer

    server = MCPServer(
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


# ── `docket mcp servers` — CLI over core/mcp_tools.py's client config (P19-13) ──
#
# Pure presentation: every function below validates input, builds/reads
# McpServerConfig objects, and calls the existing core/mcp_tools.py functions
# (add_mcp_server/load_mcp_servers/remove_mcp_server) unchanged. Nothing here
# connects to a server or touches core/tools.py — that happens later, when
# core/agent_loop.py (P19-5) calls load_mcp_tools to build a turn's registry.
#
# Deliberately plain print(), never docket.ui: this file also hosts
# serve_stdio()'s JSON-RPC session, and test_l6_mcp_sdk_v2.py's
# TestNoUiImportEvenWithTheSdkInstalled pins "cli/_mcp.py never imports
# docket.ui" at the whole-module level (simpler to guarantee than "only when
# a JSON-RPC session isn't live"). These helpers keep the same glyphs
# ui.py's success/warn/error/info use, without the Rich dependency.


def _pinfo(text: str) -> None:
    print(f"→ {text}")


def _pok(text: str) -> None:
    print(f"✓ {text}")


def _pwarn(text: str) -> None:
    print(f"⚠ {text}")


def _perror(text: str) -> None:
    print(f"✗ Error: {text}", file=sys.stderr)


_SERVERS_USAGE = """\
Usage: docket mcp servers <list|add|remove> [args...]

  list                                        Show configured MCP tool servers
  add <name> [--env KEY=VALUE ...] [--timeout SECONDS] -- <command> [args...]
                                               Configure a new server (stdio transport)
  remove <name>                               Remove a configured server

Everything after "--" is passed to the server verbatim as its launch command
and arguments; --env/--timeout must come before "--".

Example — browser automation as configuration, not code (see
specs/functional/mcp-client.spec.md's "Recipe" section):
  docket mcp servers add playwright -- npx -y @playwright/mcp@latest

Its tools then register as mcp__playwright__<tool> and are gated by the same
pre_tool_call policy and dispatch_tool chokepoint as any built-in tool — a
remote server can never shadow bash/read/write/edit/glob/grep.
"""


def _servers_list() -> int:
    servers = _mcp_tools.load_mcp_servers()
    if not servers:
        _pinfo("No MCP servers configured.")
        print("  Add one: docket mcp servers add <name> -- <command> [args...]")
        return 0

    print("\nConfigured MCP Servers\n")
    for cfg in servers:
        cmdline = " ".join([cfg.command, *cfg.args])
        print(f"  {cfg.name}  {cmdline}")
        if cfg.env:
            masked = ", ".join(f"{k}=****" for k in sorted(cfg.env))
            print(f"      env: {masked}")
        timeout_note = f"{cfg.timeout:.0f}s (pinned)" if cfg.timeout > 0 else "default"
        print(f"      timeout: {timeout_note}")
    print(f"\n  Config file: {_cfg.MCP_SERVERS_FILE}")
    return 0


def _parse_server_add_flags(
    flags: list[str],
) -> tuple[dict[str, str], float] | None:
    """Parse the ``--env KEY=VALUE`` / ``--timeout SECONDS`` flags that may
    precede the ``--`` separator in ``docket mcp servers add``. Returns
    ``None`` (after printing an error) on any malformed flag."""
    env: dict[str, str] = {}
    timeout = 0.0
    i = 0
    while i < len(flags):
        tok = flags[i]
        if tok in ("--env", "-e") and i + 1 < len(flags):
            raw, i = flags[i + 1], i + 2
        elif tok.startswith("--env="):
            raw, i = tok[len("--env=") :], i + 1
        elif tok == "--timeout" and i + 1 < len(flags):
            try:
                timeout = float(flags[i + 1])
            except ValueError:
                _perror(f"--timeout must be a number of seconds, got '{flags[i + 1]}'")
                return None
            i += 2
            continue
        elif tok.startswith("--timeout="):
            value = tok[len("--timeout=") :]
            try:
                timeout = float(value)
            except ValueError:
                _perror(f"--timeout must be a number of seconds, got '{value}'")
                return None
            i += 1
            continue
        else:
            _perror(f"Unknown flag '{tok}' before '--'. See: docket mcp servers")
            return None

        if "=" not in raw:
            _perror(f"--env expects KEY=VALUE, got '{raw}'")
            return None
        key, _, value = raw.partition("=")
        if not key:
            _perror(f"--env expects KEY=VALUE, got '{raw}'")
            return None
        env[key] = value
    return env, timeout


def _servers_add(rest: list[str]) -> int:
    if not rest:
        _perror(
            "Usage: docket mcp servers add <name> [--env K=V ...] [--timeout S] -- <command> [args...]"
        )
        return 1

    name, tail = rest[0], rest[1:]
    if "--" not in tail:
        _perror(
            "Missing '--' separator before the server's launch command.\n"
            "  Usage: docket mcp servers add <name> [--env K=V ...] [--timeout S] -- <command> [args...]\n"
            "  Example: docket mcp servers add playwright -- npx -y @playwright/mcp@latest"
        )
        return 1

    sep = tail.index("--")
    flags, command_parts = tail[:sep], tail[sep + 1 :]
    if not command_parts:
        _perror("No command given after '--'.")
        return 1

    parsed = _parse_server_add_flags(flags)
    if parsed is None:
        return 1
    env, timeout = parsed
    command, command_args = command_parts[0], command_parts[1:]

    try:
        _mcp_tools.add_mcp_server(
            _mcp_tools.McpServerConfig(
                name=name, command=command, args=command_args, env=env, timeout=timeout
            )
        )
    except ValueError as exc:
        _perror(str(exc))
        return 1

    audit_log("mcp_servers.add", f"name={name!r} command={command!r}")
    cmdline = " ".join([command, *command_args])
    _pok(f"MCP server '{name}' added ({cmdline}).")
    print(f"  Its tools register as mcp__{name}__<tool> — gated exactly like a built-in tool.")
    return 0


def _servers_remove(rest: list[str]) -> int:
    if not rest:
        _perror("Usage: docket mcp servers remove <name>")
        return 1
    name = rest[0]
    if not _mcp_tools.remove_mcp_server(name):
        _pwarn(f"No MCP server named '{name}' is configured.")
        return 1
    audit_log("mcp_servers.remove", f"name={name!r}")
    _pok(f"MCP server '{name}' removed.")
    return 0


def _run_servers(sub2: str | None, rest: list[str]) -> int:
    if sub2 == "list":
        return _servers_list()
    if sub2 == "add":
        return _servers_add(rest)
    if sub2 == "remove":
        return _servers_remove(rest)
    print(_SERVERS_USAGE, file=sys.stderr if sub2 is not None else sys.stdout, end="")
    return 0 if sub2 is None else 1


def run_mcp(sub: str | None, args: list[str]) -> int:
    """Dispatch `docket mcp <sub>`. Returns the process exit code.

    Two subcommands: ``serve`` (docket as an MCP server) and ``servers``
    (manage the external MCP servers docket connects to as a client — see
    ``_run_servers`` above). Anything else prints usage to stderr (never
    stdout — see module docstring's stdio-discipline note, which applies once
    ``serve`` is actually running) and returns 1.
    """
    if sub == "serve":
        del args  # no flags yet for serve
        return serve_stdio()
    if sub == "servers":
        sub2 = args[0] if args else None
        return _run_servers(sub2, args[1:])
    print(
        "Usage: docket mcp <serve|servers>\n"
        "  docket mcp serve                     Start an MCP (Model Context Protocol) stdio\n"
        "                                        server exposing docket's control plane as\n"
        "                                        tools: " + ", ".join(_TOOL_NAMES) + "\n"
        "  docket mcp servers <list|add|remove>  Manage external MCP tool servers docket\n"
        "                                        connects to as a client (see: docket mcp servers)",
        file=sys.stderr,
    )
    return 0 if sub is None else 1
