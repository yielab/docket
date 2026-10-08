"""docket pod: the pod group, its roster and its settings.

A *pod* is the set of project-scoped agents for one project: a Lead plus workers, each
with its own workspace; member ids are ``<project>-<role>`` (``-N`` for duplicates).
Composition lives in `core/pod.py`; provisioning I/O lives in `core/pod_provisioning.py`
so `serve.py`'s `POST /pods` reaches it without importing `docket.cli`. This module
renders around those typed results, so `docket init` and `POST /pods` cannot drift apart.
"""

from __future__ import annotations

import contextlib
import hashlib as _hashlib
import os
from pathlib import Path
from typing import Any

import typer
from rich.markup import escape

import docket.config as _cfg
from docket import ui
from docket.cli import _contract
from docket.cli import _pod_show as _show
from docket.cli._target import TargetError, pod_option, resolve_pod
from docket.core import archetypes as _arch
from docket.core import dispatch as _dispatch
from docket.core import fleet as _fleet
from docket.core import memory as _mem
from docket.core import models_policy as _mp
from docket.core import orchestrator as _orch
from docket.core import pipeline as _pipeline
from docket.core import pod
from docket.core import pod_apply as _pod_apply
from docket.core import pod_provisioning as _pp
from docket.core import schedule as _sched
from docket.core.audit import audit_log
from docket.edges import store
from docket.edges.adapters import docket_runtime as _dr

# Names this module's callers and tests reach on `docket.cli._pod`; the implementations
# live in core/pod_provisioning.py.
POD_TEMPLATE_VERSION = _pp.POD_TEMPLATE_VERSION
_MAX_VERIFY_CMD_LEN = _pp._MAX_VERIFY_CMD_LEN
VerifyCmdError = _pp.VerifyCmdError
_validate_verify_cmd = _pp.validate_verify_cmd
_worktree_branch = _pp.worktree_branch
_provision_task_worktree = _pp.provision_task_worktree
_member_soul = _pp._member_soul
_member_agents = _pp._member_agents
_member_tools = _pp._member_tools
teardown_member = _pp.teardown_member
free_pod_resources = _pp.free_pod_resources
purge_pod_history = _pp.purge_pod_history
pod_member_ids = _pp.pod_member_ids

pod_app = typer.Typer(
    name="pod",
    help="Manage this project's pod: members, settings and configuration.",
    no_args_is_help=True,
)


def provision_member(
    member: pod.PodMember,
    *,
    codebase: str,
    stack: str,
    description: str,
    project: str,
    project_key: str,
    port_range_start: int = 0,
    port_range_count: int = 0,
    scratch_dir: str = "",
    verify_cmd: str = "",
    work_dir: str = "",
    blueprint_name: str = "",
    budget_usd: float | None = None,
) -> tuple[bool, str]:
    """Create one pod member's workspace + meta and register it in the fleet registry.
    Thin rendering wrapper over `core.pod_provisioning.provision_member` — prints the
    `(ok, message)` result."""
    ok, msg = _pp.provision_member(
        member,
        codebase=codebase,
        stack=stack,
        description=description,
        project=project,
        project_key=project_key,
        port_range_start=port_range_start,
        port_range_count=port_range_count,
        scratch_dir=scratch_dir,
        verify_cmd=verify_cmd,
        work_dir=work_dir,
        blueprint_name=blueprint_name,
        budget_usd=budget_usd,
    )
    return ok, msg


def pod_roles(full: bool, with_roles: str) -> tuple[str, ...]:
    """The software pod's roster from `docket init`'s flags: lean (lead + implementer) by
    default, the four-role pod for ``--pod full``, lean plus the named ``--with`` roles
    otherwise. Unknown role names are ignored."""
    if full:
        return pod.FULL_POD_ROLES
    extras: list[str] = []
    for raw in with_roles.split(","):
        if not raw.strip():
            continue
        try:
            role = pod.normalize_role(raw)
        except pod.PodError:
            continue
        if role not in ("lead", "implementer") and role not in extras:
            extras.append(role)
    return (*pod.DEFAULT_POD_ROLES, *extras)


