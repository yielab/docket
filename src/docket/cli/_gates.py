"""docket gates — manage exec-approval enforcement.

Opt-in, re-runnable front door for the daemon's exec-approval gates. docket
configures; the OpenClaw daemon enforces. ``run_gates(sub, *, want, force)``
returns the process exit code; the coordinator wraps it in a Typer command.

All openclaw-owned reads/writes go through the ACL (``_oc``) and core.security;
this module never opens openclaw.json or exec-approvals.json directly.
"""

from __future__ import annotations

import shutil

from docket import ui
from docket.core import security as _sec
from docket.core.audit import audit_log
from docket.core.utils import restart_gateway
from docket.edges.adapters import openclaw as _oc


def _restart() -> None:
    from docket.cli import _render_restart_result

    _render_restart_result(restart_gateway())


def _usage() -> None:
    ui.console.print("[bold]Usage:[/bold] docket gates <command>")
    ui.console.print()
    ui.console.print("[bold]Commands:[/bold]")
    ui.console.print(
        "  [green]status[/green]            Show current exec-approval policy and audit posture"
    )
    ui.console.print(
        "  [green]enable[/green] [--force]  Apply conservative gate defaults + curated allowlist"
    )
    ui.console.print(
        "  [green]disable[/green]           "
        "Reset gate defaults (escape hatch; daemon falls back to tools.exec)"
    )
    ui.console.print(
        "  [green]isolate[/green] [on|off]  "
        "Confine tool execution to a per-agent Docker sandbox (needs Docker)"
    )
    ui.console.print()
    ui.console.print("[bold]What 'enable' does:[/bold]")
    ui.console.print(
        "  Sets exec-approval defaults to "
        "[cyan]security=allowlist, ask=on-miss, askFallback=deny[/cyan]"
    )
    ui.console.print("  and seeds each agent a curated allowlist of common, lower-risk binaries.")
    ui.console.print("  Dangerous/non-allowlisted commands (rm, dd, docker, ...) then prompt and,")
    ui.console.print("  with no approver reachable, are denied (fail-closed).")
    ui.console.print()
    ui.dim("  Existing config is preserved; defaults are only overwritten with --force.")
    ui.dim("  Verify anytime with 'docket doctor' (Security gates section).")


def _status() -> int:
    ui.header("Exec-approval gates")
    ui.console.print()

    gs_state, gs_policy, gs_counts = _oc.security_gate_report()
    if gs_state == "OK":
        ui.success(f"Policy: {gs_policy}")
        ui.console.print(f"  {gs_counts}")
    elif gs_state == "OPEN":
        ui.warn(f"Policy: {gs_policy} — host exec is ungated ({gs_counts})")
    elif gs_state == "UNSET":
        ui.warn("Gates inactive — no exec-approval policy configured")
        ui.console.print("  Enable with: [green]docket gates enable[/green]")
    else:
        ui.dim(f"Status unavailable: {gs_policy}")

    r_state, r_mode = _oc.get_approval_routing()
    if r_state == "on":
        ui.success(f"Approval routing: on (mode={r_mode or '?'})")
    elif r_state == "off":
        ui.warn("Approval routing: off — prompts won't reach chat")
    else:
        ui.dim("Approval routing: not configured")

    iso = _oc.get_isolation_mode()
    if iso in ("non-main", "all"):
        ui.success(f"Workspace isolation: {iso} (Docker sandbox)")
    elif iso == "off":
        ui.dim("Workspace isolation: off")
    else:
        ui.dim("Workspace isolation: not configured — docket gates isolate on")
    return 0


def _isolate(want: str) -> int:
    ui.header("Workspace isolation (Docker sandbox)")
    ui.console.print()

    if want == "off":
        _sec.disable_workspace_isolation()
        _restart()
        audit_log("gates.isolate", "off")
        ui.success("Sandbox isolation disabled (mode=off) — tools run on the host")
        return 0

    if not shutil.which("docker"):
        ui.console.print("[red]✗[/red] Docker not found — isolation requires Docker")
        ui.console.print("  Install Docker, then re-run: [green]docket gates isolate on[/green]")
        return 1

    _sec.apply_workspace_isolation()
    _restart()
    audit_log("gates.isolate", "on")
    ui.success("Sandbox isolation on (mode=non-main, scope=agent, workspaceAccess=rw)")
    ui.console.print(
        "  Non-main sessions run tools in a per-agent container; only the workspace is mounted."
    )
    ui.warn("First sandboxed run builds/pulls the image (openclaw-sandbox:bookworm-slim).")
    ui.console.print("  Disable: [green]docket gates isolate off[/green]")
    return 0


def _enable(force: bool) -> int:
    ui.header("Enabling exec-approval gates")
    ui.console.print()
    ui.warn("Fail-closed: commands not on the allowlist will prompt, and are DENIED")
    ui.console.print("  when no approver is reachable (Telegram approval routing is a later step).")
    ui.console.print("  Dangerous bins (rm, dd, docker, systemctl, ...) are intentionally gated.")
    ui.console.print()

    result = _sec.apply_exec_approval_gates(force)

    if result.defaults_changed:
        ui.success("Applied gate defaults (security=allowlist, ask=on-miss, askFallback=deny)")
    else:
        ui.info("Gate defaults already set — left as-is (use --force to overwrite)")
    if result.seeded:
        ui.success(f"Seeded allowlist ({result.bins} bins) for: {','.join(result.seeded)}")
    if result.mode == "applied-via-daemon":
        ui.info("Applied via the running gateway (openclaw approvals set)")
    elif result.mode == "applied-direct":
        ui.info("Wrote ~/.openclaw/exec-approvals.json directly (gateway not reached)")

    tg_count = _sec.apply_approval_routing()
    ui.success("Approval routing on (mode=session) — prompts go to each agent's channel")
    if tg_count > 0:
        ui.console.print(
            f"  {tg_count} Telegram-bound agent(s) can approve with: /approve <id> allow-once|deny"
        )
    else:
        ui.warn("No Telegram-bound agents — wire one (docket wire <id>) so prompts are answerable.")

    _restart()
    audit_log("gates.enable", f"security=allowlist seeded={','.join(result.seeded)}")

    ui.console.print()
    ui.console.print(
        "  Verify:  [green]docket doctor[/green]   ·   "
        "Tune:  [green]openclaw approvals allowlist add <glob>[/green]"
    )
    ui.console.print("  Disable: [green]docket gates disable[/green]")
    return 0


def _disable() -> int:
    ui.header("Disabling exec-approval gates")
    ui.console.print()
    _sec.disable_exec_approval_gates()
    _sec.disable_approval_routing()
    _restart()
    audit_log("gates.disable", "")
    ui.success("Reset gate defaults + approval routing — daemon falls back to tools.exec policy")
    ui.dim("  Seeded allowlists are left in place (harmless; reused if re-enabled).")
    return 0


def run_gates(sub: str | None = None, *, want: str = "on", force: bool = False) -> int:
    """Dispatch the gates subcommand. Returns the process exit code.

    sub:   status (default) | enable | disable | isolate | <anything else → usage>
    want:  on (default) | off — argument to 'isolate'.
    force: --force flag for 'enable'.
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
    _usage()
    return 0
