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
from urllib.parse import urlsplit

import docket.config as _cfg
from docket import ui
from docket.core import channel as _channel
from docket.core import exporter as _exporter
from docket.core import fleet as _fleet
from docket.core import mcp_tools as _mcp_tools
from docket.core import memory as _mem
from docket.core import models_policy as _mp
from docket.core import policy as _pol
from docket.core import secrets as _secrets
from docket.core.utils import aggregate_cost, gating_cost, project_ids
from docket.edges import store
from docket.edges.adapters import system as _sys

TEMPLATE_VERSION = _cfg.TEMPLATE_VERSION
RUNAWAY_TURNS_THRESHOLD = _cfg.RUNAWAY_TURNS_THRESHOLD
RUNAWAY_COST_THRESHOLD = _cfg.RUNAWAY_COST_THRESHOLD
KEY_MAX_AGE_DAYS = _cfg.KEY_MAX_AGE_DAYS

_WORKSPACE_FILES = ("SOUL.md", "AGENTS.md", "TOOLS.md", _mem.HEARTBEAT_FILE)


def _expected_credential(provider: str) -> str:
    """The provider's first credential name from the catalog, or ``""`` when *provider* is
    unknown or needs none -- the single reader both `_check_provider_coverage` and its JSON
    twin use, replacing the old hand-kept ``_PROVIDER_KEY`` table."""
    from docket.core import provider as _prov

    spec = _prov.load_catalog().get(provider)
    if spec is None or not spec.auth.credentials:
        return ""
    return spec.auth.credentials[0]


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
    """python3 (required): docket owns its runtime, so only its direct dependencies are
    probed."""
    issues = 0

    py = shutil.which("python3")
    if py:
        ui.success(f"python3: {py}")
    else:
        ui.console.print("[red]✗[/red] python3 not found — required for JSON operations")
        issues += 1

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


def _check_model_registry_entries() -> int:
    """Flag every malformed ``docket-models.json`` entry (unknown rank anchor/role, or a
    bad model id) that ``load_registry`` silently ignores at read time -- naming the file,
    key, and reason. Read-only: never edits the registry."""
    ui.console.print()
    ui.console.print("[bold]Model registry entries (docket-models.json):[/bold]")
    problems = _mp.find_registry_problems()
    if not problems:
        ui.success("  All registry entries are well-formed")
        return 0
    ui.console.print("[red]✗[/red]   Found malformed docket-models.json entries:")
    for key, reason in problems:
        ui.console.print(f"    {key}: {reason}")
    return len(problems)


def _check_archetype_overlay() -> int:
    """Flag every malformed ``docket-roles.json`` overlay entry that ``load_registry``
    silently skips at read time -- naming the role and the ``ArchetypeError`` reason.
    Read-only: never edits the overlay."""
    from docket.core import archetypes as _arch

    ui.console.print()
    ui.console.print("[bold]Role archetype overlay (docket-roles.json):[/bold]")
    problems = _arch.find_overlay_problems()
    if not problems:
        ui.success("  All overlay entries are well-formed")
        return 0
    ui.console.print("[red]✗[/red]   Found malformed docket-roles.json entries:")
    for role, reason in problems:
        ui.console.print(f"    {role}: {reason}")
    return len(problems)


def _check_schedule_config() -> int:
    """Flag every ``docket-schedules.json`` entry ``is_schedule_due`` would silently treat
    as never-due -- naming the file, project key, and reason. Read-only:
    never edits the schedules file (use ``docket pod <p> config set/unset schedule``)."""
    from docket.core import schedule as _sched

    ui.console.print()
    ui.console.print("[bold]Schedules (docket-schedules.json):[/bold]")
    problems = _sched.find_schedule_problems(_cfg.SCHEDULE_FILE)
    if not problems:
        ui.success("  All schedules are well-formed")
        return 0
    ui.console.print("[red]✗[/red]   Found schedule(s) that will never fire:")
    for key, reason in problems:
        ui.console.print(f"    {key}: {reason}")
    return len(problems)


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
        expected = _expected_credential(provider)
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


def _provider_catalog_problems() -> list[tuple[str, str]]:
    """Every global provider document that fails `load_provider_document`'s own
    validation -- `load_catalog` silently skips these at read time. Returns
    (name, "field: message") pairs. Read-only: never edits the catalog."""
    from pydantic import ValidationError

    from docket.core.provider import ProviderSpec

    raw = store.read_json(_cfg.PROVIDERS_FILE)
    providers = raw.get("providers") if isinstance(raw, dict) else None
    problems: list[tuple[str, str]] = []
    if not isinstance(providers, dict):
        return problems
    for name, block in providers.items():
        if not isinstance(block, dict):
            problems.append((str(name), "not a mapping"))
            continue
        try:
            ProviderSpec.model_validate(block)
        except ValidationError as exc:
            first = exc.errors()[0]
            field = ".".join(str(p) for p in first["loc"]) if first["loc"] else ""
            problems.append((str(name), f"{field}: {first['msg']}"))
    return problems