def _render_created(members: list[_pp.ProvisionedMember]) -> list[str]:
    """Render each provisioned member's success line."""
    for m in members:
        ui.success(escape(f"  {m.member_id}  [{m.role}]  {m.model}"))
    return [m.member_id for m in members]


def build_pod(
    project: str,
    roles: tuple[str, ...],
    *,
    codebase: str = "",
    stack: str = "",
    description: str = "",
    project_key: str = "default",
    work_dir: str = "",
    blueprint_name: str = "",
    budget_usd: float | None = None,
) -> list[str]:
    """Provision a fresh pod's members and return their ids, all-or-nothing: a partial
    failure rolls back every member and any pod resources, the contract `POST /pods` shares."""
    try:
        created = _pp.provision_members(
            project,
            roles,
            codebase=codebase,
            stack=stack,
            description=description,
            project_key=project_key,
            work_dir=work_dir,
            blueprint_name=blueprint_name,
            budget_usd=budget_usd,
        )
    except _pp.PodProvisionError as exc:
        ui.warn(f"  pod provisioning failed: {exc}")
        return []
    return _render_created(created)


def build_pod_from_blueprint(
    project: str,
    blueprint_name: str,
    *,
    location: str = "",
    stack: str = "",
    description: str = "",
    project_key: str = "default",
    roles: tuple[str, ...] | None = None,
    budget_usd: float | None = None,
    verify_cmd: str = "",
    source: str = "declarative",
) -> list[str]:
    """Provision a fresh pod from a named blueprint and return its member ids; a refusal or a
    failure warns and returns ``[]``. The path `docket init` and `POST /pods` share."""
    try:
        result = _pp.provision_pod(
            project,
            blueprint_name,
            location=location,
            stack=stack,
            description=description,
            project_key=project_key,
            roles=roles,
            budget_usd=budget_usd,
            verify_cmd=verify_cmd,
            source=source,
        )
    except _pp.PodAlreadyExistsError:
        ui.warn(f"'{project}' already exists — skipping.")
        return []
    except _pp.PodProvisionError as exc:
        ui.warn(f"  pod provisioning failed: {exc}")
        return []
    return _render_created(result.members)


def _pod_name(name: str | None) -> str:
    """The pod a leaf acts on: ``--pod``, ``DOCKET_POD``, then the cwd; exit 1 when none."""
    try:
        return resolve_pod(name, env=os.environ, cwd=Path.cwd())
    except TargetError as exc:
        ui.error(str(exc))
        raise typer.Exit(1) from exc


def _require_members(project: str) -> list[str]:
    members = pod_member_ids(project)
    if not members:
        ui.error(f"No pod named '{project}'", "Create one with: docket init")
        raise typer.Exit(1)
    return members


def _require_member(project: str, member_id: str) -> str:
    """The member's role, or exit 1 when ``member_id`` is not in the pod."""
    _require_members(project)
    if pod.parse_member_id(member_id, project) is None:
        ui.error(f"'{member_id}' is not a member of the '{project}' pod", "See: docket pod show")
        raise typer.Exit(1)
    return _fleet.meta_get(member_id, "role", "")


def _implementer_member(project: str, member_id: str) -> None:
    """Exit 1 unless ``member_id`` is an implementer of the pod (the only role with a verify gate)."""
    role = _require_member(project, member_id)
    if role != "implementer":
        ui.error(
            f"'{member_id}' is a {role or 'unknown role'}",
            "verify applies only to implementers",
        )
        raise typer.Exit(1)


@pod_app.command("show")
def cmd_show(
    member: str | None = typer.Argument(None, help="A member id, for its full configuration"),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON"),
    pod_name: str | None = pod_option(),
) -> None:
    """The pod: members, settings and the approval mode dispatch will use, with sources.

    With a member id, that member's whole effective configuration instead.

    Example: docket pod show"""
    project = _pod_name(pod_name)
    _require_members(project)
    if member is not None:
        _require_member(project, member)
    try:
        report = _show.member_report(member) if member else _show.pod_report(project)
    except (_dispatch.DispatchError, pod.PodSettingsError) as ex:
        ui.error(str(ex))
        raise typer.Exit(1) from ex
    if json_out:
        _contract.emit_json(report)
    elif member:
        _show.render_member(report)
    else:
        _show.render_pod(report)


