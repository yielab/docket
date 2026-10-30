"""The ``setup mcp`` group: external MCP tool servers docket connects to as a client."""

from __future__ import annotations

import typer

from docket.governance.audit import audit_log
from docket.interfaces.cli.commands import contract as _contract
from docket.interfaces.cli.render import ui
from docket.kernel import mcp as _mcp
from docket.kernel.home import current_home
from docket.teams import mcp_servers as _mcp_servers

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
    servers = _mcp_servers.load_mcp_servers()
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
                env,
            ]
        )
    ui.table(rows, ["NAME", "COMMAND", "KIND", "TOOLS", "TIMEOUT", "ENV"])
    ui.dim(f"  Config file: {current_home().mcp_servers_file}")


@mcp_app.command("add")
def cmd_add(
    name: str = typer.Argument(..., help="Server name; tools register as mcp__<name>__<tool>"),
    command: list[str] = typer.Argument(..., help="Launch command and arguments, after --"),
    env: list[str] = typer.Option([], "--env", "-e", help="KEY=VALUE for the server (repeatable)"),
    timeout: float = typer.Option(0.0, "--timeout", help="Seconds before a call gives up"),
    kind: str = typer.Option("write", "--kind", help="read or write: the server's trust level"),
    tools: str = typer.Option("", "--tools", help="Allow-list of the server's tool names"),
    lifetime: str = typer.Option(
        "call", "--lifetime", help="call: a process per call; hop: one session per hop"
    ),
) -> None:
    """Configure a server; everything after -- is its launch command, verbatim.

    A role that denies write gets tools only from a server declared --kind read.
    A server that keeps state between calls (a browser) wants --lifetime hop.
    Example: docket setup mcp add playwright --lifetime hop -- npx -y @playwright/mcp@latest"""
    if kind not in ("read", "write"):
        ui.error(f"--kind must be 'read' or 'write', got '{kind}'")
        raise typer.Exit(1)
    if lifetime not in ("call", "hop"):
        ui.error(f"--lifetime must be 'call' or 'hop', got '{lifetime}'")
        raise typer.Exit(1)
    allow = [t.strip() for t in tools.split(",") if t.strip()]
    try:
        _mcp_servers.add_mcp_server(
            _mcp.McpServerConfig(
                name=name,
                command=command[0],
                args=command[1:],
                env=_parse_env(env),
                timeout=timeout,
                kind=kind,  # type: ignore[arg-type]  # validated above
                tools=allow,
                lifetime=lifetime,  # type: ignore[arg-type]  # validated above
            )
        )
    except ValueError as exc:
        ui.error(str(exc))
        raise typer.Exit(1) from exc
    audit_log(
        "mcp_servers.add",
        f"name={name!r} command={command[0]!r} kind={kind}"
        + (f" lifetime={lifetime}" if lifetime != "call" else ""),
    )
    ui.success(f"MCP server '{name}' added ({' '.join(command)}).")
    ui.dim(f"  Its tools register as mcp__{name}__<tool>, gated like a built-in tool.")
    _contract.next_step("docket setup mcp list")


@mcp_app.command("remove")
def cmd_remove(name: str = typer.Argument(..., help="Server name")) -> None:
    """Remove a configured server.

    Example: docket setup mcp remove playwright"""
    if not _mcp_servers.remove_mcp_server(name):
        ui.error(f"No MCP server named '{name}' is configured", "Run: docket setup mcp list")
        raise typer.Exit(1)
    audit_log("mcp_servers.remove", f"name={name!r}")
    ui.success(f"MCP server '{name}' removed.")
    _contract.next_step("docket setup mcp list")
