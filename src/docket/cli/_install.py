"""docket install — bootstrap OpenClaw + specialist agents.

`run_install(want_gates, assume_yes)`
returns the process exit code (0 on success, 1 when a hard preflight fails); the
coordinator wraps it in a Typer command and raises typer.Exit(code).

All openclaw.json / daemon knowledge funnels through the ACL (`_oc`) and the
system adapter (`_sys`); this module never opens openclaw.json directly.

Two steps genuinely depend on a live OpenClaw daemon and cannot be exercised in
a hermetic unit test:
  * Step 2 — `openclaw onboard` (only invoked when openclaw.json is absent).
  * Step 6 — the interactive auth chooser (`openclaw models auth ...`), only
    reached when no usable auth profile exists *and* stdin is a TTY.
Both are isolated behind small functions (`_run_onboard`, `_auth_setup_interactive`)
so the surrounding orchestration stays testable; tests drive the "auth already
configured" and "auth missing, non-TTY" branches.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime

import docket.config as _cfg
from docket import ui
from docket.core import models_policy as _mp
from docket.core.audit import audit_log
from docket.core.security import apply_approval_routing, apply_exec_approval_gates
from docket.edges import store
from docket.edges.adapters import openclaw as _oc
from docket.edges.adapters import system as _sys


def _check_dependencies() -> list[str]:
    """Report required (openclaw/python3/git) + optional (fzf) tools.

    Returns the list of MISSING required dependencies (empty when all present).
    """
    missing: list[str] = []

    oc = shutil.which("openclaw")
    if oc:
        ui.success(f"openclaw: {_openclaw_version()}")
    else:
        missing.append("openclaw")

    py = shutil.which("python3") or shutil.which("python")
    if py:
        ver = ""
        try:
            res = subprocess.run([py, "--version"], capture_output=True, text=True, timeout=5)
            ver = (res.stdout or res.stderr).strip().split()[-1]
        except (OSError, subprocess.TimeoutExpired, IndexError):
            ver = ""
        ui.success(f"python3: {ver}" if ver else "python3: found")
    else:
        missing.append("python3")

    if shutil.which("git"):
        ui.success("git: found")
    else:
        missing.append("git")

    if missing:
        return missing

    if shutil.which("fzf"):
        ui.success("fzf: found (optional, improves UX)")
    else:
        ui.warn("fzf not found (optional) — install with: brew install fzf")
    return missing


def _openclaw_version() -> str:
    probe = _oc.openclaw_version()
    return probe.output or "found"


def _run_onboard() -> None:
    """Run `openclaw onboard` (only when openclaw.json is absent).

    Live-daemon path; isolated so the orchestration around it stays testable.
    """
    _oc.onboard()


def _auth_print_profiles() -> None:
    """Pretty-print the auth-profile summary."""
    for p in _oc.auth_profiles_summary():
        if p.disabled:
            reason = p.disabled_reason or "?"
            ui.console.print(
                f"  [yellow]●[/yellow] {p.id}  [dim]({p.provider}, {p.type})[/dim] "
                f"— [yellow]{reason} disabled[/yellow]"
            )
        else:
            ui.console.print(f"  [green]●[/green] {p.id}  [dim]({p.provider}, {p.type})[/dim]")


def _auth_setup_interactive() -> bool:
    """Interactive Claude-auth chooser.

    Returns True if a usable profile was configured. Shells out to
    `openclaw models auth` so OpenClaw owns the credential format. Live path —
    reached only with no usable profile and a TTY.
    """
    if not shutil.which("openclaw"):
        ui.warn("openclaw CLI not found — cannot configure auth.")
        return False

    ui.console.print()
    ui.console.print("[bold]How should agents authenticate to Claude?[/bold]")
    ui.console.print(
        "  1) Claude subscription (Pro/Max) — uses your plan; runs the provider token flow"
    )
    ui.console.print(
        "     [dim]Note: third-party/agent use draws from your extra usage, not plan limits.[/dim]"
    )
    ui.console.print("  2) API key (pay-as-you-go)        — paste an sk-ant-… key")
    ui.console.print("  3) Skip for now")
    ui.console.print()
    try:
        choice = input("Choice [1/2/3]: ").strip()
    except EOFError:
        choice = "3"

    if choice == "1":
        ui.info("Starting subscription token flow (openclaw models auth setup-token)...")
        ok = _run_openclaw_auth("setup-token")
        if ok:
            ui.success("Subscription token configured.")
            audit_log("auth.setup", "anthropic subscription (setup-token)")
        else:
            ui.warn(
                "Token flow did not complete. Retry later: "
                "openclaw models auth setup-token --provider anthropic"
            )
            return False
    elif choice == "2":
        ui.info("Starting API-key flow (openclaw models auth paste-token)...")
        ui.dim("  Get a key: https://console.anthropic.com/settings/keys")
        ok = _run_openclaw_auth("paste-token")
        if ok:
            ui.success("API key configured.")
            audit_log("auth.setup", "anthropic api-key (paste-token)")
        else:
            ui.warn(
                "Paste-token flow did not complete. Retry later: "
                "openclaw models auth paste-token --provider anthropic"
            )
            return False
    else:
        ui.dim("  Skipped — configure later with: docket auth (or openclaw models auth).")
        return False

    _sys.restart_gateway()
    return True


def _run_openclaw_auth(method: str) -> bool:
    try:
        res = (
            _oc.auth_paste_token(timeout=600)
            if method == "paste-token"
            else _oc.auth_setup_token(timeout=600)
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return res.returncode == 0


def _step_auth() -> int:
    """Step 6 — model authentication. Returns 0 if auth is usable, else 1.

    Detect existing profiles, warn when all are disabled, and run the interactive
    chooser when none exist.
    """
    profiles = _oc.auth_profiles_summary()
    has_usable = any(not p.disabled for p in profiles)

    if has_usable:
        ui.success("Claude auth already configured:")
        _auth_print_profiles()
        return 0

    if profiles:
        ui.warn("All Claude auth profiles are currently disabled (usage/billing):")
        _auth_print_profiles()
        ui.dim(
            "  Add subscription usage: https://claude.ai/settings/usage  "
            "·  or re-fund your API key."
        )
        ui.console.print("  Reconfigure anytime: [green]docket auth[/green]")
        return 1

    ui.warn("No Claude auth configured — agents cannot answer yet.")
    if not sys.stdin.isatty():
        ui.dim("  Non-interactive shell — configure later with: docket auth")
        return 1
    _auth_setup_interactive()
    return 0 if any(not p.disabled for p in _oc.auth_profiles_summary()) else 1


def _step_security(want_gates: bool) -> None:
    """Step 7 — harden config perms and optionally apply exec gates."""
    hardened = _oc.harden_config_perms()
    if hardened:
        for path in hardened:
            ui.success(f"Tightened permissions to 600: {path}")
    else:
        ui.success("Config and secrets permissions already owner-only (600)")
    ui.dim("  Verify posture anytime with: docket doctor  (Security gates section)")

    if not want_gates:
        ui.dim("  Exec-approval enforcement is opt-in: 'docket gates enable' (or install --gates).")
        ui.dim("  Spec: specs/functional/security-gates.spec.md.")
        return

    ui.console.print()
    try:
        result = apply_exec_approval_gates()
    except Exception:
        ui.warn("Could not apply exec-approval gates (see 'docket gates enable')")
        return
    ui.success("Exec-approval gates applied (security=allowlist, ask=on-miss, askFallback=deny)")
    if result.seeded:
        ui.console.print(f"  Seeded allowlist ({result.bins} bins) for: {','.join(result.seeded)}")
    try:
        tg = apply_approval_routing()
        ui.success(f"Approval routing on (mode=session); {tg} Telegram-bound agent(s)")
    except Exception:
        pass
    ui.warn("Fail-closed: non-allowlisted commands are denied without an approver.")
    ui.console.print(
        "  Tune: [green]openclaw approvals allowlist add <glob>[/green]  "
        "·  Disable: [green]docket gates disable[/green]"
    )


def _step_gateway() -> None:
    """Step 8 — start/restart the gateway service (best-effort)."""
    if _sys.service_manager() == "none":
        ui.warn("No service manager detected — start the OpenClaw gateway yourself:")
        ui.console.print(f"  {_sys.service_hint('start')}")
        return

    if _sys.gateway_active():
        ui.success("Gateway already running")
        ui.info("Restarting to apply changes...")
        _sys.systemctl_restart()
    else:
        ui.info("Starting gateway service...")
        _sys.systemctl_start()

    if _sys.gateway_active():
        ui.success("Gateway service: active")
    else:
        ui.warn("Gateway service not started")
        ui.console.print(f"  Start manually: {_sys.service_hint('start')}")


def _provision_specialists() -> None:
    """Step 5 — register the shared **org** specialist agents + backfill their meta.

    Install provisions only the cross-cutting org roles (security, knowledge,
    manager) as shared singletons. The project roles (programmer, reviewer, tester)
    are NOT installed globally — they become per-pod workers provisioned by
    `docket add`, so one programmer never serves two projects.

    Models come from the role→model policy so a provider preset switched before
    install provisions specialists on that provider.
    """
    for spec in _cfg.ORG_SPECIALIST_ORDER:
        spec_model = _mp.resolve_role_model(spec)
        spec_dir = _cfg.OPENCLAW_DIR / "workspaces" / spec

        if _oc.agent_registered(spec):
            ui.success(f"{spec}: already registered")
        else:
            ui.info(f"Creating {spec} agent...")
            spec_dir.mkdir(parents=True, exist_ok=True)
            ok, message = _oc.register_agent_cli(spec, str(spec_dir), spec_model)
            why = _cfg.ROLE_WHY.get(spec, "")
            if ok:
                ui.success(f"{spec}: created ({spec_model} — {why})")
            else:
                ui.warn(f"{spec}: registration failed — {message}")

        # Specialists are first-class meta citizens: stamp .docket-meta.json so
        # list/profile/doctor manage them like any other agent.
        meta_file = spec_dir / _cfg.META_FILE
        if spec_dir.is_dir() and not meta_file.is_file():
            store.write_json(
                meta_file,
                {
                    "kind": "specialist",
                    "scope": _cfg.role_scope(spec),
                    "role": spec,
                    "name": spec,
                    "model": spec_model,
                    "modelSource": "policy",
                    "created": datetime.now(UTC).isoformat(),
                },
            )


_PORTFOLIO_SOUL = """# SOUL — Portfolio Manager