def add_members(project: str, role: str, *, count: int = 1, verify_cmd: str = "") -> list[str]:
    """Add ``count`` members of ``role`` to the pod; returns the new member ids."""
    base_ids = _require_members(project)
    try:
        canon_role = pod.normalize_role(role, project)
    except pod.PodError as ex:
        ui.error(str(ex))
        raise typer.Exit(1) from ex
    if verify_cmd:
        try:
            verify_cmd = _validate_verify_cmd(verify_cmd)
        except VerifyCmdError as ex:
            ui.error(str(ex))
            raise typer.Exit(1) from ex

    # A new member inherits codebase/stack/description (and a workdir pod's shared directory and
    # blueprint) from an existing one, so it is never provisioned as a codebase-kind member.
    base_id = base_ids[0]
    inherited: dict[str, Any] = {
        "codebase": _fleet.meta_get(base_id, "codebase", ""),
        "stack": _fleet.meta_get(base_id, "stack", ""),
        "description": _fleet.meta_get(base_id, "description", ""),
        "work_dir": _fleet.meta_get(base_id, "workDir", ""),
        "blueprint_name": _fleet.meta_get(base_id, "blueprint", ""),
    }
    project_key = _fleet.meta_get(base_id, "projectKey", "default") or "default"
    role_models, _, _ = _mp.load_registry()

    if canon_role == "implementer":
        port_start, port_count, scratch = _pp.allocate_pod_resources(project)
    else:
        port_start, port_count, scratch = 0, 0, ""
        if verify_cmd:
            ui.warn(f"--verify only applies to implementers; ignored for {canon_role}")
            verify_cmd = ""

    created: list[str] = []
    for _ in range(max(1, count)):
        try:
            member = pod.plan_added_member(
                project,
                role,
                pod_member_ids(project),
                project_key=project_key,
                role_models=role_models,
            )
        except pod.PodError as ex:
            ui.error(str(ex))
            raise typer.Exit(1) from ex
        ok, msg = provision_member(
            member,
            project=project,
            project_key=project_key,
            port_range_start=port_start,
            port_range_count=port_count,
            scratch_dir=scratch,
            verify_cmd=verify_cmd,
            **inherited,
        )
        if not ok:
            ui.warn(f"{member.member_id}: registration failed - {msg}")
            continue
        ui.success(f"Added {member.member_id} ({member.role}, {member.model})")
        created.append(member.member_id)
        if verify_cmd:
            audit_log("pod.set-verify", f"member={member.member_id} cmd={verify_cmd!r}")
    if created:
        audit_log("pod.add", f"{project} role={canon_role} members={','.join(created)}")
    return created


@pod_app.command("add")
def cmd_add(
    role: str = typer.Argument(..., help="Role archetype name, e.g. reviewer"),
    count: int = typer.Option(1, "--count", "-n", min=1, help="How many members to add"),
    verify: str = typer.Option("", "--verify", help="Verify command for a new implementer"),
    pod_name: str | None = pod_option(),
) -> None:
    """Add members of a role to the pod.

    Example: docket pod add reviewer"""
    project = _pod_name(pod_name)
    if add_members(project, role, count=count, verify_cmd=verify):
        _contract.next_step("docket pod show")
        return
    raise typer.Exit(1)


def remove_member(project: str, member_id: str, *, yes: bool) -> None:
    """Remove one non-Lead member after confirmation; frees the pod's resources with its last
    implementer."""
    role = _require_member(project, member_id)
    if role == "lead":
        ui.error(f"{member_id} is the pod's Lead", "Delete the pod instead: docket pod delete")
        raise typer.Exit(1)
    if not _contract.confirm(f"Remove {member_id} and its workspace", yes=yes):
        ui.warn("Aborted.")
        raise typer.Exit(1)
    ok, msg = teardown_member(member_id)
    if ok:
        ui.success(f"Removed {member_id}")
        if msg:
            ui.dim(f"  {msg}")
    else:
        ui.warn(f"{member_id}: fleet deregistration reported: {msg} (workspace cleaned)")
    audit_log("pod.remove", f"{project} member={member_id} role={role}")
    if role == "implementer":
        remaining = {_fleet.meta_get(mid, "role", "") for mid in pod_member_ids(project)}
        if "implementer" not in remaining:
            free_pod_resources(project)


