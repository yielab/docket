"""docket doctor — system-wide health checks + auto-fixes.

`run_doctor(json_out)` returns the process exit
code: 0 when healthy, 1 when the report flags issues. The coordinator wraps
this in a Typer command and raises typer.Exit(code).

Each health check is its own small function so it can be tested in isolation.
All openclaw.json / agent state is read through the ACL (`_oc`) and `store`;
this module never opens openclaw.json directly.
"""

from __future__ import annotations

import contextlib
import json as _json
import os
import shutil
from pathlib import Path
from typing import Any

import docket.config as _cfg
from docket import ui
from docket.core import models_policy as _mp
from docket.core.utils import aggregate_cost, gateway_active, project_ids, restart_gateway
from docket.edges import store
from docket.edges.adapters import openclaw as _oc

TEMPLATE_VERSION = _cfg.TEMPLATE_VERSION
RUNAWAY_TURNS_THRESHOLD = int(os.environ.get("RUNAWAY_TURNS_THRESHOLD", "200"))
RUNAWAY_COST_THRESHOLD = float(os.environ.get("RUNAWAY_COST_THRESHOLD", "20"))
KEY_MAX_AGE_DAYS = int(os.environ.get("DOCKET_KEY_MAX_AGE_DAYS", "90"))

_STALE_MODELS: dict[str, str] = {
    "anthropic/claude-haiku-3-5": "anthropic/claude-haiku-4-5",
    "anthropic/claude-haiku-3": "anthropic/claude-haiku-4-5",
    "anthropic/claude-sonnet-3-5": "anthropic/claude-sonnet-4-6",
}

_PROVIDER_KEY: dict[str, str] = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "google": "GOOGLE_AI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "groq": "GROQ_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "xai": "XAI_API_KEY",
    "cerebras": "CEREBRAS_API_KEY",
}

_WORKSPACE_FILES = ("SOUL.md", "AGENTS.md", "TOOLS.md", "HEARTBEAT.md")


def _batch_cost(agent_ids: list[str]) -> dict[str, tuple[str, float, int]]:
    """Return {agent_id: (budgetUsd_str, cost_float, turns_int)} for all agents.

    Budget comes from .docket-meta.json, cost+turns from the aggregated session index.
    """
    out: dict[str, tuple[str, float, int]] = {}
    for aid in agent_ids:
        raw = store.read_json(_cfg.meta_path(aid))
        budget = str(raw.get("budgetUsd", "") or "")
        totals = aggregate_cost(aid)
        out[aid] = (budget, totals.cost_usd, totals.turns)
    return out


def _check_binaries() -> int:
    """openclaw, python3 (required) and fzf (optional)."""
    issues = 0

    oc = shutil.which("openclaw")
    if oc:
        ui.success(f"openclaw: {oc}")
    else:
        ui.console.print("[red]✗[/red] openclaw not found in PATH")
        ui.console.print("  Install from: https://openclaw.dev")
        issues += 1

    py = shutil.which("python3")
    if py:
        ui.success(f"python3: {py}")
    else:
        ui.console.print("[red]✗[/red] python3 not found — required for JSON operations")
        issues += 1

    fzf = shutil.which("fzf")
    if fzf:
        ui.success(f"fzf: {fzf}")
    else:
        ui.warn("fzf not installed — interactive pickers will use numbered fallback")
        ui.console.print("  Install with: brew install fzf")

    return issues


def _check_config() -> int:
    """openclaw.json presence + JSON validity."""
    if not _cfg.CONFIG_FILE.is_file():
        ui.console.print(f"[red]✗[/red] Config missing: {_cfg.CONFIG_FILE}")
        ui.console.print("  Run: openclaw onboard")
        return 1
    try:
        _oc.load_config()
    except Exception:
        ui.console.print(f"[red]✗[/red] Config JSON is invalid: {_cfg.CONFIG_FILE}")
        ui.console.print("  Run: openclaw doctor")
        return 1
    ui.success(f"Config JSON valid: {_cfg.CONFIG_FILE}")
    return 0


def _check_gateway() -> int:
    """openclaw-gateway.service status."""
    if gateway_active():
        ui.success("Gateway service: active")
        return 0
    ui.console.print("[red]✗[/red] Gateway service: inactive")
    ui.console.print("  Run: systemctl --user start openclaw-gateway.service")
    return 1


