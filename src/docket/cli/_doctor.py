"""docket doctor — system-wide health checks + auto-fixes.

`run_doctor(json_out)` returns the process exit code: 0 healthy, 1 when
issues are flagged. Each check is its own function, testable in isolation.

All fleet/agent state is read through `core/fleet.py` and `store`; this
module never opens a daemon config file — there is no daemon to have one.
Where a check has no daemon-era equivalent, its own docstring says so and
why (see `_check_dependencies`, `_check_security_gates`, `_doctor_json`).
"""

from __future__ import annotations

import json as _json
import shutil
from typing import Any

import docket.config as _cfg
from docket import ui
from docket.core import fleet as _fleet
from docket.core import memory as _mem
from docket.core import models_policy as _mp
from docket.core import secrets as _secrets
from docket.core.utils import aggregate_cost, gating_cost, project_ids
from docket.edges import store

TEMPLATE_VERSION = _cfg.TEMPLATE_VERSION
RUNAWAY_TURNS_THRESHOLD = _cfg.RUNAWAY_TURNS_THRESHOLD
RUNAWAY_COST_THRESHOLD = _cfg.RUNAWAY_COST_THRESHOLD
KEY_MAX_AGE_DAYS = _cfg.KEY_MAX_AGE_DAYS

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
    "ai-gateway": "AI_GATEWAY_API_KEY",
    "groq": "GROQ_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "xai": "XAI_API_KEY",
    "cerebras": "CEREBRAS_API_KEY",
}

_WORKSPACE_FILES = ("SOUL.md", "AGENTS.md", "TOOLS.md", _mem.HEARTBEAT_FILE)


def _required_workspace_files(aid: str) -> tuple[str, ...]:
    """Workspace files ``aid`` must have — role-aware for pod members.

    Only an Implementer gets TOOLS.md (specs/functional/workspace-structure.spec.md
    requirement 1); other pod roles must never be flagged for lacking it."""
    from docket.core import pod as _pod

    if _pod.pod_of(aid) is not None and _fleet.meta_get(aid, "role", "") != "implementer":
        return tuple(f for f in _WORKSPACE_FILES if f != "TOOLS.md")
    return _WORKSPACE_FILES


def _batch_cost(agent_ids: list[str]) -> dict[str, tuple[str, float, int]]:
    """Return {agent_id: (budgetUsd_str, cost_float, turns_int)} for all agents, using
    recorded spend only -- see ``_batch_gating_cost`` for the budget-warning figure."""
    out: dict[str, tuple[str, float, int]] = {}
    for aid in agent_ids:
        raw = store.read_json(_cfg.meta_path(aid))
        budget = str(raw.get("budgetUsd", "") or "")
        totals = aggregate_cost(aid)
        out[aid] = (budget, totals.cost_usd, totals.turns)
    return out


def _batch_gating_cost(agent_ids: list[str]) -> dict[str, tuple[str, float, bool]]:
    """Return {agent_id: (budgetUsd_str, gating_cost, estimated)} -- the recorded-or-estimated
    figure ``core/utils.gating_cost`` computes, so ``_check_budget`` can fire even though the
    driver's recorded cost is always 0.0."""
    out: dict[str, tuple[str, float, bool]] = {}
    for aid in agent_ids:
        raw = store.read_json(_cfg.meta_path(aid))
        budget = str(raw.get("budgetUsd", "") or "")
        cost_f, estimated = gating_cost(aid)
        out[aid] = (budget, cost_f, estimated)
    return out


def _check_dependencies() -> int:
    """python3 (required) and fzf (optional): docket owns its runtime, so only its
    direct dependencies are probed."""
    issues = 0

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


