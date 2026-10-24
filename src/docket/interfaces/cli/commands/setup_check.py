"""docket setup --fix and the health engine: system-wide checks + auto-fixes.

`run_check(json_out, do_fix)` returns the process exit code: 0 healthy, 1 when
issues are flagged. Each check is its own function, testable in isolation.

All fleet/agent state is read through `teams/fleet.py` and `store`; this
module never opens a daemon config file — there is no daemon to have one.
Where a check has no daemon-era equivalent, its own docstring says so and
why (see `_check_dependencies`, `_check_security_gates`, `_check_json`).
"""

from __future__ import annotations

import json as _json
import shutil
from typing import Any

from docket.hops.gates import profile as _profile
from docket.interfaces.cli.commands.setup_check_budget import (
    _batch_cost,
    _batch_gating_cost,
    _check_budget,
    _check_dispatch_ledger,
    _check_runaway,
)
from docket.interfaces.cli.commands.setup_check_config import (
    _agents_missing_contract,
    _check_pod_config_overlays,
    _check_pod_sync,
    _check_policies,
    _check_profiles,
    _check_runtime_contract,
    _check_template_version,
    _pod_member_sync,
    _pod_overlay_problems,
    _policy_problems,
    _pp_version,
    _required_workspace_files,
)
from docket.interfaces.cli.commands.setup_check_providers import (
    _check_key_hygiene,
    _check_provider_catalog,
    _check_provider_coverage,
    _keys_age_report,
    _missing_provider_keys,
    _provider_catalog_problems,
)
from docket.interfaces.cli.commands.setup_check_services import (
    _check_exporters,
    _check_notifications,
    _check_security_gates,
    _docker_image_has_git,
    _exporter_report,
)
from docket.interfaces.cli.render import ui
from docket.kernel.home import current_home
from docket.kernel.ports import jail as _jail
from docket.operator import load_catalog
from docket.pipeline.application import schedule as _sched
from docket.platform import read_json
from docket.tasks.application import queue as _queue
from docket.teams import agent_memory as _mem
from docket.teams import fleet as _fleet
from docket.teams import model_selection as _mp
from docket.teams import network_posture as _np
from docket.teams import pod as _pod
from docket.teams import pod as _pod_ledger_mod
from docket.teams import pod as _pod_mod
from docket.teams.utils import project_ids


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


def _pod_of(aid: str) -> str:
    """The pod *aid* is a member of, or ``""`` for a standalone agent."""

    return _pod.pod_of(aid) or ""


def _check_project_agents(ids: list[str]) -> int:
    """Per-project workspace files, fleet registration, and channel binding. A pod member's
    missing managed file is re-rendered by ``docket pod update``; ``setup --fix`` does not
    write it."""
    if not ids:
        ui.console.print()
        ui.warn("No project agents found — run: docket init")
        return 0

    ui.section("Project agents (global fleet across all registered projects):")
    issues = 0
    fleet = _fleet.load_fleet()
    registered = {a.id for a in _fleet.list_agents(fleet)}

    for aid in ids:
        ws = current_home().projects_dir / aid
        tg = _fleet.get_binding(aid, cfg=fleet)
        proj_issues: list[str] = []
        for f in _required_workspace_files(aid):
            if not (ws / f).is_file():
                proj_issues.append(f"missing {f}")
        if not (ws / current_home().meta_file).is_file():
            proj_issues.append(f"no {current_home().meta_file}")
        if aid not in registered:
            proj_issues.append("not registered in fleet")

        if proj_issues:
            ui.console.print(f"[red]✗[/red]   {aid}: {' '.join(proj_issues)}")
            pod_name = _pod_of(aid)
            if pod_name and all(i.startswith("missing ") for i in proj_issues):
                ui.console.print(f"    Fix with: docket pod update --pod {pod_name}")
            issues += 1
        elif not tg:
            ui.warn(f"  {aid}: OK, no channel binding  →  docket setup notify bind {aid}")
        else:
            ui.success(f"  {aid}: OK  →  group {tg}")
    return issues


def _check_model_registry_entries() -> int:
    """Flag every malformed ``docket-models.json`` entry (unknown rank anchor/role, or a
    bad model id) that ``load_registry`` silently ignores at read time -- naming the file,
    key, and reason. Read-only: never edits the registry."""
    ui.section("Model registry entries (docket-models.json):")
    problems = _mp.find_registry_problems()
    if not problems:
        ui.success("  All registry entries are well-formed")
        return 0
    ui.console.print("[red]✗[/red]   Found malformed docket-models.json entries:")
    for key, reason in problems:
        ui.console.print(f"    {key}: {reason}")
    return len(problems)