def _check_telegram() -> int:
    """Telegram channel enabled (advisory — never fails)."""
    if not _cfg.CONFIG_FILE.is_file():
        return 0
    if _oc.get_telegram_enabled():
        ui.success("Telegram channel: enabled")
    else:
        ui.warn("Telegram channel: disabled or not configured")
        ui.console.print("  Run: openclaw onboard  (to configure Telegram)")
    return 0


def _check_project_agents(ids: list[str]) -> int:
    """Per-project workspace files, registration, and Telegram binding."""
    if not ids:
        ui.console.print()
        ui.warn("No project agents found — run: docket add")
        return 0

    ui.console.print()
    ui.console.print("[bold]Project agents:[/bold]")
    issues = 0
    oc = _oc.load_config()
    registered = {a.id for a in _oc.list_agents(oc)}

    for aid in ids:
        ws = _cfg.PROJECTS_DIR / aid
        tg = _oc.get_binding(aid, cfg=oc)
        proj_issues: list[str] = []
        for f in _WORKSPACE_FILES:
            if not (ws / f).is_file():
                proj_issues.append(f"missing {f}")
        if not (ws / _cfg.META_FILE).is_file():
            proj_issues.append(f"no {_cfg.META_FILE}")
        if aid not in registered:
            proj_issues.append("not registered in openclaw")

        if proj_issues:
            ui.console.print(f"[red]✗[/red]   {aid}: {' '.join(proj_issues)}")
            ui.console.print(f"    Fix with: docket repair {aid}")
            issues += 1
        elif not tg:
            ui.warn(f"  {aid}: OK, no Telegram binding  →  docket wire {aid}")
        else:
            ui.success(f"  {aid}: OK  →  group {tg}")
    return issues


def _check_brave_browser() -> int:
    """Brave-browser process scan for the OpenClaw web UI (advisory).

    Counts `openclaw/browser` processes via ps, warns when the oldest is stale
    (>2 days). Never bumps the issue count (returns 0).
    """
    import subprocess as _sp

    ui.console.print()

    def _ps() -> str:
        try:
            return _sp.run(["ps", "aux"], capture_output=True, text=True, timeout=10).stdout
        except (OSError, _sp.SubprocessError):
            return ""

    procs = [ln for ln in _ps().splitlines() if "openclaw/browser" in ln and "grep" not in ln]
    count = len(procs)
    if count <= 0:
        ui.dim("  Brave browser: not running (OpenClaw will auto-start when needed)")
        return 0

    oldest_etimes = 0
    try:
        out = _sp.run(
            ["ps", "-eo", "pid,etimes,cmd"], capture_output=True, text=True, timeout=10
        ).stdout
    except (OSError, _sp.SubprocessError):
        out = ""
    for ln in out.splitlines():
        if "openclaw/browser" not in ln or "grep" in ln:
            continue
        parts = ln.split()
        if len(parts) >= 2 and parts[1].isdigit():
            oldest_etimes = max(oldest_etimes, int(parts[1]))
    days_old = oldest_etimes // 86400

    if days_old > 2:
        ui.warn(f"Brave browser: {count} processes (oldest: {days_old} days old)")
        ui.dim("  Old browser processes can cause disconnections")
        ui.console.print("  [yellow]Fix: DOCKET_EXPERIMENTAL=1 docket browser restart[/yellow]")
    else:
        ui.success(f"Brave browser: {count} processes running")
    return 0


def _check_today_log() -> int:
    """Today's gateway log presence + disconnect scan (advisory)."""
    import datetime as _dt

    ui.console.print()
    today = _dt.date.today().strftime("%Y-%m-%d")
    log_file = _cfg.LOG_DIR / f"openclaw-{today}.log"
    if log_file.is_file():
        try:
            text = log_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
        lines = text.count("\n")
        ui.success(f"Today's log: {log_file} ({lines} lines)")
        low = text.lower()
        disc = sum(low.count(pat) for pat in ("disconnect", "timeout", "connection"))
        if disc:
            ui.warn(f"  Found {disc} disconnect/timeout events in log")
    else:
        ui.dim(f"  No log today: {log_file}")
        ui.dim("  (Normal if the gateway hasn't received messages yet)")
    return 0