def _check_project_agents(ids: list[str]) -> int:
    """Per-project workspace files, fleet registration, and channel binding."""
    if not ids:
        ui.console.print()
        ui.warn("No project agents found — run: docket init")
        return 0

    ui.console.print()
    ui.console.print("[bold]Project agents (global fleet across all registered projects):[/bold]")
    issues = 0
    fleet = _fleet.load_fleet()
    registered = {a.id for a in _fleet.list_agents(fleet)}

    for aid in ids:
        ws = _cfg.PROJECTS_DIR / aid
        tg = _fleet.get_binding(aid, cfg=fleet)
        proj_issues: list[str] = []
        for f in _required_workspace_files(aid):
            if not (ws / f).is_file():
                proj_issues.append(f"missing {f}")
        if not (ws / _cfg.META_FILE).is_file():
            proj_issues.append(f"no {_cfg.META_FILE}")
        if aid not in registered:
            proj_issues.append("not registered in fleet")

        if proj_issues:
            ui.console.print(f"[red]✗[/red]   {aid}: {' '.join(proj_issues)}")
            ui.console.print(f"    Fix with: docket maintain {aid} check")
            issues += 1
        elif not tg:
            ui.warn(f"  {aid}: OK, no channel binding  →  docket wire {aid}")
        else:
            ui.success(f"  {aid}: OK  →  group {tg}")
    return issues


def _check_models() -> int:
    """Flag stale/aliased model names across every registered agent's meta."""
    ui.console.print()
    ui.console.print("[bold]Model Configuration[/bold]")
    invalid: list[str] = []
    for a in _fleet.list_agents():
        model = _fleet.meta_get(a.id, "model", "")
        if model in _STALE_MODELS:
            invalid.append(f"{a.id}: {model}")
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

    Advisory — never affects the issue count. Migration/residual-key rules: see
    specs/functional/model-profiles.spec.md. A residual key is a manual cleanup, not a health
    defect."""
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


def _check_dispatch_ledger(do_fix: bool) -> int:
    """TASK_LIST.json (``status: "running"``) vs. the pod Lead's HEARTBEAT.md dispatch ledger —
    must agree.

    ``core/dispatch.py`` keeps the ledger synced mechanically; this check catches whatever slips
    through anyway (an old docket version, a hand-edited file, a crash mid-write). See
    specs/functional/pod-dispatch.spec.md, "Mechanical HEARTBEAT ledger". ``--fix`` re-syncs the
    ledger to exactly what TASK_LIST.json says now — always safe, since the ledger's dispatch
    region is entirely docket-owned and TASK_LIST.json is dispatch's own source of truth."""
    from docket.core import dispatch as _dispatch
    from docket.core import pod as _pod

    pods = _dispatch.dispatchable_pods()
    if not pods:
        return 0

    ui.console.print()
    ui.console.print("[bold]Dispatch task ledger (TASK_LIST.json <-> HEARTBEAT.md):[/bold]")
    issues = 0
    for project in pods:
        lead_id = _pod.member_id(project, "lead")
        ws = _cfg.workspace_dir(lead_id)
        tasks = _dispatch.read_tasks(project)
        running_ids = {str(t["id"]) for t in tasks if t.get("status") == "running"}
        ledger_ids = set(_mem.read_dispatch_task_ids(ws))
        missing = running_ids - ledger_ids
        stale = ledger_ids - running_ids
        if not missing and not stale:
            ui.success(f"  {project}: in sync ({len(running_ids)} running)")
            continue

        detail = []
        if missing:
            detail.append(f"missing from ledger: {', '.join(sorted(missing))}")
        if stale:
            detail.append(f"stale in ledger: {', '.join(sorted(stale))}")
        ui.console.print(f"[red]✗[/red]   {project}: " + "; ".join(detail))
        issues += 1
        if do_fix:
            _mem.sync_dispatch_tasks(ws, tasks)
            ui.success(f"  {project}: ledger re-synced from TASK_LIST.json")
            issues -= 1
        else:
            ui.console.print("    Fix with: docket doctor --fix")
    return issues


