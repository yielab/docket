"""The MCP setup commands.
Holds mcp."""

from __future__ import annotations

import sys

import typer


def _argv_tail_after(token: str, ctx_args: list[str]) -> list[str] | None:
    """Recover the `sys.argv` tail after `token`, trusting a candidate only when it equals
    `ctx_args` (what Click already parsed) with its first `--` dropped -- rules out a
    coincidental `token` elsewhere in argv, and returns None for a `CliRunner` call."""
    for i, tok in enumerate(sys.argv):
        if tok != token:
            continue
        tail = sys.argv[i + 1 :]
        trimmed = list(tail)
        if "--" in trimmed:
            trimmed.remove("--")
        if trimmed == ctx_args:
            return tail
    return None


def cmd_mcp(ctx: typer.Context) -> None:
    """Expose the control plane as an MCP server (`mcp serve`), or configure external MCP tool servers (`mcp servers`).

    "Rent the protocol": external tools are configuration, not code.

    Subcommands:
      serve      expose docket's own control plane as an MCP server over
                  stdio, so an external MCP client (an IDE, another agent
                  runtime) can inspect and drive the fleet through typed
                  tool calls instead of shelling out to the CLI. Requires
                  the optional [mcp] extra (`pip install 'docket[mcp]'` or
                  `uv sync --extra mcp`) -- prints an install hint to stderr
                  and exits 1 if missing. Transport: newline-delimited
                  JSON-RPC 2.0 on stdin/stdout -- no HTTP, no bind address,
                  no bearer token; the trust boundary is whoever can spawn
                  the process. Exposes 13 tools (every call audit-logged as
                  `mcp.<tool>`): status, pods, queue, delegate, dispatch,
                  runs, approvals_list, approvals_grant, approvals_deny,
                  task_answer, task_pregrant, inbox, cost -- each mirrors the
                  equivalent CLI/HTTP path through the exact same `core/` function, no
                  parallel logic, no auto-approve. `dispatch` creates a run
                  record and returns its id immediately, then runs the
                  pipeline in the background -- poll `runs` for the outcome.
      servers    list/add/remove external MCP tool servers (stdio transport)
                  so their tools become available to an agent's turn, gated
                  by the same pre_tool_call policy and dispatch_tool
                  chokepoint as any built-in -- a remote server can never
                  shadow bash/read/write/edit/glob/grep. `add <name>
                  [--env K=V ...] [--timeout S] [--kind read|write]
                  [--tools NAME,NAME,...] [--no-isolate] -- <command>
                  [args...]`: everything after `--` is passed to the server
                  verbatim as its launch command and arguments; the options
                  must come before `--`. Tools register as
                  `mcp__<name>__<tool>`. `--kind` declares the server's
                  trust level (default: write) -- a role that denies write
                  gets no tools from a server left at the default, but does
                  get tools from one declared `--kind read`, since docket's
                  role narrowing excludes by tool kind, not by name.
                  `--tools` restricts registration to a comma-separated
                  allow-list of that server's own tool names (default: all).
                  A stdio server starts inside the turn's sandbox (its
                  roots and network mode) while isolation is on;
                  `--no-isolate` is the audited assertion that it must run
                  on the host.

    Its tools are reachable from a live turn: the client namespaces them
    `mcp__<server>__<tool>`, and the turn loop folds them into the registry
    before gating and before per-role narrowing, so a Reviewer (or any role
    that denies write) never gets a write-capable MCP tool no matter what a
    configured server advertises. `docket mcp` alone prints usage and exits
    0; an unrecognized subcommand exits 1. A tool call's own success/failure
    is expressed inside the MCP protocol (isError), never as a process exit
    code. Configured servers persist in
    `~/.docket/docket-mcp-servers.json` (docket-owned JSON); env values are
    masked when listed. Every `mcp servers add`/`remove` is audit-logged.
    See specs/functional/mcp-client.spec.md and specs/api/mcp-server.spec.md."""
    from docket.cli._mcp import run_mcp

    tail = _argv_tail_after("mcp", list(ctx.args))
    args = tail if tail is not None else list(ctx.args)
    sub = args[0] if args else None
    raise typer.Exit(run_mcp(sub, args[1:]))
