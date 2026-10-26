from __future__ import annotations

from typing import Any

from docket.governance import policy as _pol
from docket.hops.application import report as _pod_report
from docket.interfaces.cli.render import ui
from docket.kernel.home import current_home
from docket.platform import read_json
from docket.tasks.application import queue as _queue
from docket.teams import agent_memory as _mem
from docket.teams import fleet as _fleet
from docket.teams import member_workspace as _member_workspace
from docket.teams import pod as _pod
from docket.teams import roles as _arch

_WORKSPACE_FILES = ("SOUL.md", "AGENTS.md", "TOOLS.md", _mem.HEARTBEAT_FILE)


def _provisioned_tools_md(aid: str) -> bool:
    """True when provisioning writes a TOOLS.md for the pod member *aid*: an Implementer with
    allocated runtime resources or a verify command (the same test ``pod_provisioning`` uses)."""
    if _fleet.meta_get(aid, "role", "") != "implementer":
        return False
    resources = _fleet.meta_get(aid, "portRangeStart", "") and _fleet.meta_get(
        aid, "scratchDir", ""
    )
    return bool(resources or _fleet.meta_get(aid, "verifyCmd", ""))


def _required_workspace_files(aid: str) -> tuple[str, ...]:
    """Workspace files ``aid`` must have; a pod member needs TOOLS.md only when provisioning
    writes one (workspace-structure.spec.md requirement 1)."""

    if _pod.pod_of(aid) is not None and not _provisioned_tools_md(aid):
        return tuple(f for f in _WORKSPACE_FILES if f != "TOOLS.md")
    return _WORKSPACE_FILES


def _check_profiles() -> None:
    """Under ``lights-out``, each pod's profile and unmet requirements; silent otherwise."""
    report = _pod_report.lights_out_report()
    if not report:
        return
    ui.section("Profile:")
    for project, violations in report.items():
        if not violations:
            ui.success(f"  {project}: lights-out, all requirements met")
            continue
        ui.warn(f"  {project}: lights-out, tasks are refused until fixed")
        for v in violations:
            ui.console.print(f"    {v.requirement}: {v.detail}. Fix: {v.fix}", markup=False)


def _policy_problems() -> tuple[list[Any], list[tuple[str, str]]]:
    """(installed policy files, (file name, error) for each the evaluator fails closed on)."""
    files = _pol.policy_files()
    problems = [(f.name, err) for f in files if (err := _pol.validate_policy(f))]
    return files, problems


def _check_policies() -> int:
    """Guardrail policy store integrity: flags any file the evaluator would fail closed on,
    through the same ``governance.policy`` validation, so doctor can never call a store healthy that
    a live turn would block on (security-gates.spec.md, policy engine requirement 7)."""
    ui.section("Guardrail policies:")
    files, problems = _policy_problems()
    if not files:
        ui.dim("  No policies installed — docket setup")
        return 0
    for name, err in problems:
        ui.console.print(f"[red]✗[/red]   {name}: broken — every matching call fails closed")
        ui.console.print(f"    {err}")
    if problems:
        ui.console.print("  Fix or remove the file(s); check with: docket pod validate")
        return len(problems)
    ui.success(f"  {len(files)} policy file(s) valid")
    return 0


def _pod_overlay_problems() -> list[tuple[str, str, str, str]]:
    """(pod, kind, name, reason) for each malformed pod role overlay or invalid pod policy file,
    excluding problems already reported for the global policy files."""

    global_policy_files = set(_pol.policy_files())
    found: list[tuple[str, str, str, str]] = []
    for project in _queue.dispatchable_pods():
        for role, reason in _arch.find_overlay_problems(project):
            found.append((project, "role", role, reason))
        for f in _pol.policy_files(project):
            if f not in global_policy_files and (err := _pol.validate_policy(f)):
                found.append((project, "policy", f.name, err))
    return found


