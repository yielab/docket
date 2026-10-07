"""Internal workstation bootstrap used lazily by the first ``docket init``.

`bootstrap_workstation(assume_yes)` returns the process exit code (0 on success,
1 when a hard preflight fails); the project initializer returns that code to the CLI.

There is no external daemon: this provisions a purely docket-native home (directory
structure under `DOCKET_HOME`, `fleet.json`, baseline policy templates)
through `core/fleet.py`/`edges/store.py` only, so the module is fully exercisable in a
hermetic unit test.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import subprocess

import docket.config as _cfg
from docket import ui
from docket.core import fleet as _fleet
from docket.core import models_policy as _mp
from docket.core import policy as _policy
from docket.core import provider as _provider
from docket.core import secrets as _secrets


def _check_dependencies() -> list[str]:
    """Return MISSING required deps (python3/git). Docket owns its runtime, so only its
    direct tools belong in this check."""
    missing: list[str] = []

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

    return missing


def _step_model_readiness(model: str) -> int:
    """Step 4 — prove the selected runtime route is structurally callable."""
    readiness = _provider.model_readiness(model)
    if readiness.ready:
        ui.success("Model provider ready")
        ui.console.print(f"  Selected model: {readiness.model}")
        ui.console.print(f"  Endpoint: {readiness.base_url}")
        if readiness.credential_name:
            ui.console.print(f"  Credential: {readiness.credential_name} configured (value hidden)")
        else:
            ui.console.print("  No API key required")
        return 0

    ui.error(f"Selected model {model} is not ready: {readiness.issue}.")
    ui.console.print("  Coding-tool subscriptions are not Docket runtime API credentials.")
    ui.console.print("  Configure a reachable local OpenAI-compatible endpoint, then select it:")
    ui.console.print(
        "    docket models provider add local <base-url> --model <model-id> "
        "--ctx <tokens> --max-tokens <tokens>"
    )
    ui.console.print("    docket models preset local")
    return 1


def _harden_perms() -> None:
    """Harden docket-owned secrets/config file permissions to 0600."""
    hardened: list[str] = []
    for path in (_cfg.FLEET_FILE, _secrets.SECRETS_FILE, _secrets.SECRETS_META_FILE):
        if not path.is_file():
            continue
        try:
            mode = os.stat(path).st_mode & 0o777
        except OSError:
            continue
        if mode & 0o077:
            with contextlib.suppress(OSError):
                os.chmod(path, 0o600)
                hardened.append(str(path))
    if hardened:
        for hardened_path in hardened:
            ui.success(f"Tightened permissions to 600: {hardened_path}")
    else:
        ui.success("Docket-owned config/secrets permissions already owner-only (600)")


def _step_security() -> None:
    """Step 5 — harden secrets/config perms. The tool-call gate itself is always active.
    See specs/functional/security-gates.spec.md."""
    _harden_perms()
    ui.success("Tool-call gate: always active (policy engine + high-risk command classifier)")
    ui.dim("  See: docket gates status")


def _step_policies() -> None:
    """Step 6 — install the baseline guardrail policy templates (idempotent: never
    overwrites local edits). See specs/functional/security-gates.spec.md for why
    this step is what puts the policy engine on the live path at all."""
    result = _policy.install_policies()
    if not result.template_dir.is_dir():
        ui.warn(f"Policy templates not found at {result.template_dir} — skipping")
        return
    installed = len(result.installed)
    if installed > 0:
        word = "policy" if installed == 1 else "policies"
        ui.success(f"Installed {installed} baseline {word}")
    else:
        ui.success("Guardrail policies already installed")
    ui.dim(f"  Policies active at: {result.policies_dir}")
    ui.dim('  List/tune: docket policies list  ·  docket policies test <hook> <role> "<text>"')


def bootstrap_workstation(
    assume_yes: bool = False,
    continuing_to_project: bool = False,
) -> int:
    """Bootstrap a docket-native home; returns the process exit code."""
    ui.header("Preparing Shared Workstation Foundation")
    ui.console.print()
    ui.info("One Docket home with policies and security defaults.")
    ui.dim(
        "  Project pods remain separate; the current project is initialized immediately after this."
    )
    ui.console.print()

    _role_models, _rank_anchors, selected_model = _mp.load_registry()

    if _cfg.FLEET_FILE.is_file():
        ui.info("Existing Docket workstation foundation detected")
        ui.console.print()

        needs_update: list[str] = []
        readiness = _provider.model_readiness(selected_model)
        if not readiness.ready:
            needs_update.append(f"model provider: {readiness.issue}")

        if not needs_update:
            ui.success("Docket is fully configured!")
            ui.console.print()
            ui.console.print("Current foundation:")
            ui.console.print(f"  • Fleet registry: {_cfg.FLEET_FILE}")
            ui.console.print(f"  • Projects: {_cfg.PROJECTS_DIR}")
            ui.console.print(f"  • Agents: {_fleet.agent_count()}")
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
        return 1
    ui.console.print()

    ui.header("Step 2: Creating directory structure")
    _cfg.PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        os.chmod(_cfg.DOCKET_HOME, 0o700)
        # WORKSPACES_DIR is an intermediate dir of the mkdir(parents=True) call above --
        # harden it too, not just its PROJECTS_DIR child (umask otherwise leaves it open).
        os.chmod(_cfg.WORKSPACES_DIR, 0o700)
        os.chmod(_cfg.PROJECTS_DIR, 0o700)
    ui.success("Directories created")
    ui.console.print(f"  {_cfg.PROJECTS_DIR}")
    ui.console.print()

    ui.header("Step 3: Configuring the default model")
    _mp.write_registry({"default": selected_model})
    ui.success("Default model configured")
    ui.console.print(f"  Default model: {selected_model}")
    ui.console.print()

    ui.header("Step 4: Model provider readiness")
    provider_missing = _step_model_readiness(selected_model) != 0
    ui.console.print()

    ui.header("Step 5: Configuring security best practices")
    _step_security()
    ui.console.print()

    ui.header("Step 6: Guardrail policies")
    _step_policies()
    ui.console.print()

    if provider_missing:
        ui.header("Workstation Foundation Incomplete")
        ui.error("Project initialization stopped until the selected model provider is ready.")
        return 1

    if continuing_to_project:
        ui.header("Shared Workstation Foundation Ready")
        ui.console.print()
        ui.info("Continuing with project initialization...")
    else:
        _print_summary()
    return 0


def _print_summary() -> None:
    """Closing summary + next steps."""
    ui.header("Workstation Foundation Ready")
    ui.console.print()
    ui.console.print("[bold]Next Steps:[/bold]")
    ui.console.print()
    step = 1
    ui.console.print(f"  {step}. Initialize a project pod (run inside its repository):")
    ui.console.print("     [green]docket init[/green]")
    ui.console.print()
    step += 1
    ui.console.print(
        f"  {step}. Wire a channel binding (optional — enables Telegram approvals via"
        " 'docket serve --telegram'):"
    )
    ui.console.print("     [green]docket wire <agent-id>[/green]")
    ui.console.print()
    step += 1
    ui.console.print(f"  {step}. Check system health:")
    ui.console.print("     [green]docket doctor[/green]")
    ui.console.print()
    ui.console.print("[dim]Code workers (implementer/reviewer/tester) are per-project pod[/dim]")
    ui.console.print("[dim]members — run 'docket init' inside a project to create its pod.[/dim]")
    ui.console.print()
    ui.console.print("[bold]Configuration:[/bold]")
    ui.console.print(f"  Fleet registry: {_cfg.FLEET_FILE}")
    ui.console.print(f"  Projects: {_cfg.PROJECTS_DIR}")
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