@pod_app.command("remove")
def cmd_remove(
    member: str = typer.Argument(..., help="Member id, e.g. demo-reviewer"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the confirmation"),
    pod_name: str | None = pod_option(),
) -> None:
    """Remove a member and its workspace. The Lead is removed only with the pod.

    Example: docket pod remove demo-reviewer"""
    remove_member(_pod_name(pod_name), member, yes=yes)
    _contract.next_step("docket pod show")


def _run_distillation(agent_id: str, ws: Path) -> _mem.DistillResult:
    """Distill ``memory/*.md`` into MEMORY.md through one driver turn. Callers gate their
    destructive step on ``.ok`` so a failed distillation deletes nothing."""
    raw = store.read_json(_cfg.meta_path(agent_id))
    ui.info("Distilling memory before proceeding (one driver-backed turn)...")
    result = _mem.distill_memory(
        ws,
        label=str(raw.get("name", agent_id)),
        agent_id=agent_id,
        session_key=str(raw.get("sessionKey", "")),
        driver=_dr.default_driver().run_turn,
    )
    if not result.ok:
        kind = f" ({result.failure_kind})" if result.failure_kind else ""
        ui.error(
            f"Distillation failed{kind}: {result.error or 'unknown error'}", "Nothing was deleted"
        )
    elif result.skipped:
        ui.info("No memory logs to distill.")
    else:
        ui.success(
            f"Distilled {result.logs_distilled} log(s) into MEMORY.md; "
            f"original(s) archived under memory/{_mem.DISTILLED_ARCHIVE_DIRNAME}/."
        )
    return result


def _clear_memory(agent_id: str, ws: Path, *, keep_memory_md: bool) -> int:
    """Delete ``memory/*.md``, clear MEMORY.md (unless just distilled) and reset the ledger."""
    removed = 0
    mem_dir = ws / "memory"
    if mem_dir.is_dir():
        for f in mem_dir.glob("*.md"):
            f.unlink()
            removed += 1
    memory_md = ws / "MEMORY.md"
    if not keep_memory_md and memory_md.is_file():
        memory_md.write_text("# MEMORY.md\n\n_Cleared by docket pod reset._\n", encoding="utf-8")
        memory_md.chmod(0o600)
    raw = store.read_json(_cfg.meta_path(agent_id))
    hb = ws / _mem.HEARTBEAT_FILE
    hb.write_text(_mem.heartbeat_seed(str(raw.get("name", agent_id))), encoding="utf-8")
    hb.chmod(0o600)
    return removed


def reset_member(project: str, member_id: str, *, yes: bool) -> None:
    """Distill a member's memory, clear it and rebuild SOUL/AGENTS/TOOLS from its metadata.
    A failed distillation aborts before anything is touched."""
    _require_member(project, member_id)
    if not _contract.confirm(f"Reset {member_id}: memory is distilled, then cleared", yes=yes):
        ui.warn("Aborted.")
        raise typer.Exit(1)
    ws = _cfg.workspace_dir(member_id)
    result = _run_distillation(member_id, ws)
    if not result.ok:
        raise typer.Exit(1)
    removed = _clear_memory(member_id, ws, keep_memory_md=not result.skipped)
    for name, text in _pp.rendered_member_files(member_id).items():
        (ws / name).write_text(text, encoding="utf-8")
        (ws / name).chmod(0o600)
    _fleet.meta_set(member_id, "templateVersion", str(POD_TEMPLATE_VERSION))
    audit_log("pod.reset", f"{project} member={member_id} logs={removed}")
    ui.success(f"Reset {member_id}: {removed} memory log(s) cleared, workspace files rebuilt")


@pod_app.command("reset")
def cmd_reset(
    member: str = typer.Argument(..., help="Member id, e.g. demo-implementer"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the confirmation"),
    pod_name: str | None = pod_option(),
) -> None:
    """Distill a member's memory, then clear it and rebuild its workspace files.

    Example: docket pod reset demo-implementer"""
    reset_member(_pod_name(pod_name), member, yes=yes)
    _contract.next_step("docket pod show")


def _delete_pod(project: str, members: list[str]) -> int:
    """Tear down every member of a pod, its resources, history and bindings."""
    from docket.core import conversations as _conv

    for mid in members:
        if _fleet.get_binding(mid):
            _fleet.remove_binding(mid)
        _conv.remove_agent_durable(mid)
        ok, msg = teardown_member(mid)
        if ok:
            ui.success(f"Removed {mid}")
            if msg:
                ui.dim(f"  {msg}")
        else:
            ui.warn(f"{mid}: fleet deregistration reported: {msg} (workspace cleaned)")
    free_pod_resources(project)
    purge_pod_history(project, members)
    audit_log("pod.delete", f"{project} pod ({len(members)} members)")
    ui.success(f"Pod '{project}' deleted")
    return 0


@pod_app.command("delete")
def cmd_delete(
    confirm: str | None = typer.Option(None, "--confirm", help="The pod name, to confirm"),
    pod_name: str | None = pod_option(),
) -> None:
    """Destroy the pod: every member, workspace, session and trace. The audit log stays.

    Example: docket pod delete --confirm demo"""
    project = _pod_name(pod_name)
    members = pod_member_ids(project)
    if not members:
        if _cfg.workspace_dir(project).is_dir():
            ui.error(f"'{project}' is a member id, not a pod", "Pass the pod name with --pod")
        else:
            ui.error(f"No pod named '{project}'", "See: docket status --all")
        raise typer.Exit(1)
    if confirm is not None and confirm != project:
        ui.error(f"--confirm must be the pod name '{project}'", f"Re-run with --confirm {project}")
        raise typer.Exit(1)
    ui.header("pod", project)
    for mid in members:
        ui.dim(f"  {mid} ({_fleet.meta_get(mid, 'role', '?')})")
    ui.warn(
        "This removes every member's workspace, session history and traces; the audit log stays"
    )
    if not _contract.confirm(
        f"Delete pod {project} ({len(members)} members)", yes=confirm == project, typed=project
    ):
        ui.warn("Aborted.")
        raise typer.Exit(1)
    _delete_pod(project, members)
    _contract.next_step("docket init")


def _regenerate_member_tools(member_id: str, project: str) -> None:
    """Rewrite TOOLS.md for an existing Implementer after a meta change (e.g.
    a verify change). No-op for non-implementers, and for members with no allocated
    resources and no verify command (nothing to render)."""
    role = _fleet.meta_get(member_id, "role", "")
    if role != "implementer":
        return
    port_start_s = _fleet.meta_get(member_id, "portRangeStart", "")
    port_count_s = _fleet.meta_get(member_id, "portRangeCount", "")
    scratch = _fleet.meta_get(member_id, "scratchDir", "")
    verify_cmd = _fleet.meta_get(member_id, "verifyCmd", "")
    if not ((port_start_s and scratch) or verify_cmd):
        return
    raw_codebase = _fleet.meta_get(member_id, "codebase", "")
    codebase = pod.resolve_member_cwd(member_id, "", raw_codebase)
    content = _member_tools(
        project,
        role,
        codebase,
        int(port_start_s) if port_start_s else 0,
        int(port_count_s) if port_count_s else 0,
        scratch,
        verify_cmd,
    )
    ws = _cfg.PROJECTS_DIR / member_id
    (ws / "TOOLS.md").write_text(content, encoding="utf-8")


def _set_member_verify(project: str, member_id: str, command: str) -> None:
    """Set an implementer's verify command (validated, audited) and re-render its TOOLS.md."""
    _implementer_member(project, member_id)
    try:
        command = _validate_verify_cmd(command)
    except VerifyCmdError as ex:
        ui.error(str(ex))
        raise typer.Exit(1) from ex
    _fleet.meta_set(member_id, "verifyCmd", command)
    _regenerate_member_tools(member_id, project)
    audit_log("pod.set-verify", f"member={member_id} cmd={command!r}")
    ui.success(f"Set verify command for {member_id}: {command!r}")


def _unset_member_verify(project: str, member_id: str) -> None:
    _implementer_member(project, member_id)
    raw = store.read_json(_cfg.meta_path(member_id))
    raw.pop("verifyCmd", None)
    store.write_json(_cfg.meta_path(member_id), raw)
    _regenerate_member_tools(member_id, project)
    audit_log("pod.unset-verify", f"member={member_id}")
    ui.success(f"Cleared the verify command for {member_id}")


def _lead_for_settings(project: str) -> str:
    """The Lead's member id, after checking the pod exists and has one."""
    try:
        _dispatch.pod_pipeline(project)
    except _dispatch.DispatchError as ex:
        ui.error(str(ex))
        raise typer.Exit(1) from ex
    return pod.member_id(project, "lead")


def _budget_changed(project: str, lead_id: str, *, cap_removed: bool) -> None:
    """A new budget re-queues the pod's budget-blocked tasks and lifts an auto-pause."""
    unblocked = _dispatch.unblock_pod(project)
    if unblocked:
        ui.info(f"Unblocked {unblocked} budget-blocked task(s)")
    if not cap_removed:
        _fleet.meta_set(lead_id, "paused", False)
        _fleet.meta_set(lead_id, "pausedReason", "")


def set_setting(project: str, key: str, value: str, *, member: str | None = None) -> None:
    """Set one pod setting, or with ``member`` an implementer's verify command."""
    if key == "verify" or member is not None:
        if key != "verify":
            ui.error(
                "--member applies only to verify", "Example: docket pod set verify 'make test'"
            )
            raise typer.Exit(1)
        if member is None:
            ui.error("verify belongs to one member", "Pass --member <id>")
            raise typer.Exit(1)
        _set_member_verify(project, member, value)
        return
    lead_id = _lead_for_settings(project)
    if key == "pipeline":
        _pod_config_set_pipeline(project, lead_id, value)
        return
    if key == "schedule":
        _pod_config_set_schedule(project, lead_id, value)
        return
    if key in pod.PodSettings.RECORDED_KEYS:
        ui.error(f"{key} is written by apply, not by set")
        raise typer.Exit(1)
    try:
        coerced = pod.PodSettings.coerce(key, value, project=project)
    except pod.PodSettingsError as ex:
        ui.error(str(ex))
        raise typer.Exit(1) from ex
    _fleet.meta_set(lead_id, key, coerced)
    audit_log("pod.config", f"project={project} action=set key={key} value={coerced!r}")
    ui.success(f"Set {key}={coerced} for pod '{project}'")
    if key == "budgetUsd":
        _budget_changed(project, lead_id, cap_removed=not coerced)


def unset_setting(project: str, key: str, *, member: str | None = None) -> None:
    """Clear one pod setting back to its default, or with ``member`` a verify command."""
    if key == "verify" or member is not None:
        if key != "verify" or member is None:
            ui.error("--member goes with verify", "Example: docket pod unset verify --member <id>")
            raise typer.Exit(1)
        _unset_member_verify(project, member)
        return
    lead_id = _lead_for_settings(project)
    if key not in pod.PodSettings.KEYS:
        ui.error(f"unknown pod setting {key!r}", f"Valid keys: {', '.join(pod.PodSettings.KEYS)}")
        raise typer.Exit(1)
    # None reads back exactly like an absent key: the writer's only way to clear one.
    _fleet.meta_set(lead_id, key, None)
    if key == "pipeline":
        with contextlib.suppress(OSError):
            pod.bound_pipeline_path(project).unlink()
    if key == "schedule":
        # docket-schedules.json, not the meta key cleared above, is what the serve sweep reads.
        _sched.unset_schedule(_cfg.SCHEDULE_FILE, project)
    audit_log("pod.config", f"project={project} action=unset key={key}")
    ui.success(f"Unset {key} for pod '{project}'; it falls back to its default")
    if key == "budgetUsd":
        _budget_changed(project, lead_id, cap_removed=True)


@pod_app.command("set")
def cmd_set(
    key: str = typer.Argument(..., help="A pod setting (see docket pod show), or verify"),
    value: str = typer.Argument(..., help="The new value"),
    member: str | None = typer.Option(None, "--member", help="Member id, for verify"),
    pod_name: str | None = pod_option(),
) -> None:
    """Set a pod setting; with --member, set an implementer's verify command.

    Example: docket pod set budgetUsd 5"""
    set_setting(_pod_name(pod_name), key, value, member=member)
    _contract.next_step("docket pod show")


@pod_app.command("unset")
def cmd_unset(
    key: str = typer.Argument(..., help="A pod setting (see docket pod show), or verify"),
    member: str | None = typer.Option(None, "--member", help="Member id, for verify"),
    pod_name: str | None = pod_option(),
) -> None:
    """Clear a pod setting back to its default; with --member, clear a verify command.

    Example: docket pod unset verify --member demo-implementer"""
    unset_setting(_pod_name(pod_name), key, member=member)
    _contract.next_step("docket pod show")


# Persists a docket-owned copy plus its sha256 hash in the Lead's own workspace, never the
# operator's original path, which can drift or disappear -- core/dispatch.py's
# effective_pipeline verifies the copy against this hash on every read.
def _pod_config_set_pipeline(project: str, lead_id: str, path_str: str) -> None:
    """``docket pod set pipeline <file>``: validate *path_str* and
    plan it against the pod's real roster before binding it."""
    path = Path(path_str)
    if not path.is_file():
        ui.error(f"File not found: {path_str}")
        raise typer.Exit(1)
    text = path.read_text(encoding="utf-8")
    result = _pipeline.load_pipeline(text)
    if result.spec is None:
        ui.error(f"Pipeline '{path_str}' is invalid:")
        for e in result.errors:
            ui.console.print(f"  [red]x[/red] {e}")
        raise typer.Exit(1)

    roster = _dispatch.pod_full_roster(project)
    registry = _arch.load_registry(project)
    plan = _orch.resolve_plan(result.spec, roster, registry=registry)
    problems = _pod_apply.unresolvable_pipeline_steps(plan, project)
    if problems:
        ui.error(f"Pipeline '{path_str}' targets a role/agent this pod does not have:")
        for p in problems:
            ui.console.print(f"  [red]x[/red] {p}")
        raise typer.Exit(1)

    digest = _hashlib.sha256(text.encode("utf-8")).hexdigest()
    dest = pod.bound_pipeline_path(project)
    dest.write_text(text, encoding="utf-8")
    dest.chmod(0o600)

    _fleet.meta_set(lead_id, "pipeline", digest)
    audit_log(
        "pod.config",
        f"project={project} action=set key=pipeline file={path_str} hash={digest[:12]}",
    )
    ui.success(f"Bound pipeline '{path_str}' (hash {digest[:12]}...) to pod '{project}'.")


# Two writers for one logical value, same as `pipeline` above: `docket-schedules.json`
# (`cfg.SCHEDULE_FILE`) is this schedule's real source of truth -- it is the file
# `serve.py::_check_schedules` actually reads to fire a dispatch -- while the Lead's meta
# copy exists only so `config get`/`list` can report it through the same generic
# `PodSettings.value_and_source` every other setting uses, instead of a bespoke display path.
def _pod_config_set_schedule(project: str, lead_id: str, spec: str) -> None:
    """``docket pod set schedule <spec>``: validate *spec*, persist it as
    this pod's writer into ``docket-schedules.json``, and mirror it into the Lead's meta
    for display."""
    try:
        coerced = pod.PodSettings.coerce("schedule", spec)
    except pod.PodSettingsError as ex:
        ui.error(str(ex))
        raise typer.Exit(1) from ex

    try:
        _sched.set_schedule(_cfg.SCHEDULE_FILE, project, str(coerced))
    except _sched.ScheduleError as ex:
        ui.error(str(ex))
        raise typer.Exit(1) from ex

    _fleet.meta_set(lead_id, "schedule", coerced)
    audit_log("pod.config", f"project={project} action=set key=schedule value={coerced!r}")
    ui.success(f"Set schedule={coerced} for pod '{project}'.")