def _check_provider_catalog() -> int:
    """Flag every malformed global provider document -- naming the file, provider
    name and failing field, the way `_check_archetype_overlay` names a malformed
    role. Read-only: never edits the catalog."""
    ui.console.print()
    ui.console.print("[bold]Provider catalog (docket-providers.json):[/bold]")
    problems = _provider_catalog_problems()
    if not problems:
        ui.success("  All provider documents are well-formed")
        return 0
    ui.console.print("[red]✗[/red]   Found malformed docket-providers.json entries:")
    for name, reason in problems:
        ui.console.print(f"    {_cfg.PROVIDERS_FILE}: {name}: {reason}")
    return len(problems)


_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def _check_exporters() -> int:
    """Warn for every enabled exporter whose health shows a failure since its last success,
    plus informational lines (not counted as issues) for a `conversation`/`full` exporter
    reaching a non-loopback host."""
    ui.console.print()
    ui.console.print("[bold]Exporters:[/bold]")
    catalog = _exporter.load_catalog()
    enabled = sorted(name for name, spec in catalog.entries.items() if spec.enabled)
    issues = 0
    if not enabled:
        ui.dim("  No exporters enabled")
    else:
        health = _exporter.read_health()
        for name in enabled:
            spec = catalog.entries[name]
            record = health.get(name, {})
            failed = int(record.get("failed") or 0)
            if failed > 0:
                ui.warn(f"  {name}: {failed} failed export(s) — docket exporters test {name}")
                issues += 1
            else:
                ui.success(f"  {name}: healthy")
            if spec.privacy_label in ("conversation", "full"):
                host = urlsplit(spec.endpoint).hostname or spec.endpoint
                if host not in _LOOPBACK_HOSTS:
                    ui.info(f"  {name}: privacy '{spec.privacy_label}' shares content with {host}")
    return issues


def _check_notifications(ids: list[str]) -> int:
    """Warn when no enabled channel delivers beyond the console -- a parked task would wait
    unseen. Counted as an issue only once a project agent exists to park anything."""
    ui.console.print()
    ui.console.print("[bold]Notifications:[/bold]")
    delivering = _channel.load_catalog().delivering()
    text = _channel.unreached_warning(delivering)
    if text is None:
        ui.success(f"  Delivering: {', '.join(delivering)}")
        return 0
    if ids:
        ui.warn(f"  {text}")
        return 1
    ui.dim(f"  {text}")
    return 0


def _unjailed_mcp_servers() -> list[dict[str, str]]:
    """Every server declared ``isolate: false``: the global registry's (``pod`` empty), then each
    pod's own pod-scoped ones."""
    from docket.core import dispatch as _dispatch

    found = [{"name": s.name, "pod": ""} for s in _mcp_tools.load_mcp_servers() if not s.isolate]
    taken = {s.name for s in _mcp_tools.load_mcp_servers()}
    for pod in _dispatch.dispatchable_pods():
        found += [
            {"name": s.name, "pod": pod}
            for s in _mcp_tools.load_pod_mcp_servers(pod)
            if s.name not in taken and not s.isolate
        ]
    return found


def _docker_image_has_git() -> bool | None:
    """The jail image's git probe, only when docker is the backend in use and isolation is not off;
    None when it does not apply."""
    if not _fleet.get_isolation_enabled():
        return None
    if _sys.sandbox_availability().backend != "docker":
        return None
    return _sys.docker_image_has_git()


def _check_security_gates() -> int:
    """Isolation posture + the always-on tool-call gate.

    The gate itself is unconditionally active on every tool call docket dispatches (see
    specs/functional/security-gates.spec.md) — there is no "is it enabled" question left to ask,
    only whether execution is sandboxed."""
    ui.console.print()
    ui.console.print("[bold]Security gates:[/bold]")

    ui.success("  Tool-call gate: always active (policy engine + high-risk command classifier)")

    state = _fleet.get_isolation_state()
    enabled = _fleet.get_isolation_enabled()
    if not enabled:
        ui.dim(
            f"  Workspace isolation: {'off (explicit)' if state == 'off' else state} -- "
            "docket gates isolate on (needs bubblewrap or docker)"
        )
    else:
        backend = _sys.sandbox_availability().backend
        if backend == "none":
            ui.warn(
                f"  Workspace isolation: {state}, but no backend is usable -- turns will be "
                "refused. Install bubblewrap or start docker, or docket gates isolate off"
            )
        else:
            ui.success(f"  Workspace isolation: {state}, backend {backend}")
            if _docker_image_has_git() is False:
                ui.warn(
                    f"  Docker jail image {_cfg.SANDBOX_DOCKER_IMAGE} has no git -- a jailed "
                    "commit will fail. Set DOCKET_SANDBOX_IMAGE=<an image with git>"
                )

    net_mode = _fleet.get_network_mode()
    if net_mode == "none":
        if not enabled:
            ui.warn(
                "  Network: none (global), but isolation is off -- turns will be refused. "
                "docket gates isolate on, or docket gates network open"
            )
        else:
            ui.success("  Network: none (global) -- jailed tool calls have no network")
    else:
        ui.dim(
            "  Network: open (default) -- docket gates network none to cut the sandbox's network"
        )

    unjailed = [
        f"{s['name']} (pod {s['pod']})" if s["pod"] else s["name"] for s in _unjailed_mcp_servers()
    ]
    if unjailed and enabled:
        ui.warn(f"  MCP servers declared isolate: false (start on the host): {', '.join(unjailed)}")

    return 0


