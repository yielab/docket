"""docket gates — docket's own tool-call gate + workspace-isolation posture.

``core/tools.py``'s ``pre_tool_call`` policy hook and ``core/security.py``'s
argument-aware command classifier are unconditionally live on every tool call
docket dispatches — there is no "enable the gate" step; the gate is always
on. ``enable``/``disable`` are retired: the approval-routing flag they wrote
had no reader anywhere on the live turn path -- see ``_RETIRED_NOTICE``. What
``docket gates`` still manages is whether tool execution runs sandboxed
(``isolate``), which the turn loop does consult. ``run_gates(sub, *, want,
force)`` returns the process exit code; the coordinator wraps it in a Typer
command.
"""

from __future__ import annotations

import shutil

from docket import ui
from docket.core import fleet as _fleet
from docket.core import security as _sec
from docket.core.audit import audit_log

# `enable`/`disable` retirement notice (security-gates.spec.md's Enablement section): the
# approval-routing flag they wrote had no reader anywhere on the live turn path. Do not
# claim a not-yet-shipped replacement command exists.
_RETIRED_NOTICE = (
    "docket gates {sub} was retired — it only recorded an approval-routing posture flag "
    "that nothing on the live path (core/tools.py, core/approval.py, core/telegram.py, "
    "core/agent_loop.py, serve.py) ever read; every channel answers an 'ask' verdict the "
    "same way regardless of it.",
    "Check today's posture:  docket doctor       (or the narrower: docket gates status)",
    "A wired, per-pod approval setting is planned but not shipped yet — there is no live "
    "consumer to route this flag to today.",
)


def _retired(sub: str) -> int:
    ui.console.print(f"[red]✗[/red] {_RETIRED_NOTICE[0].format(sub=sub)}")
    for line in _RETIRED_NOTICE[1:]:
        ui.console.print(f"  {line}")
    return 1


def _usage() -> None:
    ui.console.print("[bold]Usage:[/bold] docket gates <command>")
    ui.console.print()
    ui.console.print("[bold]Commands:[/bold]")
    ui.console.print(
        "  [green]status[/green]            Show approval-routing and isolation posture"
    )
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
    ui.dim("  'enable'/'disable' are retired — see 'docket gates enable' for why.")
    ui.dim("  Verify anytime with 'docket doctor'.")


def _status() -> int:
    ui.header("Tool-call gate")
    ui.console.print()
    ui.success("Policy engine + high-risk command classifier: always active (Phase 19 P19-3)")
    ui.console.print()

    r_state, r_mode = _fleet.get_approval_routing()
    if r_state == "on":
        ui.success(
            f"Approval routing: on (mode={r_mode or '?'})"
            " — recorded posture only, nothing on the live path reads it"
        )
    elif r_state == "off":
        ui.warn("Approval routing: off — recorded posture only, nothing on the live path reads it")
    else:
        ui.dim("Approval routing: not configured")

    iso = _fleet.get_isolation_mode()
    if iso in ("non-main", "all"):
        ui.success(
            f"Workspace isolation: {iso} (consulted by the turn loop — sandboxed via docker/bwrap "
            "when a backend is available; a turn refuses to run rather than falling back "
            "unsandboxed)"
        )
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
    ui.success("Sandbox isolation on (mode=non-main)")
    ui.dim(
        "  Consulted by the turn loop: DocketDriver probes docker/bwrap fresh on every turn and "
        "runs tools sandboxed (ToolContext.sandbox='auto') when one is usable. If neither is "
        "available when a turn starts, the turn refuses to run rather than falling back "
        "unsandboxed, and the refusal is audited ('isolation.refused')."
    )
    ui.console.print("  Disable: [green]docket gates isolate off[/green]")
    return 0


def run_gates(sub: str | None = None, *, want: str = "on", force: bool = False) -> int:
    """Dispatch the gates subcommand. Returns the process exit code.

    sub:   status (default) | isolate | classes | enable/disable (retired) |
           <anything else → usage>
    want:  on (default) | off — argument to 'isolate'.
    force: accepted (unused) for `enable`'s old CLI compatibility; parsing 'gates enable
           --force' must not error on the flag itself, only on the retired subcommand.
    """
    subcmd = sub or "status"
    if subcmd == "status":
        return _status()
    if subcmd in ("enable", "disable"):
        return _retired(subcmd)
    if subcmd == "isolate":
        return _isolate(want)
    if subcmd == "classes":
        return _classes()
    _usage()
    return 0