def _check_budget(ids: list[str], cost: dict[str, tuple[str, float, bool]]) -> int:
    """Per-agent budget cap usage. ``cost_f`` is ``_batch_gating_cost``'s gating figure
    (recorded spend, or a token-based estimate when recorded is 0.0), rendered with the
    same ``~$… (estimated — no cost recorded)`` label the dispatch gate uses."""
    if not ids:
        return 0
    ui.console.print()
    ui.console.print("[bold]Budget check:[/bold]")
    issues = 0
    for aid in ids:
        budget_s, cost_f, estimated = cost.get(aid, ("", 0.0, False))
        if not budget_s or budget_s == "0":
            ui.dim(f"  {aid}: no cap")
            continue
        budget_f = float(budget_s)
        pct = int((cost_f / budget_f) * 100) if budget_f else 0
        budget_disp = _fmt_num(budget_s)
        cost_disp = (
            f"~${cost_f:.6f} (estimated — no cost recorded)" if estimated else f"${cost_f:.6f}"
        )
        if pct >= 100:
            ui.console.print(
                f"[red]✗[/red]   {aid}: over budget — {pct}% of ${budget_disp} ({cost_disp} used)"
            )
            issues += 1
        elif pct >= 80:
            ui.warn(f"  {aid}: {pct}% of ${budget_disp} ({cost_disp} used)")
        else:
            ui.success(f"  {aid}: {cost_disp} / ${budget_disp} ({pct}%)")
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
        ui.warn(f"  Backend: file — secrets are plaintext at rest in {_secrets.SECRETS_FILE}")
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
    stored = _secrets.secrets_keys()
    missing: list[tuple[str, str, str]] = []
    for aid in ids:
        model = _fleet.meta_get(aid, "model", _cfg.DEFAULT_MODEL)
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
    """Approval-routing/isolation posture + the always-on tool-call gate.

    The gate itself is unconditionally active on every tool call docket dispatches (see
    specs/functional/security-gates.spec.md) — there is no "is it enabled" question left to ask,
    only where an approval prompt routes and whether execution is sandboxed."""
    ui.console.print()
    ui.console.print("[bold]Security gates:[/bold]")

    ui.success("  Tool-call gate: always active (policy engine + high-risk command classifier)")

    r_state, r_mode = _fleet.get_approval_routing()
    if r_state == "on":
        ui.success(f"  Approval routing: on (mode={r_mode or '?'})")
    elif r_state == "off":
        ui.warn("  Approval routing: off — gated prompts have nowhere configured to go")
    else:
        ui.dim("  Approval routing: not configured — docket gates enable")

    iso = _fleet.get_isolation_mode()
    if iso in ("non-main", "all"):
        ui.success(f"  Workspace isolation: {iso} (consulted by the turn loop)")
    else:
        ui.dim("  Workspace isolation: off — docket gates isolate on (needs Docker)")

    return 0


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
        tv = _fleet.meta_get(aid, "templateVersion", "")
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
        sdir = _cfg.WORKSPACES_DIR / spec
        if not sdir.is_dir():
            continue
        if (sdir / _cfg.META_FILE).is_file():
            continue
        sm = _mp.resolve_role_model(spec)
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
        if not _fleet.meta_get(aid, "kind", ""):
            _fleet.meta_set(aid, "kind", "project")
            fixed.append("kind")
        if not _fleet.meta_get(aid, "modelSource", ""):
            _fleet.meta_set(aid, "modelSource", _mp.agent_model_source(aid))
            fixed.append("modelSource")
        if not _fleet.meta_get(aid, "scope", ""):
            _fleet.meta_set(aid, "scope", "project")
            fixed.append("scope")
        if fixed:
            ui.success(f"  {aid}: backfilled {' '.join(fixed)}")
            backfilled += 1

    for role in sorted(_cfg.PROJECT_ROLES):
        if (_cfg.WORKSPACES_DIR / role).is_dir():
            ui.warn(
                f"  {role}: legacy shared specialist — project roles now live in "
                f"pods. Recreate via a pod (docket pod <project> add {role}) and "
                f"remove the global '{role}' workspace."
            )

    if backfilled == 0:
        ui.success("  All agents have kind/role/scope/modelSource metadata")
    return 0