def _check_policies() -> int:
    """Guardrail policy store integrity: flags any file the evaluator would fail closed on,
    through the same ``core.policy`` validation, so doctor can never call a store healthy that
    a live turn would block on (security-gates.spec.md, policy engine requirement 7)."""
    ui.console.print()
    ui.console.print("[bold]Guardrail policies:[/bold]")
    files = _pol.policy_files()
    if not files:
        ui.dim("  No policies installed — docket policies init")
        return 0
    broken = 0
    for f in files:
        err = _pol.validate_policy(f)
        if err:
            broken += 1
            ui.console.print(f"[red]✗[/red]   {f.name}: broken — every matching call fails closed")
            ui.console.print(f"    {err}")
    if broken:
        ui.console.print("  Fix or remove the file(s); check with: docket policies validate")
        return broken
    ui.success(f"  {len(files)} policy file(s) valid")
    return 0


def _check_pod_config_overlays() -> int:
    """Every pod's own config overlay (``<pod>/config/``) -- the layer
    ``_check_archetype_overlay``/``_check_policies`` never look at. Names the pod plus
    the role/file and reason for a malformed role overlay or invalid policy file."""
    from docket.core import archetypes as _arch
    from docket.core import dispatch as _dispatch

    ui.console.print()
    ui.console.print("[bold]Pod config overlays (<pod>/config/):[/bold]")
    pods = _dispatch.dispatchable_pods()
    if not pods:
        ui.dim("  No pods provisioned")
        return 0

    # Subtract the global-file problems so a pre-existing global overlay/policy
    # problem (already reported above) is never re-counted once per pod.
    global_role_problems = set(_arch.find_overlay_problems())
    global_policy_files = set(_pol.policy_files())

    broken = 0
    for project in pods:
        pod_role_problems = [
            p for p in _arch.find_overlay_problems(project) if p not in global_role_problems
        ]
        for role, reason in pod_role_problems:
            broken += 1
            ui.console.print(f"[red]✗[/red]   {project}: role {role}: {reason}")

        for f in _pol.policy_files(project):
            if f in global_policy_files:
                continue
            err = _pol.validate_policy(f)
            if err:
                broken += 1
                ui.console.print(f"[red]✗[/red]   {project}: policy {f.name}: {err}")

    if broken == 0:
        ui.success("  All pod overlay entries and policy files are well-formed")
    return broken


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


def _check_pod_sync(ids: list[str]) -> int:
    """Flag pod members whose managed files drifted from the current archetype +
    metadata -- the pod counterpart of ``_check_template_version``, which skips pod
    members outright. Advisory; ``docket pod <project> sync`` re-renders."""
    from docket.core import pod as _pod
    from docket.core import pod_provisioning as _pp

    member_ids = [aid for aid in ids if _pod.pod_of(aid) is not None]
    if not member_ids:
        return 0
    ui.console.print()
    ui.console.print("[bold]Pod member templates:[/bold]")
    stale = 0
    for aid in member_ids:
        status = _pp.member_sync_status(aid)
        if status is None:
            continue
        if status.stale:
            stale += 1
            ui.console.print(
                f"[red]✗[/red]   {aid}: stale (v{status.stored_template_version or '?'}, "
                f"current v{_pp.POD_TEMPLATE_VERSION}) — docket pod <project> sync"
            )
        else:
            ui.success(f"  {aid}: v{status.stored_template_version} (current)")
    if stale == 0:
        ui.success("  All pod members are in sync")
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
    for aid in ids:
        ws = _cfg.workspace_dir(aid)
        if not ws.is_dir() or _mem.contract_ok(ws):
            continue
        meta = store.read_json(_cfg.meta_path(aid))
        codebase = str(meta.get("codebase", ""))
        stack = str(meta.get("stack", ""))
        name = str(meta.get("name", "") or aid)
        _mem.seed_contract(ws, project=name, codebase=codebase, stack=stack)
        where = f" (codebase {codebase})" if codebase else " (no codebase in meta)"
        ui.success(f"  {aid}: seeded {_mem.REQUIRED_STARTUP_FILE}{where}")
        healed += 1
    if healed == 0:
        ui.success(f"  All agents have a current {_mem.REQUIRED_STARTUP_FILE}")
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
    meta = _secrets.load_secrets_meta()
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
        expected = _expected_credential(provider)
        if expected and expected not in stored:
            missing_keys.append({"agent": aid, "model": model, "needsKey": expected})
            issues += 1
    return issues, keys_list, missing_keys


