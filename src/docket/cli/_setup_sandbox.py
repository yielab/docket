"""The sandbox setup commands: isolation and network posture; the tool-call gate is always on."""

from __future__ import annotations

from enum import StrEnum

import typer

from docket import ui
from docket.cli import _contract
from docket.core import fleet as _fleet
from docket.core import security as _sec
from docket.core.audit import audit_log
from docket.edges.adapters import system as _sys

sandbox_app = typer.Typer(
    name="sandbox",
    no_args_is_help=False,
    invoke_without_command=True,
)


class NetworkMode(StrEnum):
    none = "none"
    open = "open"


def _off_label(state: str) -> str:
    return "off (explicit)" if state == "off" else state


def sandbox_state() -> dict[str, object]:
    """Isolation state, network mode and the backend found, without writing anything."""
    return {
        "gate": "always active",
        "isolation": _fleet.get_isolation_state(),
        "isolationEnabled": _fleet.get_isolation_enabled(),
        "network": _fleet.get_network_mode(),
        "backend": _sys.sandbox_availability().backend,
    }


def status(json_out: bool = False) -> int:
    """Print the gate, isolation and network posture; a read."""
    state = sandbox_state()
    if json_out:
        _contract.emit_json(state)
        return 0
    ui.header("Sandbox")
    ui.success("Tool-call gate: always active (policy engine + high-risk command classifier)")
    backend = state["backend"]
    if state["isolationEnabled"]:
        ui.success(
            f"Isolation: {state['isolation']} (backend {backend}); a turn refuses to run "
            "rather than fall back unsandboxed"
        )
    else:
        ui.warn(f"Isolation: {_off_label(str(state['isolation']))}; tools run on the host")
        ui.dim("Turn it on: docket setup sandbox on (needs bubblewrap or docker)")
    if state["network"] == "none":
        ui.success("Network: none; jailed tool calls have no network")
    else:
        ui.dim("Network: open (a pod's network none still narrows it)")
    return 0


def isolate(want: str) -> int:
    """Turn workspace isolation on or off; ``on`` needs bwrap or docker."""
    if want == "off":
        _sec.disable_workspace_isolation()
        audit_log("gates.isolate", "off")
        ui.success("Isolation off; tools run on the host")
        return 0
    avail = _sys.sandbox_availability()
    if avail.backend == "none":
        ui.error("No sandbox backend is usable", "Install bubblewrap (bwrap) or start docker")
        return 1
    _sec.apply_workspace_isolation()
    audit_log("gates.isolate", "on")
    ui.success(f"Isolation on (backend {avail.backend})")
    ui.dim("A turn with no usable backend is refused and audited, never run unsandboxed.")
    return 0


def network(want: str) -> int:
    """Record whether jailed tool calls may reach the network."""
    _fleet.set_network_mode(want)
    audit_log("gates.network", want)
    if want == "open":
        ui.success("Sandbox network open; a pod's network none still narrows it")
        return 0
    ui.success("Sandbox network none; jailed tool calls have no network")
    ui.dim("fetch runs in docket's own process and keeps its domain allowlist.")
    if not _fleet.get_isolation_enabled():
        ui.warn("Isolation is off: turns are refused until docket setup sandbox on")
    return 0


def classes() -> int:
    """List the built-in high-risk action classes."""
    ui.header("High-risk action classes")
    rows = []
    for cls in _sec.HIGH_RISK_PATTERNS:
        bins = ", ".join(cls.bins) if cls.bins else "none allowlisted; always asks"
        rows.append([cls.name, cls.description, cls.pattern, bins])
    ui.table(rows, ["CLASS", "DESCRIPTION", "PATTERN", "ALLOWLISTED BINS"])
    ui.dim("Every shell command is classified before it runs; a match asks for approval.")
    return 0


@sandbox_app.callback(invoke_without_command=True)
def sandbox_callback(
    ctx: typer.Context,
    json_out: bool = typer.Option(False, "--json", help="Emit JSON"),
) -> None:
    """Workspace isolation and sandbox network (bare: show the state).

    Example: docket setup sandbox"""
    if ctx.invoked_subcommand is None:
        raise typer.Exit(status(json_out))


@sandbox_app.command("status")
def sandbox_status(json_out: bool = typer.Option(False, "--json", help="Emit JSON")) -> None:
    """Show the gate, isolation and network posture.

    Example: docket setup sandbox status --json"""
    raise typer.Exit(status(json_out))


@sandbox_app.command("on")
def sandbox_on() -> None:
    """Run tools inside a sandbox (bwrap, else docker).

    Example: docket setup sandbox on"""
    rc = isolate("on")
    if rc == 0:
        _contract.next_step("docket setup")
    raise typer.Exit(rc)


@sandbox_app.command("off")
def sandbox_off() -> None:
    """Run tools on the host.

    Example: docket setup sandbox off"""
    rc = isolate("off")
    if rc == 0:
        _contract.next_step("docket setup")
    raise typer.Exit(rc)


@sandbox_app.command("network")
def sandbox_network(mode: NetworkMode = typer.Argument(..., help="none or open")) -> None:
    """Cut the sandbox's network (none) or leave it open.

    Example: docket setup sandbox network none"""
    rc = network(mode.value)
    _contract.next_step("docket setup sandbox")
    raise typer.Exit(rc)


@sandbox_app.command("classes")
def sandbox_classes() -> None:
    """List the high-risk action classes that always ask.

    Example: docket setup sandbox classes"""
    raise typer.Exit(classes())
