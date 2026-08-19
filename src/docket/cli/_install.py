"""docket install — bootstrap a docket-native home + specialist agents.

`run_install(want_gates, assume_yes)`
returns the process exit code (0 on success, 1 when a hard preflight fails); the
coordinator wraps it in a Typer command and raises typer.Exit(code).

There is no external daemon. `docket install` provisions a purely
docket-native home: directory structure under `DOCKET_HOME`, the fleet
registry (`fleet.json`), specialist agents (fleet registration + workspace +
meta), and the baseline guardrail policy templates. `.docket-meta.json`/
`fleet.json` reads and writes go through `core/fleet.py` and
`edges/store.py`; nothing here opens a daemon config file, because none
exists.

No step here depends on a live external process, so this module is fully
exercisable in a hermetic unit test.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import docket.config as _cfg
from docket import ui
from docket.core import fleet as _fleet
from docket.core import memory as _mem
from docket.core import models_policy as _mp
from docket.core import policy as _policy
from docket.core import secrets as _secrets
from docket.core.security import apply_approval_routing
from docket.edges import store


def _check_dependencies() -> list[str]:
    """Report required (python3/git) + optional (fzf) tools.

    Returns the list of MISSING required dependencies (empty when all present).
    Docket owns its runtime, so only its direct tools belong in this check.
    """
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

    if missing:
        return missing

    if shutil.which("fzf"):
        ui.success("fzf: found (optional, improves UX)")
    else:
        ui.warn("fzf not found (optional) — install with: brew install fzf")
    return missing


def _step_auth() -> int:
    """Step 5 — model authentication. Returns 0 if a credential looks available.

    There is no docket-native provider-login flow (no daemon to shell out to
    for an OAuth-like token exchange). The real, working credential path is
    `docket keys add <PROVIDER>_API_KEY` — `edges/adapters/llm.py`'s
    `resolve_endpoint` falls back to that env var. This step only checks
    whether one is already stored or exported, and says plainly what to do
    if not.
    """
    stored = _secrets.secrets_keys()
    known_env_vars = (
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "GOOGLE_AI_API_KEY",
        "OPENROUTER_API_KEY",
        "DOCKET_LLM_API_KEY",
    )
    present = sorted(stored) + [v for v in known_env_vars if v in os.environ and v not in stored]

    if present:
        ui.success("Model credential(s) available:")
        for name in present:
            source = "stored" if name in stored else "environment"
            ui.console.print(f"  • {name}  ({source})")
        return 0

    ui.warn("No model-provider credential found yet — agents cannot reply without one.")
    ui.console.print("  Store one: [green]docket keys add ANTHROPIC_API_KEY[/green]")
    ui.console.print(
        "  (or export it directly: ANTHROPIC_API_KEY=sk-ant-... in your shell environment)"
    )
    return 1


def _harden_perms() -> None:
    """Harden docket-owned secrets/config file permissions to 0600.

    Always runs regardless of --gates/--no-gates -- this is basic file
    hygiene, not exec-approval policy.
    """
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


def _step_security(want_gates: bool) -> None:
    """Step 6 — harden docket-owned secrets/config perms + approval routing.

    There is no separate daemon exec-approval config to enable/disable:
    `core/tools.py`'s policy engine + high-risk command classifier are
    unconditionally active on every tool call docket dispatches, so there is
    nothing left to "enable". What remains configurable is where an approval
    prompt is routed, and that is the one piece --no-gates actually opts out
    of.
    """
    _harden_perms()

    ui.success("Tool-call gate: always active (policy engine + high-risk command classifier)")
    ui.dim("  Nothing to enable/disable there — see: docket gates status")

    if not want_gates:
        ui.dim("Approval-routing setup skipped (--no-gates).")
        ui.console.print("  Enable later: 'docket gates enable'.")
        return

    tg = apply_approval_routing()
    ui.success(f"Approval routing on (mode=session); {tg} channel-bound agent(s)")
    ui.dim("  Verify posture anytime with: docket doctor  (Security gates section)")


def _step_policies() -> None:
    """Step 7 — install the baseline guardrail policy templates.

    Idempotent (same producer as ``docket policies init``): a repeat install skips files
    already present rather than overwriting local edits. This is what puts the policy
    engine on the live path at all — ``pre_input``/``pre_output`` have nothing to evaluate
    against an empty ``$POLICIES_DIR`` (``policy_eval`` returns ``allow`` unconditionally).
    """
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


# One-line role identity for each org specialist's SOUL.md `## Scope` section
# (paraphrased from docs/DOCKET.md's per-role capability tables — the durable
# description of what each shared singleton is *for*).
_SPECIALIST_IDENTITY: dict[str, str] = {
    "security": (
        "Deep security audits, threat modeling, and the HITL gate for risky or "
        "destructive actions — across every pod, not just one project."
    ),
    "knowledge": (
        "Documentation, research, and pattern extraction across every project's "
        "memory. You distill durable facts; you do not touch source code."
    ),
    "manager": (
        "Cross-cutting coordination across pods (transitional — being superseded "
        "by per-pod Leads). Advisory only: you read memory/snapshots, you don't "
        "execute work yourself."
    ),
}


def _specialist_session_key(role: str) -> str:
    """Session key for an org specialist: `agent:<role>:org`.

    Mirrors project agents' `agent:<id>:<project>` pattern (see
    ``specs/data/docket-meta.spec.md``), using ``org`` as the project component
    since a specialist is shared across the whole fleet, not scoped to one.
    """
    return f"agent:{role}:org"


def _specialist_agents_md(role: str) -> str:
    """AGENTS.md for an org specialist — the same session protocol every
    project agent gets (see ``cli/_agents.py``'s ``_create_workspace``), minus
    the codebase/stack sections a specialist has neither of.

    Section names matter: the turn loop re-injects the "Session Startup"
    and "Red Lines" H2 blocks after every compaction — keep them verbatim.
    """
    return (
        f"# AGENTS.md — {role}\n\n"
        "## Session Startup\n"
        "_Lean — re-sent every turn._\n"
        f"1. Read {_mem.REQUIRED_STARTUP_FILE} — startup protocol (the turn loop "
        "requires this after every context reset).\n"
        f"2. Read {_mem.HEARTBEAT_FILE} — active tasks/decisions (small; always). Unchecked\n"
        "   items mean you were interrupted mid-task: resume them, don't greet idle.\n"
        "3. Read history ONLY when the task needs it: open MEMORY.md, then the\n"
        "   specific memory/YYYY-MM-DD.md you need. Every byte you read is re-sent\n"
        "   on every later turn.\n"
        "4. Log outcomes to today's memory/YYYY-MM-DD.md (one file per day).\n\n"
        "## Red Lines\n"
        f"- You are the shared org **{role}** specialist: act across every pod,\n"
        "  never as if you were a member of just one.\n"
        "- Never edit code, run builds, or commit — that is a pod's own\n"
        "  Implementer's job.\n"
        f"- Before starting multi-step work, write it to {_mem.HEARTBEAT_FILE} — an\n"
        "  unwritten task does not survive a context reset.\n"
    )


def _specialist_soul(role: str) -> str:
    """SOUL.md for an org specialist: identity, scope, and session key.

    Mirrors ``cli/_agents.py``'s ``_create_workspace`` / ``cli/_pod.py``'s
    ``_member_soul`` — adapted for a role with no codebase and no single
    project (shared, singleton, cross-pod).
    """
    identity = _SPECIALIST_IDENTITY.get(role, f"You are the org-level **{role}** specialist.")
    return (
        f"# SOUL.md — {role}\n\n"
        "## Identity\n"
        f"You are the org-level **{role}** specialist — shared across every "
        "project pod, not scoped to any single project.\n\n"
        f"**Session Key:** `{_specialist_session_key(role)}`\n\n"
        "This session key isolates your org-level context. You may only access "
        "resources and memory within this coordinate space.\n\n"
        "## Scope\n"
        f"{identity}\n\n"
        "## Traits\n"
        f"- Proactive: check {_mem.HEARTBEAT_FILE} every session.\n"
        "- You do not edit code, run builds, or commit — that is a pod's own "
        "Implementer's job.\n\n"
        "## Safety\n"
        "- Never take a destructive or irreversible action without HITL approval.\n"
    )


def _write_specialist_contract_files(role: str, ws: Path, soul_text: str) -> None:
    """Give an org specialist (or the opt-in Portfolio Manager) the same
    durable workspace contract a project agent gets:
    ``SOUL.md`` (caller-supplied, role-specific), a generic org-specialist
    ``AGENTS.md``, ``HEARTBEAT.md`` (the durable task ledger), and the
    ``WORKFLOW_AUTO.md``/``MEMORY.md``/daily-log set from
    ``core/memory.py``'s ``seed_contract``. ``TOOLS.md`` is deliberately
    skipped — a specialist has no fixed codebase or build commands to document.

    Idempotent and backfill-safe: ``SOUL.md``/``AGENTS.md``/``HEARTBEAT.md``
    are written only when absent, so re-running `docket install` (or healing
    an older install via `docket doctor`) never clobbers an agent-written
    ``HEARTBEAT.md`` or a persona-decorated ``SOUL.md``. ``seed_contract``
    itself only ever creates ``MEMORY.md``/the daily log when absent —
    ``WORKFLOW_AUTO.md`` is wholly derived and always refreshed, never
    hand-edited.
    """
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "memory").mkdir(exist_ok=True)

    for fname, text in (
        ("SOUL.md", soul_text),
        ("AGENTS.md", _specialist_agents_md(role)),
        (_mem.HEARTBEAT_FILE, _mem.heartbeat_seed(role)),
    ):
        fpath = ws / fname
        if not fpath.is_file():
            fpath.write_text(text, encoding="utf-8")
        with contextlib.suppress(OSError):
            fpath.chmod(0o600)

    # Seed the files the turn loop's system-prompt composition re-reads every
    # turn. Specialists have no codebase — say so plainly rather than the
    # project default's "ask the human for the repo path" (which would be
    # misleading).
    _mem.seed_contract(
        ws,
        project=role,
        codebase="(none — shared org specialist, not scoped to one project)",
    )

    # Quarantine any self-authoring base-assistant scaffolding so identity
    # stays docket-owned (SOUL.md), not self-authored (IDENTITY.md/BOOTSTRAP.md).
    from docket.core import identity as _identity

    _identity.quarantine_scaffolding(ws)

    with contextlib.suppress(OSError):
        ws.chmod(0o700)
        (ws / "memory").chmod(0o700)


def _provision_specialists() -> None:
    """Step 4 — register the shared **org** specialist agents + backfill their
    meta and full workspace contract.

    Install provisions only the cross-cutting org roles (security, knowledge,
    manager) as shared singletons. The project roles (programmer, reviewer, tester)
    are NOT installed globally — they become per-pod workers provisioned by
    `docket add`, so one programmer never serves two projects.

    Models come from the role→model policy so a provider preset switched before
    install provisions specialists on that provider.
    """
    for spec in _cfg.ORG_SPECIALIST_ORDER:
        spec_model = _mp.resolve_role_model(spec)
        spec_dir = _cfg.WORKSPACES_DIR / spec

        if _fleet.agent_registered(spec):
            ui.success(f"{spec}: already registered")
        else:
            ui.info(f"Creating {spec} agent...")
            spec_dir.mkdir(parents=True, exist_ok=True)
            _fleet.add_agent(spec, spec_model)
            why = _cfg.ROLE_WHY.get(spec, "")
            ui.success(f"{spec}: created ({spec_model} — {why})")

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
                    "sessionKey": _specialist_session_key(spec),
                    "projectKey": "org",
                    "created": datetime.now(UTC).isoformat(),
                },
            )

        # Full workspace contract (SOUL/AGENTS/HEARTBEAT + the runtime's
        # WORKFLOW_AUTO/MEMORY/daily-log set).
        if spec_dir.is_dir():
            _write_specialist_contract_files(spec, spec_dir, _specialist_soul(spec))


_PORTFOLIO_SOUL_TEMPLATE = """# SOUL — Portfolio Manager

**Scope:** org (cross-pod). **Role:** portfolio-manager. **Edits code:** never.

**Session Key:** `{session_key}`

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
    never auto-installed, never a pod member. Idempotent. Gets the same full
    workspace contract as the other org specialists.
    """
    role = _cfg.PORTFOLIO_MANAGER_ROLE
    model = _mp.resolve_role_model(role)
    ws = _cfg.WORKSPACES_DIR / role

    if _fleet.agent_registered(role):
        ui.success(f"{role}: already registered")
    else:
        ui.info(f"Creating {role} agent...")
        ws.mkdir(parents=True, exist_ok=True)
        _fleet.add_agent(role, model)
        ui.success(f"{role}: created ({model} — {_cfg.ROLE_WHY.get(role, '')})")

    if ws.is_dir():
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
                    "sessionKey": _specialist_session_key(role),
                    "projectKey": "org",
                    "created": datetime.now(UTC).isoformat(),
                },
            )
        soul = _PORTFOLIO_SOUL_TEMPLATE.format(session_key=_specialist_session_key(role))
        _write_specialist_contract_files(role, ws, soul)


def run_install(
    want_gates: bool = True, assume_yes: bool = False, want_portfolio: bool = False
) -> int:
    """Bootstrap a docket-native home + specialist agents. Returns the process exit code.

    want_gates:      apply approval routing (on by default; False when the caller
                     passed --no-gates). The tool-call gate itself (policy engine +
                     high-risk command classifier) is always active regardless —
                     see `_step_security`'s docstring.
    assume_yes:      skip the reconfigure/update confirmation prompt (non-interactive).
    want_portfolio:  also provision the opt-in org Portfolio Manager.
    """
    ui.header("Docket Installation")
    ui.console.print()

    if _cfg.FLEET_FILE.is_file():
        ui.info("Existing docket installation detected")
        ui.console.print()

        missing_specialists = [
            s for s in _cfg.ORG_SPECIALIST_ORDER if not _fleet.agent_registered(s)
        ]
        needs_update = (
            [f"specialist agents: {' '.join(missing_specialists)}"] if missing_specialists else []
        )

        if not needs_update:
            ui.success("Docket is fully configured!")
            ui.console.print()
            ui.console.print("Current setup:")
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
    _cfg.SITES_DIR.mkdir(parents=True, exist_ok=True)
    _cfg.LOG_DIR.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        os.chmod(_cfg.DOCKET_HOME, 0o700)
        os.chmod(_cfg.PROJECTS_DIR, 0o700)
    ui.success("Directories created")
    ui.console.print(f"  {_cfg.PROJECTS_DIR}")
    ui.console.print(f"  {_cfg.SITES_DIR}")
    ui.console.print()

    ui.header("Step 3: Configuring the default model")
    _fleet.set_default_model(_cfg.DEFAULT_MODEL)
    ui.success("Default model configured")
    ui.console.print(f"  Default model: {_cfg.DEFAULT_MODEL}")
    ui.console.print()

    ui.header("Step 4: Setting up specialist agents")
    _provision_specialists()
    if want_portfolio:
        ui.console.print()
        ui.info("Provisioning the org Portfolio Manager (--portfolio)...")
        _provision_portfolio_manager()
    ui.console.print()

    ui.header("Step 5: Model authentication")
    auth_missing = _step_auth() != 0
    ui.console.print()

    ui.header("Step 6: Configuring security best practices")
    _step_security(want_gates)
    ui.console.print()

    ui.header("Step 7: Guardrail policies")
    _step_policies()
    ui.console.print()

    _print_summary(auth_missing)
    return 0


def _print_summary(auth_missing: bool) -> None:
    """Closing summary + next steps."""
    ui.header("Installation Complete!")
    ui.console.print()
    ui.console.print("[bold]Next Steps:[/bold]")
    ui.console.print()
    step = 1
    if auth_missing:
        ui.console.print(
            f"  {step}. Store a model-provider credential (agents can't reply without it):"
        )
        ui.console.print("     [green]docket keys add ANTHROPIC_API_KEY[/green]")
        ui.console.print()
        step += 1
    ui.console.print(f"  {step}. Add your first project agent:")
    ui.console.print("     [green]docket add[/green]")
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
    ui.console.print("[bold]Org Specialists (auto-created, shared across projects):[/bold]")
    ui.console.print("  • manager    - Cross-cutting coordination and task queue")
    ui.console.print("  • knowledge  - Memory distillation and patterns")
    ui.console.print("  • security   - Security audits and risk checks")
    ui.console.print()
    ui.console.print("[dim]Code workers (implementer/reviewer/tester) are per-project pod[/dim]")
    ui.console.print("[dim]members — run 'docket add <project>' to create a pod.[/dim]")
    ui.console.print()
    ui.console.print("[bold]Configuration:[/bold]")
    ui.console.print(f"  Fleet registry: {_cfg.FLEET_FILE}")
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