def _doctor_json_security() -> dict[str, Any]:
    """Gate/isolation posture, JSON shape of `_check_security_gates`."""
    return {
        "toolCallGate": "always-on",
        "isolation": _fleet.get_isolation_state(),
        "sandboxBackend": _sys.sandbox_availability().backend,
        "dockerImageHasGit": _docker_image_has_git(),
        "network": _fleet.get_network_mode(),
        "unjailedMcpServers": _unjailed_mcp_servers(),
    }


def _doctor_json_notifications(ids: list[str]) -> tuple[int, dict[str, Any]]:
    """Notification reach, JSON shape of `_check_notifications`."""
    delivering = _channel.load_catalog().delivering()
    ok = bool(delivering) or not ids
    return (0 if ok else 1), {"ok": ok, "delivering": delivering}


def _doctor_json_provider_catalog() -> tuple[int, list[dict[str, str]]]:
    """Malformed global provider documents, JSON shape of `_check_provider_catalog`."""
    problems = _provider_catalog_problems()
    return len(problems), [{"name": name, "reason": reason} for name, reason in problems]


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
    """Assemble the machine-readable health report; channel-binding presence is
    covered per agent below."""
    issues = 0
    ids = project_ids()

    has_py = shutil.which("python3")
    if not has_py:
        issues += 1

    fleet_issues, fleet_data, fleet = _doctor_json_fleet_state()
    issues += fleet_issues

    agents_issues, agents_json = _doctor_json_agents(ids, fleet)
    issues += agents_issues

    ledger_issues, dispatch_ledger_results = _doctor_json_dispatch_ledger()
    issues += ledger_issues

    budget_issues, budget_results, runaway_results = _doctor_json_budget_runaway(ids)
    issues += budget_issues

    key_issues, keys_list, missing_keys = _doctor_json_key_hygiene(ids)
    issues += key_issues

    provider_catalog_issues, provider_catalog_problems = _doctor_json_provider_catalog()
    issues += provider_catalog_issues

    notify_issues, notifications = _doctor_json_notifications(ids)
    issues += notify_issues

    security = _doctor_json_security()
    tmpl_results = _doctor_json_template_drift(ids)

    return {
        "healthy": issues == 0,
        "issues": issues,
        "checks": {
            "python3": {"ok": bool(has_py), "path": has_py or None},
            "fleet": fleet_data,
            "agents": agents_json,
            "dispatchLedger": dispatch_ledger_results,
            "budget": budget_results,
            "runaway": runaway_results,
            "keyHygiene": {"keys": keys_list, "missingForAgents": missing_keys},
            "providerCatalog": {
                "ok": not provider_catalog_problems,
                "problems": provider_catalog_problems,
            },
            "notifications": notifications,
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
    was_recording = ui.console.record
    ui.console.record = True
    ui.console.export_text(clear=True)

    ids = project_ids()
    cost = _batch_cost(ids)

    _check_dependencies()
    _check_project_agents(ids)
    _check_model_registry_entries()
    _check_archetype_overlay()
    _check_schedule_config()
    _check_dispatch_ledger(do_fix)
    _check_budget(ids, _batch_gating_cost(ids))
    _check_runaway(ids, cost)
    _check_key_hygiene()
    _check_provider_coverage(ids)
    _check_provider_catalog()
    _check_exporters()
    _check_notifications(ids)
    _check_security_gates()
    _check_policies()
    _check_pod_config_overlays()
    _check_template_version(ids)
    _check_pod_sync(ids)
    _check_runtime_contract(ids)

    ui.console.print()
    rendered = ui.console.export_text(clear=True)
    ui.console.record = was_recording
    return _print_summary(rendered)


def _print_summary(rendered: str) -> int:
    """Print the verdict from the report just shown: critical = lines marked with a cross."""
    lines = rendered.splitlines()
    critical = sum("✗" in ln for ln in lines) - sum("ledger re-synced" in ln for ln in lines)
    if critical <= 0:
        ui.success("All checks passed — docket is healthy.")
        return 0
    ui.console.print(f"[red][bold]{critical} critical issue(s) found.[/bold][/red]")
    ui.console.print("  Re-sync what can be fixed automatically:  docket doctor --fix")
    return 1