def _check_runtime_contract(ids: list[str]) -> int:
    """Ensure each managed workspace has a current durability contract (``WORKFLOW_AUTO.md``,
    composed into the system prompt every turn).

    Heals a missing or stale/legacy contract (version-marker detected): otherwise the loop
    composes a stale/absent resume contract and a weak model loops offering to create it instead
    of working. Idempotent re-seed from the agent's stored codebase/stack. Advisory — never fails
    the run."""
    from docket.core import memory as _mem

    ui.console.print()
    ui.console.print("[bold]Runtime startup contract:[/bold]")
    healed = 0
    for aid in _managed_workspace_ids(ids):
        ws = _cfg.workspace_dir(aid)
        if not ws.is_dir() or _mem.contract_ok(ws):
            continue
        meta = store.read_json(_cfg.meta_path(aid))
        # A member with a git worktree is gated against the worktree ALONE, so the
        # contract must anchor there -- healing it back to the origin checkout would
        # re-introduce the very unreachable path this heal exists to fix.
        codebase = str(meta.get("worktreeDir") or meta.get("codebase", ""))
        stack = str(meta.get("stack", ""))
        name = str(meta.get("name", "") or aid)
        _mem.seed_contract(ws, project=name, codebase=codebase, stack=stack)
        where = f" (codebase {codebase})" if codebase else " (no codebase in meta)"
        ui.success(f"  {aid}: seeded {_mem.REQUIRED_STARTUP_FILE}{where}")
        healed += 1
    if healed == 0:
        ui.success(f"  All agents have a current {_mem.REQUIRED_STARTUP_FILE}")
    return 0


def _managed_workspace_ids(ids: list[str]) -> list[str]:
    """Project pod members plus any provisioned org specialists — all docket-managed,
    including the opt-in Portfolio Manager (``docket init --portfolio``), never
    auto-installed."""
    specialists = [r for r in _cfg.SPECIALIST_ORDER if _cfg.workspace_dir(r).is_dir()]
    if _cfg.workspace_dir(_cfg.PORTFOLIO_MANAGER_ROLE).is_dir():
        specialists.append(_cfg.PORTFOLIO_MANAGER_ROLE)
    return list(ids) + specialists


def _check_scaffolding(ids: list[str]) -> int:
    """Quarantine self-authoring scaffolding leaking into managed workspaces.

    See specs/functional/workspace-structure.spec.md requirement 5: IDENTITY.md/BOOTSTRAP.md
    fight docket's role-derived SOUL.md, so this moves them to .docket-archive/ (reversible).
    Advisory — never fails."""
    from docket.core import identity as _identity

    ui.console.print()
    ui.console.print("[bold]Agent identity (docket-owned):[/bold]")
    cleaned = 0
    for aid in _managed_workspace_ids(ids):
        ws = _cfg.workspace_dir(aid)
        if not ws.is_dir():
            continue
        archived = _identity.quarantine_scaffolding(ws)
        if archived:
            ui.success(
                f"  {aid}: archived {', '.join(archived)} → .docket-archive/ "
                "(identity is docket-owned; set a display name with 'docket persona')"
            )
            cleaned += 1
    if cleaned == 0:
        ui.success("  No stray self-authored scaffolding in managed workspaces")
    return 0


def _fmt_num(s: str) -> str:
    """Render a numeric string the way Bash printed it ('10' not '10.0')."""
    try:
        f = float(s)
    except ValueError:
        return s
    return str(int(f)) if f == int(f) else str(f)


def _secrets_backend() -> str:
    """Resolve the secrets backend (keyring if requested + available, else file)."""
    if _cfg.secrets_backend_requested() == "keyring" and shutil.which("secret-tool"):
        return "keyring"
    return "file"


def _keys_age_report() -> list[tuple[str, str, str]]:
    """Return [(state, name, detail)] for each stored secret key; state is OK,
    STALE, or UNKNOWN."""
    import datetime as _dt

    keys = _secrets.secrets_keys()
    if not keys:
        return []
    meta = _secrets.secrets_meta()
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


def _doctor_json_fleet_state() -> tuple[int, dict[str, Any], _fleet.FleetConfig | None]:
    """Load the fleet for the JSON report; a load failure is one issue and yields the
    error shape callers below treat as "no fleet"."""
    fleet_data: dict[str, Any]
    fleet = None
    issues = 0
    try:
        fleet = _fleet.load_fleet()
        fleet_data = {
            "ok": True,
            "path": str(_cfg.FLEET_FILE),
            "agents": len(fleet.agents),
            "bindings": len(fleet.bindings),
        }
    except Exception as ex:
        fleet_data = {"ok": False, "path": str(_cfg.FLEET_FILE), "error": str(ex)}
        issues += 1
    return issues, fleet_data, fleet