def _check_models() -> int:
    """Flag stale/aliased model names in openclaw.json agents.list."""
    ui.console.print()
    ui.console.print("[bold]Model Configuration[/bold]")
    invalid: list[str] = []
    for a in _oc.list_agents():
        if a.model in _STALE_MODELS:
            invalid.append(f"{a.id}: {a.model}")
    if not invalid:
        ui.success("  All agent models are valid")
        return 0
    ui.console.print("[red]✗[/red]   Found invalid model configurations:")
    for line in invalid:
        ui.console.print(f"    {line}")
    ui.console.print("  Fix with: docket doctor --fix")
    return len(invalid)


def _check_legacy_model_registry() -> int:
    """One-shot ``profiles:`` → ``roles:`` migration report + residual-key warning.

    Advisory — never affects the issue count. Migrating is an automatic fix
    (same pattern as the metadata backfill above); a residual ``profiles:``
    key left behind (because ``roles:`` already existed, so the one-shot
    migration in ``migrate_legacy_profiles`` declined to touch it) is
    something to clean up manually, not a health defect.
    """
    ui.console.print()
    ui.console.print("[bold]Model registry (docket-models.json):[/bold]")
    note = _mp.migrate_legacy_profiles()
    if note:
        ui.success(f"  {note}")
    if _mp.has_residual_profiles_key():
        ui.warn("  Residual 'profiles:' key found (alongside 'roles:') — it is no longer read.")
        ui.dim("    Remove it from docket-models.json; 'roles:' is the source of truth.")
    elif not note:
        ui.success("  No legacy 'profiles:' key")
    return 0


def _check_drift(ids: list[str], do_fix: bool) -> int:
    """Config drift (meta ↔ openclaw.json) on model + sessionKey."""
    if not ids:
        return 0
    ui.console.print()
    ui.console.print("[bold]Config drift check (meta ↔ openclaw.json):[/bold]")

    oc = _oc.load_config()
    oc_agents = {a.id: a for a in _oc.list_agents(oc)}
    drift_agents: list[str] = []
    issues = 0

    for aid in ids:
        meta_path = _cfg.meta_path(aid)
        if not meta_path.is_file():
            continue
        meta = store.read_json(meta_path)
        oc_a = oc_agents.get(aid)
        agent_drift: list[str] = []

        meta_model = str(meta.get("model", ""))
        oc_model = oc_a.model if oc_a else ""
        if meta_model and oc_model and meta_model != oc_model:
            agent_drift.append(f"model meta={meta_model} openclaw={oc_model}")

        meta_sk = str(meta.get("sessionKey", ""))
        oc_sk = oc_a.metadata.session_key if oc_a else ""
        if meta_sk and oc_sk and meta_sk != oc_sk:
            agent_drift.append(f"sessionKey meta={meta_sk} openclaw={oc_sk}")

        if agent_drift:
            ui.console.print(f"[red]✗[/red]   {aid}: drift — {'; '.join(agent_drift)}")
            issues += 1
            drift_agents.append(aid)
        else:
            ui.success(f"  {aid}: in sync")

    if drift_agents:
        if do_fix:
            ui.console.print("  Fixing drift (re-syncing from .docket-meta.json)...")
            for aid in drift_agents:
                fix_model = _oc.meta_get(aid, "model", "")
                fix_sk = _oc.meta_get(aid, "sessionKey", "")
                if fix_model:
                    with contextlib.suppress(Exception):
                        _oc.set_agent_model(aid, fix_model)
                if fix_sk:
                    with contextlib.suppress(Exception):
                        _oc.set_agent_session_key(aid, fix_sk)
                ui.success(f"  {aid}: re-synced")
            with contextlib.suppress(Exception):
                restart_gateway()
            issues -= len(drift_agents)
        else:
            ui.console.print("  Fix with: docket doctor --fix")
    return issues


def _check_budget(ids: list[str], cost: dict[str, tuple[str, float, int]]) -> int:
    """Per-agent budget cap usage."""
    if not ids:
        return 0
    ui.console.print()
    ui.console.print("[bold]Budget check:[/bold]")
    issues = 0
    for aid in ids:
        budget_s, cost_f, _turns = cost.get(aid, ("", 0.0, 0))
        if not budget_s or budget_s == "0":
            ui.dim(f"  {aid}: no cap")
            continue
        budget_f = float(budget_s)
        pct = int((cost_f / budget_f) * 100) if budget_f else 0
        budget_disp = _fmt_num(budget_s)
        if pct >= 100:
            ui.console.print(
                f"[red]✗[/red]   {aid}: over budget — {pct}% of ${budget_disp} (${cost_f:.6f} used)"
            )
            issues += 1
        elif pct >= 80:
            ui.warn(f"  {aid}: {pct}% of ${budget_disp} (${cost_f:.6f} used)")
        else:
            ui.success(f"  {aid}: ${cost_f:.6f} / ${budget_disp} ({pct}%)")
    return issues