def _check_schedule_config() -> int:
    """Flag every ``docket-schedules.json`` entry ``is_schedule_due`` would silently treat
    as never-due -- naming the file, project key, and reason. Read-only:
    never edits the schedules file (use ``docket pod set|unset schedule``)."""

    ui.section("Schedules (docket-schedules.json):")
    problems = _sched.find_schedule_problems(current_home().schedule_file)
    if not problems:
        ui.success("  All schedules are well-formed")
        return 0
    ui.console.print("[red]✗[/red]   Found schedule(s) that will never fire:")
    for key, reason in problems:
        ui.console.print(f"    {key}: {reason}")
    return len(problems)


def _check_json_fleet_state() -> tuple[int, dict[str, Any], _fleet.FleetConfig | None]:
    """Load the fleet for the JSON report; a load failure is one issue and yields the
    error shape callers below treat as "no fleet"."""
    fleet_data: dict[str, Any]
    fleet = None
    issues = 0
    try:
        fleet = _fleet.load_fleet()
        fleet_data = {
            "ok": True,
            "path": str(current_home().fleet_file),
            "agents": len(fleet.agents),
            "bindings": len(fleet.bindings),
        }
    except Exception as ex:
        fleet_data = {"ok": False, "path": str(current_home().fleet_file), "error": str(ex)}
        issues += 1
    return issues, fleet_data, fleet


