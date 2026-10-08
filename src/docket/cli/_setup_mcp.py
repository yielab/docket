"""The ``setup mcp`` group: external MCP tool servers docket connects to as a client."""

from __future__ import annotations

import typer

import docket.config as _cfg
from docket import ui
from docket.cli import _contract
from docket.core import mcp_tools as _mcp_tools
from docket.core.audit import audit_log

mcp_app = typer.Typer(
    name="mcp",
    help="External MCP tool servers: list, add and remove (stdio transport).",
    no_args_is_help=True,
)


def _parse_env(pairs: list[str]) -> dict[str, str]:
    env: dict[str, str] = {}
    for raw in pairs:
        key, sep, value = raw.partition("=")
        if not sep or not key:
            ui.error(f"--env expects KEY=VALUE, got '{raw}'")
            raise typer.Exit(1)
        env[key] = value
    return env


@mcp_app.command("list")
def cmd_list(json_out: bool = typer.Option(False, "--json", help="Emit JSON")) -> None:
    """List the configured MCP tool servers; env values are masked.

    Example: docket setup mcp list"""
    servers = _mcp_tools.load_mcp_servers()
    if json_out:
        _contract.emit_json(
            [
                {**cfg.model_dump(mode="json"), "env": dict.fromkeys(sorted(cfg.env), "****")}
                for cfg in servers
            ]
        )
        return
    if not servers:
        ui.info("No MCP servers configured.")
        return
    ui.header("MCP servers")
    rows = []
    for cfg in servers:
        env = ", ".join(f"{k}=****" for k in sorted(cfg.env)) or "-"
        rows.append(
            [
                cfg.name,
                " ".join([cfg.command, *cfg.args]),
                cfg.kind,
                ", ".join(cfg.tools) if cfg.tools else "all",
                f"{cfg.timeout:.0f}s" if cfg.timeout > 0 else "default",
                "jail" if cfg.isolate else "host",
                env,
            ]
        )
    ui.table(rows, ["NAME", "COMMAND", "KIND", "TOOLS", "TIMEOUT", "RUNS ON", "ENV"])
    ui.dim(f"  Config file: {_cfg.MCP_SERVERS_FILE}")


@mcp_app.command("add")
def cmd_add(
    name: str = typer.Argument(..., help="Server name; tools register as mcp__<name>__<tool>"),
    command: list[str] = typer.Argument(..., help="Launch command and arguments, after --"),
    env: list[str] = typer.Option([], "--env", "-e", help="KEY=VALUE for the server (repeatable)"),
    timeout: float = typer.Option(0.0, "--timeout", help="Seconds before a call gives up"),
    kind: str = typer.Option("write", "--kind", help="read or write: the server's trust level"),
    tools: str = typer.Option("", "--tools", help="Allow-list of the server's tool names"),
    no_isolate: bool = typer.Option(False, "--no-isolate", help="Start on the host, not the jail"),
) -> None:
    """Configure a server; everything after -- is its launch command, verbatim.

    A role that denies write gets tools only from a server declared --kind read.
    Example: docket setup mcp add playwright -- npx -y @playwright/mcp@latest"""
    if kind not in ("read", "write"):
        ui.error(f"--kind must be 'read' or 'write', got '{kind}'")
        raise typer.Exit(1)
    allow = [t.strip() for t in tools.split(",") if t.strip()]
    try:
        _mcp_tools.add_mcp_server(
            _mcp_tools.McpServerConfig(
                name=name,
                command=command[0],
                args=command[1:],
                env=_parse_env(env),
                timeout=timeout,
                kind=kind,  # type: ignore[arg-type]  # validated above
                tools=allow,
                isolate=not no_isolate,
            )
        )
    except ValueError as exc:
        ui.error(str(exc))
        raise typer.Exit(1) from exc
    audit_log(
        "mcp_servers.add",
        f"name={name!r} command={command[0]!r} kind={kind} isolate={'no' if no_isolate else 'yes'}",
    )
    ui.success(f"MCP server '{name}' added ({' '.join(command)}).")
    ui.dim(f"  Its tools register as mcp__{name}__<tool>, gated like a built-in tool.")
    _contract.next_step("docket setup mcp list")


@mcp_app.command("remove")
def cmd_remove(name: str = typer.Argument(..., help="Server name")) -> None:
    """Remove a configured server.

    Example: docket setup mcp remove playwright"""
    if not _mcp_tools.remove_mcp_server(name):
        ui.error(f"No MCP server named '{name}' is configured", "Run: docket setup mcp list")
        raise typer.Exit(1)
    audit_log("mcp_servers.remove", f"name={name!r}")
    ui.success(f"MCP server '{name}' removed.")
    _contract.next_step("docket setup mcp list")