def _check_runaway(ids: list[str], cost: dict[str, tuple[str, float, int]]) -> int:
    """Per-agent runaway session detection (high turns or high cost)."""
    if not ids:
        return 0
    ui.console.print()
    ui.console.print("[bold]Runaway session check:[/bold]")
    issues = 0
    for aid in ids:
        _budget, cost_f, turns = cost.get(aid, ("", 0.0, 0))
        runaway = turns > RUNAWAY_TURNS_THRESHOLD or cost_f >= RUNAWAY_COST_THRESHOLD
        if runaway:
            ui.console.print(f"[red]✗[/red]   {aid}: runaway — {turns} turns, ${cost_f:.6f}")
            issues += 1
        else:
            ui.success(f"  {aid}: ok ({turns} turns, ${cost_f:.6f})")
    return issues


def _check_key_hygiene() -> int:
    """Backend + per-key age report (advisory — never fails)."""
    report = _keys_age_report()
    if not report:
        return 0
    ui.console.print()
    ui.console.print("[bold]API key hygiene:[/bold]")
    if _secrets_backend() == "keyring":
        ui.success("  Backend: keyring (values in OS keyring, not plaintext at rest)")
    else:
        ui.warn(
            f"  Backend: file — secrets are plaintext at rest in {_cfg.OPENCLAW_DIR}/secrets.json"
        )
        ui.dim("    For at-rest protection: DOCKET_SECRETS_BACKEND=keyring (libsecret)")
    stale = 0
    for state, name, detail in report:
        if state == "STALE":
            ui.warn(f"  {name}: {detail} — consider: docket keys rotate {name}")
            stale += 1
        elif state == "UNKNOWN":
            ui.dim(f"  {name}: {detail}")
        else:
            ui.success(f"  {name}: {detail}")
    if stale:
        ui.dim(f"  Rotate keys older than {KEY_MAX_AGE_DAYS} days")
    return 0


def _check_provider_coverage(ids: list[str]) -> int:
    """Warn (and count) when an agent's model provider has no stored key."""
    stored = _oc.secrets_keys()
    missing: list[tuple[str, str, str]] = []
    for aid in ids:
        model = _oc.meta_get(aid, "model", _cfg.DEFAULT_MODEL)
        provider = model.split("/")[0] if "/" in model else ""
        expected = _PROVIDER_KEY.get(provider, "")
        if not expected:
            continue
        if expected not in stored:
            missing.append((aid, model, expected))
    if not missing:
        return 0
    ui.console.print()
    ui.console.print("[bold]Provider key coverage:[/bold]")
    for aid, model, expected in missing:
        ui.console.print(f"[red]✗[/red]   Missing key: {aid} ({model}) — needs {expected}")
        ui.console.print(f"    Add with: docket keys add {expected}")
    return len(missing)


