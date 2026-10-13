"""The sandbox setup commands: isolation and network posture; the tool-call gate is always on."""

from __future__ import annotations

import platform
import re
import sys
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


_MISSING = {
    "linux": "Linux: a kernel with Landlock (>= 5.13)",
    "macos": "macOS: /usr/bin/sandbox-exec (ships with the OS)",
    "windows": "Windows: use WSL2; native runs without a sandbox",
    "other": "no sandbox backend exists for this platform",
}
_NOT_AVAILABLE = {
    "linux": "not available: Linux needs a kernel with Landlock (5.13 or newer).",
    "macos": "not available: macOS needs /usr/bin/sandbox-exec, which ships with the OS.",
    "windows": "not available on native Windows; use WSL2.",
    "other": "not available: no sandbox backend exists for this platform.",
}


def _platform_name() -> str:
    if sys.platform.startswith("linux"):
        return "linux"
    if sys.platform == "darwin":
        return "macos"
    if sys.platform in ("win32", "cygwin"):
        return "windows"
    return "other"


def _kernel() -> str | None:
    found = re.match(r"(\d+\.\d+)", platform.release())
    return found.group(1) if found else None


def _available(avail: _sys.SandboxAvailability) -> list[str]:
    return [
        name for name, ok in (("landlock", avail.landlock), ("seatbelt", avail.seatbelt)) if ok
    ] + (["docker"] if avail.docker else [])


def sandbox_lines() -> list[str]:
    """The ``Sandbox`` posture as printed by init, status and setup sandbox: line, then hint."""
    backend = _sys.sandbox_availability().backend
    plat = _platform_name()
    if _fleet.get_isolation_enabled():
        if backend == "none":
            return [f"Sandbox   on, but no backend is usable; turns are refused. {_MISSING[plat]}"]
        return [f"Sandbox   on ({backend}, network {_fleet.get_network_mode()})"]
    if backend == "none":
        return [f"Sandbox   {_NOT_AVAILABLE[plat]}"]
    return [
        "Sandbox   off. The agent's commands run with your user's permissions.",
        "          Turn it on: docket setup sandbox on",
    ]


def print_sandbox_block() -> None:
    """Print the ``Sandbox`` lines plain, so every command shows them the same way."""
    for line in sandbox_lines():
        ui.console.print(line, markup=False, highlight=False)


def sandbox_state() -> dict[str, object]:
    """Isolation state, network mode and the per-platform probe, without writing anything."""
    avail = _sys.sandbox_availability()
    plat = _platform_name()
    lines = sandbox_lines()
    return {
        "gate": "always active",
        "isolation": _fleet.get_isolation_state(),
        "isolationEnabled": _fleet.get_isolation_enabled(),
        "network": _fleet.get_network_mode(),
        "backend": avail.backend,
        "platform": plat,
        "kernel": _kernel() if avail.landlock else None,
        "available": _available(avail),
        "missing": _MISSING[plat] if avail.backend == "none" else None,
        "line": lines[0],
        "hint": lines[1].strip() if len(lines) > 1 else None,
    }


def _backend_report(state: dict[str, object]) -> str:
    backend = state["backend"]
    if backend == "none":
        return f"Backend: none found. Needs {state['missing']}"
    if backend == "landlock" and state["kernel"]:
        return f"Backend: landlock (kernel {state['kernel']})"
    return f"Backend: {backend}"


def status(json_out: bool = False) -> int:
    """Print the gate, the probe report and the network posture; a read."""
    state = sandbox_state()
    if json_out:
        _contract.emit_json(state)
        return 0
    ui.header("Sandbox")
    ui.success("Tool-call gate: always active (policy engine + high-risk command classifier)")
    ui.dim(_backend_report(state))
    print_sandbox_block()
    if state["network"] == "none":
        default = "" if _fleet.network_mode_recorded() else " (default)"
        ui.success(f"Network: none{default}; jailed tool calls have no network")
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
