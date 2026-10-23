from __future__ import annotations

from pathlib import Path
from typing import Any

import typer

from docket.agent import conversations as _conv
from docket.agent import memory as _mem
from docket.governance.audit import audit_log
from docket.interfaces.cli.commands import contract as _contract
from docket.interfaces.cli.render import ui
from docket.kernel.home import current_home
from docket.models import selection as _mp
from docket.platform import read_json
from docket.teams import fleet as _fleet
from docket.teams import member_workspace as _member_workspace
from docket.teams import pod
from docket.teams import pod_provisioning as _pp


def _require_members(project: str) -> list[str]:
    members = _pp.pod_member_ids(project)
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


def _reset_ledger(agent_id: str, ws: Path) -> None:
    """Replace the member's HEARTBEAT.md with a fresh ledger."""
    raw = read_json(current_home().meta_path(agent_id))
    hb = ws / _mem.HEARTBEAT_FILE
    hb.write_text(_mem.heartbeat_seed(str(raw.get("name", agent_id))), encoding="utf-8")
    hb.chmod(0o600)


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
            verify_cmd = _pp.validate_verify_cmd(verify_cmd)
        except _pp.VerifyCmdError as ex:
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
                _pp.pod_member_ids(project),
                project_key=project_key,
                role_models=role_models,
            )
        except pod.PodError as ex:
            ui.error(str(ex))
            raise typer.Exit(1) from ex
        ok, msg = _member_workspace.provision_member(
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


def remove_member(project: str, member_id: str, *, yes: bool) -> None:
    """Remove one non-Lead member after confirmation; releases the pod's port range, scratch and
    cache with its last implementer."""
    role = _require_member(project, member_id)
    if role == "lead":
        ui.error(f"{member_id} is the pod's Lead", "Delete the pod instead: docket pod delete")
        raise typer.Exit(1)
    if not _contract.confirm(f"Remove {member_id} and its workspace", yes=yes):
        ui.warn("Aborted.")
        raise typer.Exit(1)
    ok, msg = _pp.teardown_member(member_id)
    if ok:
        ui.success(f"Removed {member_id}")
        if msg:
            ui.dim(f"  {msg}")
    else:
        ui.warn(f"{member_id}: fleet deregistration reported: {msg} (workspace cleaned)")
    audit_log("pod.remove", f"{project} member={member_id} role={role}")
    if role == "implementer":
        remaining = {_fleet.meta_get(mid, "role", "") for mid in _pp.pod_member_ids(project)}
        if "implementer" not in remaining:
            _pp.release_implementer_resources(project)


def reset_member(project: str, member_id: str, *, yes: bool) -> None:
    """Reset a member's ledger and rebuild SOUL/AGENTS/TOOLS from its metadata. MEMORY.md,
    memory/ and the pod's memory.json are left as they are."""
    _require_member(project, member_id)
    if not _contract.confirm(
        f"Reset {member_id}: ledger cleared, workspace files rebuilt", yes=yes
    ):
        ui.warn("Aborted.")
        raise typer.Exit(1)
    ws = current_home().workspace_dir(member_id)
    _reset_ledger(member_id, ws)
    for name, text in _member_workspace.rendered_member_files(member_id).items():
        (ws / name).write_text(text, encoding="utf-8")
        (ws / name).chmod(0o600)
    _fleet.meta_set(member_id, "templateVersion", str(_member_workspace.POD_TEMPLATE_VERSION))
    audit_log("pod.reset", f"{project} member={member_id}")
    ui.success(f"Reset {member_id}: ledger cleared, workspace files rebuilt")


def _delete_pod(project: str, members: list[str]) -> int:
    """Tear down every member of a pod, its resources, history and bindings."""

    for mid in members:
        if _fleet.get_binding(mid):
            _fleet.remove_binding(mid)
        _conv.remove_agent_durable(mid)
        ok, msg = _pp.teardown_member(mid)
        if ok:
            ui.success(f"Removed {mid}")
            if msg:
                ui.dim(f"  {msg}")
        else:
            ui.warn(f"{mid}: fleet deregistration reported: {msg} (workspace cleaned)")
    _pp.free_pod_resources(project)
    _pp.purge_pod_history(project, members)
    audit_log("pod.delete", f"{project} pod ({len(members)} members)")
    ui.success(f"Pod '{project}' deleted")
    return 0
