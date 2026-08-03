"""docket gates — docket's own tool-call gate + approval routing/isolation.

Phase 19 P19-3 made ``core/tools.py``'s ``pre_tool_call`` policy hook and
``core/security.py``'s argument-aware command classifier unconditionally
live on every tool call docket dispatches — there is no "enable the gate"
step any more; the gate is always on. Phase 19 P19-7b then deleted the
daemon this front door used to configure, so what ``docket gates`` manages
now is strictly narrower: where an approval prompt is routed
(``enable``/``disable``) and whether tool execution runs sandboxed
(``isolate``). ``run_gates(sub, *, want, force)`` returns the process exit
code; the coordinator wraps it in a Typer command.
"""

from __future__ import annotations

import shutil

from docket import ui
from docket.core import fleet as _fleet
from docket.core import security as _sec
from docket.core.audit import audit_log


def _usage() -> None:
    ui.console.print("[bold]Usage:[/bold] docket gates <command>")
    ui.console.print()
    ui.console.print("[bold]Commands:[/bold]")
    ui.console.print(
        "  [green]status[/green]            Show approval-routing and isolation posture"
    )
    ui.console.print(
        "  [green]enable[/green] [--force]  Turn on approval routing (prompts follow a channel)"
    )
    ui.console.print("  [green]disable[/green]           Turn approval routing off")
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
    ui.success("Policy engine + high-risk command classifier: always active (Phase 19 P19-3)")
    ui.console.print()

    r_state, r_mode = _fleet.get_approval_routing()
    if r_state == "on":
        ui.success(f"Approval routing: on (mode={r_mode or '?'})")
    elif r_state == "off":
        ui.warn("Approval routing: off — prompts won't reach a channel")
    else:
        ui.dim("Approval routing: not configured")

    iso = _fleet.get_isolation_mode()
    if iso in ("non-main", "all"):
        ui.success(f"Workspace isolation: {iso} (recorded — not yet consulted by the turn loop)")
    elif iso == "off":
        ui.dim("Workspace isolation: off")
    else:
        ui.dim("Workspace isolation: not configured — docket gates isolate on")
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
    ui.header("Workspace isolation (Docker sandbox)")
    ui.console.print()

    if want == "off":
        _sec.disable_workspace_isolation()
        audit_log("gates.isolate", "off")
        ui.success("Sandbox isolation disabled (mode=off) — tools run on the host")
        return 0

    if not shutil.which("docker"):
        ui.console.print("[red]✗[/red] Docker not found — isolation requires Docker")
        ui.console.print("  Install Docker, then re-run: [green]docket gates isolate on[/green]")
        return 1

    _sec.apply_workspace_isolation()
    audit_log("gates.isolate", "on")
    ui.success("Sandbox isolation recorded on (mode=non-main)")
    ui.warn(
        "Not yet consulted by the turn loop: DocketDriver always runs tools unsandboxed "
        "(ToolContext.sandbox='off') regardless of this setting — recorded for a future card, "
        "not faked as live enforcement."
    )
    ui.console.print("  Disable: [green]docket gates isolate off[/green]")
    return 0


def _enable(force: bool) -> int:
    ui.header("Approval routing")
    ui.console.print()
    ui.dim(
        "  docket's own tool-call gate is always active; this only controls where a"
        " require_approval prompt is routed once one fires."
    )
    ui.console.print()

    tg_count = _sec.apply_approval_routing()
    ui.success("Approval routing on (mode=session)")
    if tg_count > 0:
        ui.console.print(f"  {tg_count} channel-bound agent(s) configured (see 'docket wire').")
    else:
        ui.warn("No channel-bound agents yet — wire one (docket wire <id>) so a human can answer.")
    ui.dim(
        "  No docket-owned channel bot exists yet (P19-8) — a bound agent has nowhere to receive"
        " a live prompt until then; CLI/HTTP approval (docket approve/deny, POST /approvals) work"
        " today regardless."
    )

    audit_log("gates.enable", f"routing=on force={force}")
    ui.console.print()
    ui.console.print("  Verify:  [green]docket doctor[/green]")
    ui.console.print("  Disable: [green]docket gates disable[/green]")
    return 0


def _disable() -> int:
    ui.header("Disabling approval routing")
    ui.console.print()
    _sec.disable_approval_routing()
    audit_log("gates.disable", "")
    ui.success("Approval routing off")
    return 0


def run_gates(sub: str | None = None, *, want: str = "on", force: bool = False) -> int:
    """Dispatch the gates subcommand. Returns the process exit code.

    sub:   status (default) | enable | disable | isolate | classes | <anything else → usage>
    want:  on (default) | off — argument to 'isolate'.
    force: --force flag for 'enable' (kept for CLI compatibility; routing has no
           existing-config distinction left to force over).
    """
    subcmd = sub or "status"
    if subcmd == "status":
        return _status()
    if subcmd == "enable":
        return _enable(force)
    if subcmd == "disable":
        return _disable()
    if subcmd == "isolate":
        return _isolate(want)
    if subcmd == "classes":
        return _classes()
    _usage()
    return 0