def _check_security_gates() -> int:
    """Config-perms hardening + daemon gate/audit/routing/isolation summary."""
    ui.console.print()
    ui.console.print("[bold]Security gates:[/bold]")
    issues = 0

    audit = _oc.security_audit_report()

    cfg_mode = _oc.get_config_perms()
    if cfg_mode and cfg_mode[-2:] != "00":
        ui.console.print(
            f"[red]✗[/red]   Config group/other-accessible (mode {cfg_mode}): {_cfg.CONFIG_FILE}"
        )
        ui.console.print(
            "    Another local user could change tool/auth policy. "
            f'Fix: chmod 600 "{_cfg.CONFIG_FILE}"'
        )
        issues += 1
    elif cfg_mode:
        ui.success(f"  Config perms: {cfg_mode} (owner-only)")

    gs_state, gs_policy, gs_counts = _oc.security_gate_report()
    if gs_state == "OK":
        ui.success(f"  Exec approvals: {gs_policy} ({gs_counts})")
    elif gs_state == "OPEN":
        ui.warn(f"  Exec approvals: {gs_policy} — host exec is ungated ({gs_counts})")
    elif gs_state == "UNSET":
        ui.warn("  Exec approvals: not configured — gates inactive")
        ui.dim("    Enable via docket gates enable (spec: specs/functional/security-gates.spec.md)")
    else:
        ui.dim(f"  Exec approvals: {gs_policy or 'status unavailable'}")

    r_state, r_mode = _oc.get_approval_routing()
    if r_state == "on":
        ui.success(f"  Approval routing: on (mode={r_mode or '?'})")
    elif r_state == "off":
        if gs_state == "OK":
            ui.warn("  Approval routing: off — gated prompts won't reach chat")
    else:
        if gs_state == "OK":
            ui.dim("  Approval routing: not configured — docket gates enable")

    iso = _oc.get_isolation_mode()
    if iso in ("non-main", "all"):
        ui.success(f"  Workspace isolation: {iso} (Docker sandbox)")
    else:
        ui.dim("  Workspace isolation: off — docket gates isolate on (needs Docker)")

    if audit.available:
        if audit.critical > 0:
            ui.console.print(
                f"[red]✗[/red]   openclaw security audit: {audit.critical} critical, "
                f"{audit.warn} warning(s)"
            )
            issues += audit.critical
            for finding in audit.findings:
                ui.console.print(f"    [red]•[/red] {finding.title}")
                if finding.remediation:
                    ui.dim(f"      fix: {finding.remediation}")
            ui.dim("    Remediate: openclaw security audit --fix")
        elif audit.warn > 0:
            ui.warn(f"  openclaw security audit: {audit.warn} warning(s), 0 critical")
            ui.dim("    Details: openclaw security audit")
        else:
            ui.success("  openclaw security audit: clean")
    return issues


def _check_template_version(ids: list[str]) -> int:
    """Template/prompt version drift (advisory — never fails)."""
    if not ids:
        return 0
    ui.console.print()
    ui.console.print(f"[bold]Template version (current: v{TEMPLATE_VERSION}):[/bold]")
    from docket.core import pod as _pod

    drift = 0
    for aid in ids:
        # Pod members use their own template scheme (POD_TEMPLATE_VERSION) and are
        # NOT rebuilt via `maintain rebuild` (that regenerates single-agent
        # templates and would clobber the pod-role SOULs). Skip them here.
        if _pod.pod_of(aid) is not None:
            continue
        tv = _oc.meta_get(aid, "templateVersion", "")
        if not tv:
            ui.warn(f"  {aid}: unstamped (pre-versioning) — docket maintain {aid} rebuild")
            drift += 1
        elif tv != str(TEMPLATE_VERSION):
            ui.warn(
                f"  {aid}: on v{tv}, current v{TEMPLATE_VERSION} — docket maintain {aid} rebuild"
            )
            drift += 1
        else:
            ui.success(f"  {aid}: v{tv} (current)")
    if drift:
        ui.dim("  Rebuild regenerates prompts from metadata; edit metadata first if needed.")
    return 0


def _check_metadata_backfill(ids: list[str]) -> int:
    """Backfill kind/role/modelSource taxonomy for specialists + project agents."""
    ui.console.print()
    ui.console.print("[bold]Agent metadata (taxonomy):[/bold]")
    backfilled = 0

    for spec in _cfg.SPECIALIST_ORDER:
        sdir = _cfg.OPENCLAW_DIR / "workspaces" / spec
        if not sdir.is_dir():
            continue
        if (sdir / _cfg.META_FILE).is_file():
            continue
        oc_a = _oc.get_agent(spec)
        sm = oc_a.model if oc_a and oc_a.model else _mp.resolve_role_model(spec)
        meta = {
            "kind": "specialist",
            "role": spec,
            "name": spec,
            "model": sm,
            "modelSource": _mp.agent_model_source(spec),
        }
        path = sdir / _cfg.META_FILE
        store.write_json(path, meta)
        ui.success(f"  {spec}: meta backfilled (kind=specialist, model={sm})")
        backfilled += 1

    for aid in ids:
        fixed: list[str] = []
        if not _oc.meta_get(aid, "kind", ""):
            _oc.meta_set(aid, "kind", "project")
            fixed.append("kind")
        if not _oc.meta_get(aid, "modelSource", ""):
            _oc.meta_set(aid, "modelSource", _mp.agent_model_source(aid))
            fixed.append("modelSource")
        if not _oc.meta_get(aid, "scope", ""):
            _oc.meta_set(aid, "scope", "project")
            fixed.append("scope")
        if fixed:
            ui.success(f"  {aid}: backfilled {' '.join(fixed)}")
            backfilled += 1

    for role in sorted(_cfg.PROJECT_ROLES):
        if (_cfg.OPENCLAW_DIR / "workspaces" / role).is_dir():
            ui.warn(
                f"  {role}: legacy shared specialist — project roles now live in "
                f"pods. Recreate via a pod (docket pod <project> add {role}) and "
                f"remove the global '{role}' workspace."
            )

    if backfilled == 0:
        ui.success("  All agents have kind/role/scope/modelSource metadata")
    return 0