def _check_json_agents(
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
        ws = current_home().projects_dir / aid
        for f in _required_workspace_files(aid):
            if not (ws / f).exists():
                a_issues.append(f"missing {f}")
        if not (ws / current_home().meta_file).exists():
            a_issues.append(f"no {current_home().meta_file}")
        if aid not in fleet_agent_map:
            a_issues.append("not registered in fleet")
        if a_issues:
            issues += 1
        agents_json.append(
            {"id": aid, "ok": not a_issues, "tg": tg_map.get(aid, ""), "issues": a_issues}
        )
    return issues, agents_json


def _check_json_dispatch_ledger() -> tuple[int, list[dict[str, Any]]]:
    """TASK_LIST.json vs. HEARTBEAT.md ledger agreement, JSON shape of `_check_dispatch_ledger`."""

    issues = 0
    dispatch_ledger_results: list[dict[str, Any]] = []
    for project in _queue.dispatchable_pods():
        lead_id = _pod_ledger_mod.member_id(project, "lead")
        ws = current_home().workspace_dir(lead_id)
        tasks = _queue.read_tasks(project)
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


def _check_json_budget_runaway(
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
        runaway = (
            turns > current_home().runaway_turns_threshold
            or cost_f >= current_home().runaway_cost_threshold
        )
        if runaway:
            issues += 1
        runaway_results.append(
            {"id": aid, "turns": turns, "costUsd": round(cost_f, 6), "ok": not runaway}
        )
    return issues, budget_results, runaway_results


def _check_json_key_hygiene(
    ids: list[str],
) -> tuple[int, list[dict[str, str]], list[dict[str, str]]]:
    """Key age report + missing provider keys, JSON shape of `_check_key_hygiene` and
    `_check_provider_coverage`."""
    keys_list = [{"name": n, "state": s, "detail": d} for s, n, d in _keys_age_report()]

    missing_keys = [
        {"agent": aid, "model": model, "needsKey": expected}
        for aid, model, expected in _missing_provider_keys(ids)
    ]
    return len(missing_keys), keys_list, missing_keys


def _check_json_security() -> dict[str, Any]:
    """Gate/isolation posture, JSON shape of `_check_security_gates`."""
    backend = _jail.sandbox_availability().backend
    return {
        "toolCallGate": "always-on",
        "isolation": _fleet.get_isolation_state(),
        "sandboxBackend": backend,
        "sandboxUsable": backend != "none",
        "dockerImageHasGit": _docker_image_has_git(),
        "network": _fleet.get_network_mode(),
        "networkEnforced": _np.global_posture().enforced,
    }


def _check_json_notifications(ids: list[str]) -> tuple[int, dict[str, Any]]:
    """Notification reach, JSON shape of `_check_notifications`."""
    delivering = load_catalog().delivering()
    ok = bool(delivering) or not ids
    return (0 if ok else 1), {"ok": ok, "delivering": delivering}


def _check_json_provider_catalog() -> tuple[int, list[dict[str, str]]]:
    """Malformed global provider documents, JSON shape of `_check_provider_catalog`."""
    problems = _provider_catalog_problems()
    return len(problems), [{"name": name, "reason": reason} for name, reason in problems]


def _check_json_template_drift(ids: list[str]) -> list[dict[str, Any]]:
    """Template/prompt version drift, JSON shape of `_check_template_version`.
    Advisory — never contributes to the issue count."""

    tmpl_results: list[dict[str, Any]] = []
    for aid in ids:
        # Pod members use their own template scheme — exclude from single-agent drift.
        if _pod_mod.pod_of(aid) is not None:
            continue
        tv_raw = read_json(current_home().meta_path(aid)).get("templateVersion")
        tv_i = int(tv_raw) if tv_raw is not None else None
        tmpl_results.append(
            {
                "id": aid,
                "agentVersion": tv_i,
                "currentVersion": current_home().template_version,
                "ok": tv_i == current_home().template_version,
            }
        )
    return tmpl_results


def _check_json_config_files(ids: list[str]) -> tuple[int, dict[str, Any]]:
    """Registry, schedule, policy and pod-overlay problems: JSON shape of the text
    checks of the same names. Returns the issue count and the keys to merge under `checks`."""

    registry = _mp.find_registry_problems()
    schedules = _sched.find_schedule_problems(current_home().schedule_file)
    _files, policies = _policy_problems()
    pod_overlays = _pod_overlay_problems()
    stale = [
        {
            "id": aid,
            "storedVersion": st.stored_template_version or None,
            "currentVersion": _pp_version(),
        }
        for aid, st in _pod_member_sync(ids)
        if st.stale
    ]
    exporters = _exporter_report()
    contract = _agents_missing_contract(ids)
    checks: dict[str, Any] = {
        "modelRegistry": {
            "ok": not registry,
            "problems": [{"key": k, "reason": r} for k, r in registry],
        },
        "schedules": {
            "ok": not schedules,
            "problems": [{"key": k, "reason": r} for k, r in schedules],
        },
        "exporters": {
            "ok": all(row["failed"] == 0 for row in exporters),
            "enabled": [
                {"name": r["name"], "failed": r["failed"], "sharesContentWith": r["host"]}
                for r in exporters
            ],
        },
        "guardrailPolicies": {
            "ok": not policies,
            "problems": [{"file": n, "reason": r} for n, r in policies],
        },
        "podConfigOverlays": {
            "ok": not pod_overlays,
            "problems": [
                {"pod": p, "kind": k, "name": n, "reason": r} for p, k, n, r in pod_overlays
            ],
        },
        "podSync": {"ok": not stale, "stale": stale},
        "runtimeContract": {"ok": not contract, "missing": contract},
    }
    issues = len(registry) + len(schedules) + len(policies)
    issues += len(pod_overlays) + len(stale)
    return issues, checks


def _check_json() -> dict[str, Any]:
    """Assemble the machine-readable health report; channel-binding presence is
    covered per agent below."""
    issues = 0
    ids = project_ids()

    has_py = shutil.which("python3")
    if not has_py:
        issues += 1

    fleet_issues, fleet_data, fleet = _check_json_fleet_state()
    issues += fleet_issues

    agents_issues, agents_json = _check_json_agents(ids, fleet)
    issues += agents_issues

    ledger_issues, dispatch_ledger_results = _check_json_dispatch_ledger()
    issues += ledger_issues

    budget_issues, budget_results, runaway_results = _check_json_budget_runaway(ids)
    issues += budget_issues

    key_issues, keys_list, missing_keys = _check_json_key_hygiene(ids)
    issues += key_issues

    provider_catalog_issues, provider_catalog_problems = _check_json_provider_catalog()
    issues += provider_catalog_issues

    notify_issues, notifications = _check_json_notifications(ids)
    issues += notify_issues

    security = _check_json_security()
    if report := _profile.lights_out_report():
        security["profile"] = {p: _profile.as_json(v) for p, v in report.items()}
    if ids and not security["sandboxUsable"]:
        issues += 1
    tmpl_results = _check_json_template_drift(ids)
    config_issues, config_checks = _check_json_config_files(ids)
    issues += config_issues

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
            **config_checks,
        },
    }


def run_check(json_out: bool = False, do_fix: bool = False) -> int:
    """Run all health checks; return 0 when healthy, 1 when issues are flagged.
    json_out emits the machine-readable report (health probe); do_fix re-syncs
    the dispatch ledger from TASK_LIST.json."""
    if json_out:
        report = _check_json()
        print(_json.dumps(report, indent=2))
        return 0 if report.get("healthy") else 1

    ui.header("Setup check")
    ui.console.print()
    was_recording = ui.console.record
    ui.console.record = True
    ui.console.export_text(clear=True)

    ids = project_ids()
    cost = _batch_cost(ids)

    _check_dependencies()
    _check_project_agents(ids)
    _check_model_registry_entries()
    _check_schedule_config()
    _check_dispatch_ledger(do_fix)
    _check_budget(ids, _batch_gating_cost(ids))
    _check_runaway(ids, cost)
    _check_key_hygiene()
    _check_provider_coverage(ids)
    _check_provider_catalog()
    _check_exporters()
    _check_notifications(ids)
    _check_security_gates(ids)
    _check_profiles()
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
    ui.console.print("  Re-sync what can be fixed automatically:  docket setup --fix")
    return 1