def _check_pod_config_overlays() -> int:
    """Every pod's own config overlay (``<pod>/config/``) -- the layer
    ``_check_policies`` never looks at. Names the pod plus
    the role/file and reason for a malformed role overlay or invalid policy file."""

    ui.section("Pod config overlays (<pod>/config/):")
    if not _queue.dispatchable_pods():
        ui.dim("  No pods provisioned")
        return 0
    problems = _pod_overlay_problems()
    for project, kind, name, reason in problems:
        ui.console.print(f"[red]✗[/red]   {project}: {kind} {name}: {reason}")
    if not problems:
        ui.success("  All pod overlay entries and policy files are well-formed")
    return len(problems)


def _check_template_version(ids: list[str]) -> int:
    """Template/prompt version drift (advisory — never fails)."""
    if not ids:
        return 0
    ui.console.print()
    ui.console.print(
        f"[bold]Template version (current: v{current_home().template_version}):[/bold]"
    )

    drift = 0
    for aid in ids:
        # Pod members use their own template scheme (POD_TEMPLATE_VERSION) and are
        # NOT checked against the single-agent template version (that would
        # clobber the pod-role SOULs). Skip them here.
        if _pod.pod_of(aid) is not None:
            continue
        tv = _fleet.meta_get(aid, "templateVersion", "")
        if not tv:
            ui.warn(f"  {aid}: unstamped (pre-versioning)")
            drift += 1
        elif tv != str(current_home().template_version):
            ui.warn(f"  {aid}: on v{tv}, current v{current_home().template_version}")
            drift += 1
        else:
            ui.success(f"  {aid}: v{tv} (current)")
    return 0


def _pod_member_sync(ids: list[str]) -> list[tuple[str, Any]]:
    """(member id, sync status) for each pod member whose status can be read."""

    out: list[tuple[str, Any]] = []
    for aid in ids:
        if _pod.pod_of(aid) is None:
            continue
        status = _member_workspace.member_sync_status(aid)
        if status is not None:
            out.append((aid, status))
    return out


def _check_pod_sync(ids: list[str]) -> int:
    """Flag pod members whose managed files drifted from the current archetype +
    metadata -- the pod counterpart of ``_check_template_version``, which skips pod
    members outright. Advisory; ``docket pod update`` re-renders."""

    if not any(_pod.pod_of(aid) is not None for aid in ids):
        return 0
    ui.section("Pod member templates:")
    stale = 0
    for aid, status in _pod_member_sync(ids):
        if status.stale:
            stale += 1
            ui.console.print(
                f"[red]✗[/red]   {aid}: stale (v{status.stored_template_version or '?'}, "
                f"current v{_member_workspace.POD_TEMPLATE_VERSION}) — docket pod update"
            )
        else:
            ui.success(f"  {aid}: v{status.stored_template_version} (current)")
    if stale == 0:
        ui.success("  All pod members are in sync")
    return 0


def _agents_missing_contract(ids: list[str]) -> list[str]:
    """Agents with a workspace but no current durability contract (``WORKFLOW_AUTO.md``)."""
    return [
        aid
        for aid in ids
        if current_home().workspace_dir(aid).is_dir()
        and not _mem.contract_ok(current_home().workspace_dir(aid))
    ]


def _check_runtime_contract(ids: list[str]) -> int:
    """Re-seed each missing or stale ``WORKFLOW_AUTO.md`` from the agent's stored codebase and
    stack. Advisory -- never fails the run."""
    ui.section("Runtime startup contract:")
    missing = _agents_missing_contract(ids)
    for aid in missing:
        ws = current_home().workspace_dir(aid)
        meta = read_json(current_home().meta_path(aid))
        codebase = str(meta.get("codebase", ""))
        stack = str(meta.get("stack", ""))
        name = str(meta.get("name", "") or aid)
        _mem.seed_contract(ws, project=name, codebase=codebase, stack=stack)
        where = f" (codebase {codebase})" if codebase else " (no codebase in meta)"
        ui.success(f"  {aid}: seeded {_mem.REQUIRED_STARTUP_FILE}{where}")
    if not missing:
        ui.success(f"  All agents have a current {_mem.REQUIRED_STARTUP_FILE}")
    return 0


def _pp_version() -> int:
    return int(_member_workspace.POD_TEMPLATE_VERSION)