def _check_eval_results() -> int:
    """Eval-results model-tier recommendations (advisory).

    When tests/evals/results/*.jsonl exist, prints per-role minimum passing tier
    from the latest results file. Purely advisory (returns 0 — never affects the
    issue count).
    """
    import collections

    results_dir = _eval_results_dir()
    if results_dir is None:
        return 0
    files = sorted(results_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        return 0
    latest = files[0]

    ui.console.print()
    results_date = latest.name[: -len(".jsonl")]
    ui.console.print(f"[bold]Eval results ({results_date}):[/bold]")

    recs: list[dict[str, Any]] = []
    try:
        for line in latest.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            with contextlib.suppress(Exception):
                recs.append(_json.loads(line))
    except OSError:
        recs = []
    if not recs:
        ui.console.print("  (no records in results file)")
        return 0

    tier_order = {"economy": 0, "standard": 1, "premium": 2}
    by_role: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for r in recs:
        by_role[str(r["role"])].append(r)

    for role, results in sorted(by_role.items()):
        passing = [r for r in results if r.get("passed")]
        failing = [r for r in results if not r.get("passed")]
        if not passing and not failing:
            continue
        if not passing:
            ui.console.print(f"  {role}: all {len(failing)} run(s) FAILED")
            continue
        min_tier = min(passing, key=lambda r: tier_order.get(str(r.get("tier", "standard")), 1))[
            "tier"
        ]
        avg_cost = sum(float(r.get("costUsd", 0)) for r in passing) / len(passing)
        current_tier = results[-1].get("tier", "?")
        if tier_order.get(str(min_tier), 1) < tier_order.get(str(current_tier), 1):
            ui.console.print(
                f"  [yellow]⚠[/yellow]  {role}: passes on a cheaper model class "
                f"({min_tier}, avg ${avg_cost:.4f}/run) — docket models set {role} <provider/model>"
            )
        else:
            ui.console.print(
                f"  [green]✓[/green]  {role}: {min_tier} minimum "
                f"(avg ${avg_cost:.4f}/run, {len(passing)}/{len(results)} passed)"
            )
    ui.dim("  Re-run: DOCKET_EVAL_LIVE=1 docket eval")
    return 0


def _eval_results_dir() -> Path | None:
    """Locate tests/evals/results/ — repo root via DOCKET_CLI_ROOT or package layout."""
    root = Path(os.environ.get("DOCKET_CLI_ROOT", ""))
    if not root.is_dir():
        # src/docket/cli/_doctor.py → parents[3] == repo root.
        root = Path(__file__).resolve().parents[3]
    results = root / "tests" / "evals" / "results"
    return results if results.is_dir() else None


def _fmt_num(s: str) -> str:
    """Render a numeric string the way Bash printed it ('10' not '10.0')."""
    try:
        f = float(s)
    except ValueError:
        return s
    return str(int(f)) if f == int(f) else str(f)


def _secrets_backend() -> str:
    """Resolve the secrets backend (keyring if requested + available, else file)."""
    if os.environ.get("DOCKET_SECRETS_BACKEND") == "keyring" and shutil.which("secret-tool"):
        return "keyring"
    return "file"


def _keys_age_report() -> list[tuple[str, str, str]]:
    """Return [(state, name, detail)] for each stored secret key.

    state: OK | STALE | UNKNOWN.
    """
    import datetime as _dt

    keys = _oc.secrets_keys()
    if not keys:
        return []
    meta = _oc.secrets_meta()
    now = _dt.datetime.now(_dt.UTC)

    def parse(ts: str) -> _dt.datetime | None:
        try:
            return _dt.datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=_dt.UTC)
        except ValueError:
            return None

    out: list[tuple[str, str, str]] = []
    for key in sorted(keys):
        entry = meta.get(key) or {}
        rotated = bool(entry.get("rotated_at"))
        ref = entry.get("rotated_at") or entry.get("added_at")
        dt = parse(str(ref)) if ref else None
        if dt is None:
            out.append(("UNKNOWN", key, "age unknown (added before tracking)"))
            continue
        age = max(0, (now - dt).days)
        verb = "since rotation" if rotated else "old"
        state = "STALE" if age >= KEY_MAX_AGE_DAYS else "OK"
        out.append((state, key, f"{age}d {verb}"))
    return out