**Scope:** org (cross-pod). **Role:** portfolio-manager. **Edits code:** never.

You are the org-level Portfolio Manager: a single planning/visibility surface
across every project pod. You see fleet **metadata** — agents, queues, budgets,
health — not project source code, and you are distinct from each pod's Lead.

## You do
- Survey the fleet: which pods exist, their members, recent activity, spend.
- Spot cross-cutting risk (budget pressure, stalled pods, drift) and surface it
  to the human operator.
- Recommend where to focus, rebalance, or pause — in words, for a human to act on.

## You do NOT
- Edit code or enter any project workspace.
- Dispatch work into pods at runtime (a pod's own Lead + `docket pod <p> dispatch`
  own execution). You are advisory in v1.
- Replace per-pod Leads — each pod still owns its own context and humans comms.
"""


def _provision_portfolio_manager() -> None:
    """Provision the single opt-in org Portfolio Manager.

    A `scope: org`, `role: portfolio-manager` agent: a cross-pod planning surface
    over fleet metadata (not project code). Opt-in (`docket install --portfolio`),
    never auto-installed, never a pod member. Idempotent.
    """
    role = _cfg.PORTFOLIO_MANAGER_ROLE
    model = _mp.resolve_role_model(role)
    ws = _cfg.OPENCLAW_DIR / "workspaces" / role

    if _oc.agent_registered(role):
        ui.success(f"{role}: already registered")
    else:
        ui.info(f"Creating {role} agent...")
        ws.mkdir(parents=True, exist_ok=True)
        ok, message = _oc.register_agent_cli(role, str(ws), model)
        if ok:
            ui.success(f"{role}: created ({model} — {_cfg.ROLE_WHY.get(role, '')})")
        else:
            ui.warn(f"{role}: registration failed — {message}")

    if ws.is_dir():
        soul = ws / "SOUL.md"
        if not soul.is_file():
            soul.write_text(_PORTFOLIO_SOUL, encoding="utf-8")
            with contextlib.suppress(OSError):
                os.chmod(soul, 0o600)
        meta_file = ws / _cfg.META_FILE
        if not meta_file.is_file():
            store.write_json(
                meta_file,
                {
                    "kind": "specialist",
                    "scope": _cfg.role_scope(role),  # → "org"
                    "role": role,
                    "name": role,
                    "model": model,
                    "modelSource": "policy",
                    "created": datetime.now(UTC).isoformat(),
                },
            )


def run_install(
    want_gates: bool = False, assume_yes: bool = False, want_portfolio: bool = False
) -> int:
    """Bootstrap OpenClaw + specialist agents. Returns the process exit code.

    want_gates:      apply opt-in exec-approval enforcement.
    assume_yes:      skip the reconfigure/update confirmation prompt (non-interactive).
    want_portfolio:  also provision the opt-in org Portfolio Manager.
    """
    ui.header("Docket Installation — OpenClaw Setup")
    ui.console.print()

    if _oc.config_exists():
        ui.info("Existing OpenClaw installation detected")
        ui.console.print()

        needs_update: list[str] = []
        if not _oc.has_agent_defaults():
            needs_update.append("agent defaults")
        missing_specialists = [s for s in _cfg.ORG_SPECIALIST_ORDER if not _oc.agent_registered(s)]
        if missing_specialists:
            needs_update.append("specialist agents: " + " ".join(missing_specialists))

        if not needs_update:
            ui.success("OpenClaw is fully configured!")
            ui.console.print()
            ui.console.print("Current setup:")
            ui.console.print(f"  • Config: {_cfg.CONFIG_FILE}")
            ui.console.print(f"  • Projects: {_cfg.PROJECTS_DIR}")
            ui.console.print(f"  • Agents: {_oc.agent_count()}")
            ui.console.print()
            if not assume_yes and not _confirm("Reconfigure anyway? [y/N]: ", default_yes=False):
                ui.info("Nothing to do. Run 'docket doctor' to verify health.")
                return 0
        else:
            ui.warn("Updates needed:")
            for update in needs_update:
                ui.console.print(f"  • {update}")
            ui.console.print()
            if not assume_yes and not _confirm("Apply updates? [Y/n]: ", default_yes=True):
                ui.warn("Aborted.")
                return 0

    ui.header("Step 1: Checking dependencies")
    missing = _check_dependencies()
    if missing:
        ui.error(f"Missing dependencies: {' '.join(missing)}")
        ui.console.print()
        ui.console.print("Install OpenClaw from: https://openclaw.dev")
        return 1
    ui.console.print()

    ui.header("Step 2: OpenClaw initialization")
    if not _oc.config_exists():
        ui.info("Running openclaw onboard...")
        ui.console.print()
        _run_onboard()
        ui.console.print()
        ui.success("OpenClaw initialized")
    else:
        ui.success("OpenClaw already initialized")

    ui.header("Step 3: Creating directory structure")
    _cfg.PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
    _cfg.SITES_DIR.mkdir(parents=True, exist_ok=True)
    _cfg.LOG_DIR.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        os.chmod(_cfg.OPENCLAW_DIR, 0o700)
        os.chmod(_cfg.PROJECTS_DIR, 0o700)
    ui.success("Directories created")
    ui.console.print(f"  {_cfg.PROJECTS_DIR}")
    ui.console.print(f"  {_cfg.SITES_DIR}")
    ui.console.print()

    ui.header("Step 4: Configuring agent defaults")
    _oc.configure_agent_defaults(_cfg.DEFAULT_MODEL)
    ui.success("Agent defaults configured")
    ui.console.print(f"  Default model: {_cfg.DEFAULT_MODEL}")
    ui.console.print("  Compaction: safeguard mode")
    ui.console.print("  Max concurrent: 4 agents")
    ui.console.print()

    ui.header("Step 5: Setting up specialist agents")
    _provision_specialists()
    if want_portfolio:
        ui.console.print()
        ui.info("Provisioning the org Portfolio Manager (--portfolio)...")
        _provision_portfolio_manager()
    ui.console.print()

    ui.header("Step 6: Model authentication")
    auth_missing = _step_auth() != 0
    ui.console.print()

    ui.header("Step 7: Configuring security best practices")
    _step_security(want_gates)
    ui.console.print()

    ui.header("Step 8: Gateway service")
    _step_gateway()
    ui.console.print()

    _print_summary(auth_missing)
    return 0


def _print_summary(auth_missing: bool) -> None:
    """Step 9 — closing summary + next steps."""
    ui.header("Installation Complete!")
    ui.console.print()
    ui.console.print("[bold]Next Steps:[/bold]")
    ui.console.print()
    step = 1
    if auth_missing:
        ui.console.print(f"  {step}. Set up Claude auth (agents can't reply without it):")
        ui.console.print("     [green]docket auth[/green]   [dim](subscription or API key)[/dim]")
        ui.console.print()
        step += 1
    ui.console.print(f"  {step}. Add your first project agent:")
    ui.console.print("     [green]docket add[/green]")
    ui.console.print()
    step += 1
    ui.console.print(f"  {step}. Configure Telegram (optional but recommended):")
    ui.console.print("     - Create groups for each agent (manager, your pod leads, etc.)")
    ui.console.print("     - Add your bot to each group")
    ui.console.print("     - Wire agents: [green]docket wire <agent-id>[/green]")
    ui.console.print()
    step += 1
    ui.console.print(f"  {step}. Check system health:")
    ui.console.print("     [green]docket doctor[/green]")
    ui.console.print()
    ui.console.print("[bold]Org Specialists (auto-created, shared across projects):[/bold]")
    ui.console.print("  • manager    - Cross-cutting coordination and task queue")
    ui.console.print("  • knowledge  - Memory distillation and patterns")
    ui.console.print("  • security   - Security audits and risk checks")
    ui.console.print()
    ui.console.print("[dim]Code workers (implementer/reviewer/tester) are per-project pod[/dim]")
    ui.console.print("[dim]members — run 'docket add <project>' to create a pod.[/dim]")
    ui.console.print()
    ui.console.print("[bold]Configuration:[/bold]")
    ui.console.print(f"  Config: {_cfg.CONFIG_FILE}")
    ui.console.print(f"  Projects: {_cfg.PROJECTS_DIR}")
    ui.console.print(f"  Sites: {_cfg.SITES_DIR}")
    ui.console.print()
    ui.console.print("[bold]Cost Management:[/bold]")
    ui.console.print(f"  Default model: {_cfg.DEFAULT_MODEL}")
    ui.console.print("  View usage: [green]docket cost[/green]")
    ui.console.print(
        "  Role→model policy: [green]docket models[/green]   "
        "Pin one agent: [green]docket profile <id> <provider/model>[/green]"
    )
    ui.console.print()


def _confirm(prompt: str, *, default_yes: bool) -> bool:
    """Read a y/N (or Y/n) confirmation. EOF/empty → the default."""
    try:
        answer = input(prompt).strip().lower()
    except EOFError:
        return default_yes
    if not answer:
        return default_yes
    return answer == "y"
