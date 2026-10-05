"""docket gates — docket's own tool-call gate + workspace-isolation posture.

``core/tools.py``'s ``pre_tool_call`` policy hook and ``core/security.py``'s
argument-aware command classifier are unconditionally live on every tool call
docket dispatches — the gate is always on. What ``docket gates`` manages is
whether tool execution runs sandboxed (``isolate``), which the turn loop
consults. ``run_gates(sub, *, want)`` returns the process exit code; the
coordinator wraps it in a Typer command.
"""

from __future__ import annotations

from docket import ui
from docket.core import fleet as _fleet
from docket.core import security as _sec
from docket.core.audit import audit_log
from docket.edges.adapters import system as _sys


def _usage() -> None:
    ui.console.print("[bold]Usage:[/bold] docket gates <command>")
    ui.console.print()
    ui.console.print("[bold]Commands:[/bold]")
    ui.console.print("  [green]status[/green]            Show the gate and isolation posture")
    ui.console.print(
        "  [green]isolate[/green] [on|off]  "
        "Confine tool execution to a per-agent Docker sandbox (needs Docker)"
    )
    ui.console.print(
        "  [green]classes[/green]           "
        "List the documented high-risk action classes (see 'docket gates classes')"
    )
    ui.console.print()
    ui.dim(
        "  docket's own tool-call gate (pre_tool_call + the argument-aware command"
        " classifier) is always active — there is nothing here to turn on or off."
    )
    ui.dim("  Verify anytime with 'docket doctor'.")


def _status() -> int:
    ui.header("Tool-call gate")
    ui.console.print()
    ui.success("Policy engine + high-risk command classifier: always active")
    ui.console.print()

    state = _fleet.get_isolation_state()
    if state == "off":
        ui.dim("Workspace isolation: off (explicit) -- tools run on the host")
    else:
        ui.success(
            f"Workspace isolation: {state} (consulted by the turn loop; a turn refuses to run "
            "rather than falling back unsandboxed; docket doctor names the backend)"
        )
    return 0


def _classes() -> int:
    ui.header("High-risk action classes")
    ui.console.print()
    ui.console.print(
        "  Documented action classes considered especially consequential "
        "(money movement, prod deploys, secret access)."
    )
    ui.console.print()
    for cls in _sec.HIGH_RISK_PATTERNS:
        ui.console.print(f"[bold]{cls.name}[/bold] — {cls.description}")
        ui.dim(f"  pattern: {cls.pattern}")
        if cls.bins:
            ui.dim(
                f"  overlaps allowlisted bins: {', '.join(cls.bins)} — classify_command reads the"
                " whole command line, so a high-risk invocation still asks even though the bin"
                " itself is allowlisted"
            )
        else:
            ui.dim("  none of this class's bins are allowlisted — always asks today")
        ui.console.print()
    ui.dim("  This seed list is intentionally small and built-in (not yet user-configurable).")
    ui.dim("  Wired: core/tools.py's dispatch_tool classifies every shell command before it runs;")
    ui.dim("  run_verify_cmd separately refuses a matching verify command outright (fails closed);")
    ui.dim("  a hop's real output is also scanned for a match on pre_output (logged, not blocked).")
    return 0


def _isolate(want: str) -> int:
    ui.header("Workspace isolation (bwrap or docker sandbox)")
    ui.console.print()

    if want == "off":
        _sec.disable_workspace_isolation()
        audit_log("gates.isolate", "off")
        ui.success("Sandbox isolation disabled (mode=off) — tools run on the host")
        return 0

    avail = _sys.sandbox_availability()
    if avail.backend == "none":
        ui.console.print(
            "[red]✗[/red] No sandbox backend usable — isolation needs bubblewrap or docker"
        )
        ui.console.print(
            "  Install bubblewrap (bwrap) or start docker, then re-run: [green]docket gates isolate on[/green]"
        )
        return 1

    _sec.apply_workspace_isolation()
    audit_log("gates.isolate", "on")
    ui.success(f"Sandbox isolation on (mode=non-main, backend={avail.backend})")
    ui.dim(
        "  Consulted by the turn loop: DocketDriver probes docker/bwrap fresh on every turn and "
        "runs tools sandboxed (ToolContext.sandbox='auto') when one is usable. If neither is "
        "available when a turn starts, the turn refuses to run rather than falling back "
        "unsandboxed, and the refusal is audited ('isolation.refused')."
    )
    ui.console.print("  Disable: [green]docket gates isolate off[/green]")
    return 0


def run_gates(sub: str | None = None, *, want: str = "on") -> int:
    """Dispatch the gates subcommand. Returns the process exit code.

    sub:   status (default) | isolate | classes | <anything else → usage, exit 2>
    want:  on (default) | off — argument to 'isolate'.
    """
    subcmd = sub or "status"
    if subcmd == "status":
        return _status()
    if subcmd == "isolate":
        return _isolate(want)
    if subcmd == "classes":
        return _classes()
    ui.console.print(f"[red]✗[/red] docket gates: unknown subcommand '{subcmd}'")
    _usage()
    return 2