def _doctor_json() -> dict[str, Any]:
    """Assemble the machine-readable health report."""
    issues = 0
    ids = project_ids()

    has_oc = shutil.which("openclaw")
    has_py = shutil.which("python3")
    has_fzf = shutil.which("fzf")
    if not has_oc:
        issues += 1
    if not has_py:
        issues += 1

    config_data: dict[str, Any]
    config_ok = False
    oc = None
    try:
        oc = _oc.load_config()
        config_ok = True
        config_data = {
            "ok": True,
            "path": str(_cfg.CONFIG_FILE),
            "agents": len(oc.agents.items),
            "bindings": len(oc.bindings),
        }
    except Exception as ex:
        config_data = {"ok": False, "path": str(_cfg.CONFIG_FILE), "error": str(ex)}
        issues += 1

    gw_ok = gateway_active()
    gw_status = "active" if gw_ok else "inactive"
    if not gw_ok:
        issues += 1

    tg_enabled = _oc.get_telegram_enabled() if config_ok else False

    oc_agent_map = {a.id: a for a in oc.agents.items} if oc else {}
    tg_map: dict[str, str] = {}
    if oc:
        for b in oc.bindings:
            if b.match.channel == "telegram":
                tg_map[b.agent_id] = b.match.peer.id

    agents_json: list[dict[str, Any]] = []
    for aid in ids:
        a_issues: list[str] = []
        ws = _cfg.PROJECTS_DIR / aid
        for f in _WORKSPACE_FILES:
            if not (ws / f).exists():
                a_issues.append(f"missing {f}")
        if not (ws / _cfg.META_FILE).exists():
            a_issues.append(f"no {_cfg.META_FILE}")
        if aid not in oc_agent_map:
            a_issues.append("not registered in openclaw")
        if a_issues:
            issues += 1
        agents_json.append(
            {"id": aid, "ok": not a_issues, "tg": tg_map.get(aid, ""), "issues": a_issues}
        )

    invalid_models: list[dict[str, str]] = []
    for a in oc.agents.items if oc else []:
        if a.model in _STALE_MODELS:
            invalid_models.append({"id": a.id, "model": a.model, "suggest": _STALE_MODELS[a.model]})
            issues += 1

    legacy_migration_note = _mp.migrate_legacy_profiles()
    model_registry = {
        "migrated": legacy_migration_note,
        "residualProfilesKey": _mp.has_residual_profiles_key(),
    }

    drift_results: list[dict[str, Any]] = []
    for aid in ids:
        meta = store.read_json(_cfg.meta_path(aid))
        meta_model = str(meta.get("model", ""))
        if not meta_model:
            continue
        oc_a = oc_agent_map.get(aid)
        oc_model = oc_a.model if oc_a else ""
        synced = not oc_model or meta_model == oc_model
        if not synced:
            issues += 1
        drift_results.append(
            {"id": aid, "metaModel": meta_model, "ocModel": oc_model, "synced": synced}
        )

    cost = _batch_cost(ids)
    budget_results: list[dict[str, Any]] = []
    runaway_results: list[dict[str, Any]] = []
    for aid in ids:
        budget_s, cost_f, turns = cost[aid]
        budget_f = float(budget_s) if budget_s and budget_s != "0" else None
        if budget_f:
            pct = int(cost_f / budget_f * 100)
            if pct >= 100:
                issues += 1
            budget_results.append(
                {
                    "id": aid,
                    "costUsd": round(cost_f, 6),
                    "budgetUsd": budget_f,
                    "pct": pct,
                    "ok": pct < 100,
                }
            )
        else:
            budget_results.append(
                {"id": aid, "costUsd": round(cost_f, 6), "budgetUsd": None, "ok": True}
            )
        runaway = turns > RUNAWAY_TURNS_THRESHOLD or cost_f >= RUNAWAY_COST_THRESHOLD
        if runaway:
            issues += 1
        runaway_results.append(
            {"id": aid, "turns": turns, "costUsd": round(cost_f, 6), "ok": not runaway}
        )

    keys_list = [{"name": n, "state": s, "detail": d} for s, n, d in _keys_age_report()]

    stored = _oc.secrets_keys()
    missing_keys: list[dict[str, str]] = []
    for aid in ids:
        model = str(store.read_json(_cfg.meta_path(aid)).get("model", ""))
        provider = model.split("/")[0] if "/" in model else ""
        expected = _PROVIDER_KEY.get(provider, "")
        if expected and expected not in stored:
            missing_keys.append({"agent": aid, "model": model, "needsKey": expected})
            issues += 1

    cfg_mode = _oc.get_config_perms()
    perms_ok = not (cfg_mode and cfg_mode[-2:] != "00")
    if not perms_ok:
        issues += 1
    gs_state, gs_policy, gs_counts = _oc.security_gate_report()
    r_state, r_mode = _oc.get_approval_routing()
    security = {
        "configPerms": cfg_mode or None,
        "permsOk": perms_ok,
        "gateState": gs_state,
        "policy": gs_policy,
        "gateCounts": gs_counts,
        "approvalRouting": r_state,
        "routingMode": r_mode,
        "isolation": _oc.get_isolation_mode(),
    }

    from docket.core import pod as _pod_mod

    tmpl_results: list[dict[str, Any]] = []
    for aid in ids:
        # Pod members use their own template scheme — exclude from single-agent drift.
        if _pod_mod.pod_of(aid) is not None:
            continue
        tv_raw = store.read_json(_cfg.meta_path(aid)).get("templateVersion")
        tv_i = int(tv_raw) if tv_raw is not None else None
        tmpl_results.append(
            {
                "id": aid,
                "agentVersion": tv_i,
                "currentVersion": TEMPLATE_VERSION,
                "ok": tv_i == TEMPLATE_VERSION,
            }
        )

    return {
        "healthy": issues == 0,
        "issues": issues,
        "checks": {
            "openclaw": {"ok": bool(has_oc), "path": has_oc or None},
            "python3": {"ok": bool(has_py), "path": has_py or None},
            "fzf": {"available": bool(has_fzf), "path": has_fzf or None},
            "config": config_data,
            "gateway": {"ok": gw_ok, "status": gw_status},
            "telegram": {"enabled": tg_enabled},
            "agents": agents_json,
            "modelConfig": {"ok": not invalid_models, "invalid": invalid_models},
            "modelRegistry": model_registry,
            "drift": drift_results,
            "budget": budget_results,
            "runaway": runaway_results,
            "keyHygiene": {"keys": keys_list, "missingForAgents": missing_keys},
            "securityGates": security,
            "templateDrift": tmpl_results,
        },
    }