def _doctor_json_agents(
    ids: list[str], fleet: _fleet.FleetConfig | None
) -> tuple[int, list[dict[str, Any]]]:
    """Per-project workspace/registration issues, JSON shape of `_check_project_agents`."""
    fleet_agent_map = {a.id: a for a in fleet.agents} if fleet else {}
    tg_map: dict[str, str] = {}
    if fleet:
        for b in fleet.bindings:
            if b.channel == "telegram":
                tg_map[b.agent_id] = b.peer_id

    issues = 0
    agents_json: list[dict[str, Any]] = []
    for aid in ids:
        a_issues: list[str] = []
        ws = _cfg.PROJECTS_DIR / aid
        for f in _required_workspace_files(aid):
            if not (ws / f).exists():
                a_issues.append(f"missing {f}")
        if not (ws / _cfg.META_FILE).exists():
            a_issues.append(f"no {_cfg.META_FILE}")
        if aid not in fleet_agent_map:
            a_issues.append("not registered in fleet")
        if a_issues:
            issues += 1
        agents_json.append(
            {"id": aid, "ok": not a_issues, "tg": tg_map.get(aid, ""), "issues": a_issues}
        )
    return issues, agents_json


def _doctor_json_model_config(
    fleet: _fleet.FleetConfig | None,
) -> tuple[int, list[dict[str, str]]]:
    """Stale/aliased model names across every registered agent, JSON shape of `_check_models`."""
    issues = 0
    invalid_models: list[dict[str, str]] = []
    for a in fleet.agents if fleet else []:
        model = _fleet.meta_get(a.id, "model", "")
        if model in _STALE_MODELS:
            invalid_models.append({"id": a.id, "model": model, "suggest": _STALE_MODELS[model]})
            issues += 1
    return issues, invalid_models


def _doctor_json_model_registry() -> dict[str, Any]:
    """Legacy `profiles:` migration state, JSON shape of `_check_legacy_model_registry`.
    Advisory — never contributes to the issue count."""
    legacy_migration_note = _mp.migrate_legacy_profiles()
    return {
        "migrated": legacy_migration_note,
        "residualProfilesKey": _mp.has_residual_profiles_key(),
    }


def _doctor_json_dispatch_ledger() -> tuple[int, list[dict[str, Any]]]:
    """TASK_LIST.json vs. HEARTBEAT.md ledger agreement, JSON shape of `_check_dispatch_ledger`."""
    from docket.core import dispatch as _dispatch_mod
    from docket.core import pod as _pod_ledger_mod

    issues = 0
    dispatch_ledger_results: list[dict[str, Any]] = []
    for project in _dispatch_mod.dispatchable_pods():
        lead_id = _pod_ledger_mod.member_id(project, "lead")
        ws = _cfg.workspace_dir(lead_id)
        tasks = _dispatch_mod.read_tasks(project)
        running_ids = {str(t["id"]) for t in tasks if t.get("status") == "running"}
        ledger_ids = set(_mem.read_dispatch_task_ids(ws))
        missing = sorted(running_ids - ledger_ids)
        stale = sorted(ledger_ids - running_ids)
        ok = not missing and not stale
        if not ok:
            issues += 1
        dispatch_ledger_results.append(
            {"project": project, "ok": ok, "missingFromLedger": missing, "staleInLedger": stale}
        )
    return issues, dispatch_ledger_results


def _doctor_json_budget_runaway(
    ids: list[str],
) -> tuple[int, list[dict[str, Any]], list[dict[str, Any]]]:
    """Per-agent budget cap + runaway session usage, JSON shape of `_check_budget` and
    `_check_runaway`."""
    issues = 0
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
    return issues, budget_results, runaway_results


def _doctor_json_key_hygiene(
    ids: list[str],
) -> tuple[int, list[dict[str, str]], list[dict[str, str]]]:
    """Key age report + missing provider keys, JSON shape of `_check_key_hygiene` and
    `_check_provider_coverage`."""
    keys_list = [{"name": n, "state": s, "detail": d} for s, n, d in _keys_age_report()]

    issues = 0
    stored = _secrets.secrets_keys()
    missing_keys: list[dict[str, str]] = []
    for aid in ids:
        model = str(store.read_json(_cfg.meta_path(aid)).get("model", ""))
        provider = model.split("/")[0] if "/" in model else ""
        expected = _PROVIDER_KEY.get(provider, "")
        if expected and expected not in stored:
            missing_keys.append({"agent": aid, "model": model, "needsKey": expected})
            issues += 1
    return issues, keys_list, missing_keys