def run_doctor(json_out: bool = False, do_fix: bool = False) -> int:
    """Run all health checks. Return 0 when healthy, 1 when issues are flagged.

    json_out: emit the machine-readable report and use it as a health probe.
    do_fix:   auto-fix config drift (re-sync from .docket-meta.json).
    """
    if json_out:
        report = _doctor_json()
        print(_json.dumps(report, indent=2))
        return 0 if report.get("healthy") else 1

    ui.header("Docket Doctor — System Health Check")
    ui.console.print()

    ids = project_ids()
    cost = _batch_cost(ids)

    issues = 0
    issues += _check_binaries()
    issues += _check_config()
    issues += _check_gateway()
    issues += _check_telegram()
    issues += _check_project_agents(ids)
    _check_brave_browser()
    _check_today_log()
    issues += _check_models()
    _check_legacy_model_registry()
    issues += _check_drift(ids, do_fix)
    issues += _check_budget(ids, cost)
    issues += _check_runaway(ids, cost)
    _check_key_hygiene()
    issues += _check_provider_coverage(ids)
    issues += _check_security_gates()
    _check_template_version(ids)
    _check_metadata_backfill(ids)
    _check_eval_results()

    ui.console.print()
    if issues == 0:
        ui.success("All checks passed — docket is healthy.")
        return 0
    ui.console.print(f"[red][bold]{issues} critical issue(s) found.[/bold][/red]")
    ui.console.print("  Project issues:  docket repair [id]")
    ui.console.print("  Gateway issues:  openclaw doctor")
    ui.console.print("  Model issues:    docket doctor --fix")
    return 1