def _doctor_json_security() -> dict[str, Any]:
    """Approval-routing/isolation posture, JSON shape of `_check_security_gates`."""
    r_state, r_mode = _fleet.get_approval_routing()
    return {
        "toolCallGate": "always-on",
        "approvalRouting": r_state,
        "routingMode": r_mode,
        "isolation": _fleet.get_isolation_mode(),
    }


def _doctor_json_template_drift(ids: list[str]) -> list[dict[str, Any]]:
    """Template/prompt version drift, JSON shape of `_check_template_version`.
    Advisory — never contributes to the issue count."""
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
    return tmpl_results


def _doctor_json() -> dict[str, Any]:
    """Assemble the machine-readable health report — the docket-owned schema (no
    legacy daemon/gateway keys); channel-binding presence is covered per agent
    below."""
    issues = 0
    ids = project_ids()

    has_py = shutil.which("python3")
    has_fzf = shutil.which("fzf")
    if not has_py:
        issues += 1

    fleet_issues, fleet_data, fleet = _doctor_json_fleet_state()
    issues += fleet_issues

    agents_issues, agents_json = _doctor_json_agents(ids, fleet)
    issues += agents_issues

    model_issues, invalid_models = _doctor_json_model_config(fleet)
    issues += model_issues

    model_registry = _doctor_json_model_registry()

    ledger_issues, dispatch_ledger_results = _doctor_json_dispatch_ledger()
    issues += ledger_issues

    budget_issues, budget_results, runaway_results = _doctor_json_budget_runaway(ids)
    issues += budget_issues

    key_issues, keys_list, missing_keys = _doctor_json_key_hygiene(ids)
    issues += key_issues

    security = _doctor_json_security()
    tmpl_results = _doctor_json_template_drift(ids)

    return {
        "healthy": issues == 0,
        "issues": issues,
        "checks": {
            "python3": {"ok": bool(has_py), "path": has_py or None},
            "fzf": {"available": bool(has_fzf), "path": has_fzf or None},
            "fleet": fleet_data,
            "agents": agents_json,
            "modelConfig": {"ok": not invalid_models, "invalid": invalid_models},
            "modelRegistry": model_registry,
            "dispatchLedger": dispatch_ledger_results,
            "budget": budget_results,
            "runaway": runaway_results,
            "keyHygiene": {"keys": keys_list, "missingForAgents": missing_keys},
            "securityGates": security,
            "templateDrift": tmpl_results,
        },
    }


def run_doctor(json_out: bool = False, do_fix: bool = False) -> int:
    """Run all health checks; return 0 when healthy, 1 when issues are flagged.
    json_out emits the machine-readable report (health probe); do_fix re-syncs
    the dispatch ledger from TASK_LIST.json."""
    if json_out:
        report = _doctor_json()
        print(_json.dumps(report, indent=2))
        return 0 if report.get("healthy") else 1

    ui.header("Docket Doctor — System Health Check")
    ui.console.print()

    ids = project_ids()
    cost = _batch_cost(ids)

    issues = 0
    issues += _check_dependencies()
    issues += _check_project_agents(ids)
    issues += _check_models()
    _check_legacy_model_registry()
    issues += _check_dispatch_ledger(do_fix)
    issues += _check_budget(ids, _batch_gating_cost(ids))
    issues += _check_runaway(ids, cost)
    _check_key_hygiene()
    issues += _check_provider_coverage(ids)
    issues += _check_security_gates()
    _check_template_version(ids)
    _check_metadata_backfill(ids)
    _check_runtime_contract(ids)
    _check_scaffolding(ids)

    ui.console.print()
    if issues == 0:
        ui.success("All checks passed — docket is healthy.")
        return 0
    ui.console.print(f"[red][bold]{issues} critical issue(s) found.[/bold][/red]")
    ui.console.print("  Project issues:  docket repair [id]")
    ui.console.print("  Model issues:    docket doctor --fix")
    return 1
