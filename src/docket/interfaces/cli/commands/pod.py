"""docket pod: the pod group, its roster and its settings.

A *pod* is the set of project-scoped agents for one project: a Lead plus workers, each
with its own workspace; member ids are ``<project>-<role>`` (``-N`` for duplicates).
Composition lives in `teams/pod.py`; provisioning I/O lives in `teams/pod_provisioning.py`
so `interfaces/http/server.py`'s `POST /pods` reaches it without importing `docket.interfaces.cli`. This module
renders around those typed results, so `docket init` and `POST /pods` cannot drift apart.
"""

from __future__ import annotations

from collections.abc import Callable

import typer
from rich.markup import escape

from docket.hops.application import report as _report
from docket.interfaces.cli.commands import contract as _contract
from docket.interfaces.cli.commands import pod_show as _show
from docket.interfaces.cli.commands.pod_members import (
    _delete_pod,
    _require_member,
    _require_members,
    add_members,
    remove_member,
    reset_member,
)
from docket.interfaces.cli.commands.pod_records import cmd_records
from docket.interfaces.cli.commands.pod_routines import routine_app
from docket.interfaces.cli.commands.pod_settings import set_network, set_setting, unset_setting
from docket.interfaces.cli.commands.target import pod_option
from docket.interfaces.cli.render import ui
from docket.kernel.errors import DispatchError
from docket.kernel.home import current_home
from docket.teams import fleet as _fleet
from docket.teams import memory as _pod_memory
from docket.teams import pod
from docket.teams import pod_provisioning as _pp
from docket.teams import pod_settings as _pod_settings

pod_app = typer.Typer(
    name="pod",
    help="Manage this project's pod: members, settings and configuration.",
    no_args_is_help=True,
)


def pod_roles(full: bool, with_roles: str) -> tuple[str, ...]:
    """The software pod's roster from `docket init`'s flags: lean, ``--pod full``, or lean plus
    the ``--with`` roles in the order given. An unknown name raises `pod.PodError`."""
    if full:
        return pod.FULL_POD_ROLES
    extras: list[str] = []
    for raw in with_roles.split(","):
        if not raw.strip():
            continue
        role = pod.normalize_role(raw)
        if role not in (*pod.DEFAULT_POD_ROLES, *extras):
            extras.append(role)
    return (*pod.DEFAULT_POD_ROLES, *extras)


def _render_created(members: list[_pp.ProvisionedMember]) -> list[str]:
    """Render each provisioned member's success line."""
    for m in members:
        ui.success(escape(f"  {m.member_id}  [{m.role}]  {m.model}"))
    return [m.member_id for m in members]


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


@pod_app.command("show")
def cmd_show(
    member: str | None = typer.Argument(None, help="A member id, for its full configuration"),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON"),
    pod_name: str | None = pod_option(),
) -> None:
    """The pod: members, settings and the approval mode dispatch will use, with sources.

    With a member id, that member's whole effective configuration instead.

    Example: docket pod show"""
    project = _contract.require_pod(pod_name)
    _require_members(project)
    if member is not None:
        _require_member(project, member)
    try:
        report = _report.member_report(member) if member else _report.pod_report(project)
    except (DispatchError, _pod_settings.PodSettingsError) as ex:
        ui.error(str(ex))
        raise typer.Exit(1) from ex
    if json_out:
        _contract.emit_json(report)
    elif member:
        _show.render_member(report)
    else:
        _show.render_pod(report)


@pod_app.command("add")
def cmd_add(
    role: str = typer.Argument(..., help="Role archetype name, e.g. reviewer"),
    count: int = typer.Option(1, "--count", "-n", min=1, help="How many members to add"),
    verify: str = typer.Option("", "--verify", help="Verify command for a new implementer"),
    pod_name: str | None = pod_option(),
) -> None:
    """Add members of a role to the pod.

    Example: docket pod add reviewer"""
    project = _contract.require_pod(pod_name)
    if add_members(project, role, count=count, verify_cmd=verify):
        _contract.next_step("docket pod show")
        return
    raise typer.Exit(1)


@pod_app.command("remove")
def cmd_remove(
    member: str = typer.Argument(..., help="Member id, e.g. demo-reviewer"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the confirmation"),
    pod_name: str | None = pod_option(),
) -> None:
    """Remove a member and its workspace. The Lead is removed only with the pod.

    Example: docket pod remove demo-reviewer"""
    remove_member(_contract.require_pod(pod_name), member, yes=yes)
    _contract.next_step("docket pod show")


@pod_app.command("reset")
def cmd_reset(
    member: str = typer.Argument(..., help="Member id, e.g. demo-implementer"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the confirmation"),
    pod_name: str | None = pod_option(),
) -> None:
    """Reset a member's ledger and rebuild its workspace files from its metadata.

    Example: docket pod reset demo-implementer"""
    reset_member(_contract.require_pod(pod_name), member, yes=yes)
    _contract.next_step("docket pod show")


@pod_app.command("delete")
def cmd_delete(
    confirm: str | None = typer.Option(None, "--confirm", help="The pod name, to confirm"),
    pod_name: str | None = pod_option(),
) -> None:
    """Destroy the pod: every member, workspace, session and trace. The audit log stays.

    Example: docket pod delete --confirm demo"""
    project = _contract.require_pod(pod_name)
    members = _pp.pod_member_ids(project)
    if not members:
        if current_home().workspace_dir(project).is_dir():
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


memory_app = typer.Typer(
    name="memory",
    help="What this pod has learned about its repository: review, approve, revert, reset.",
    no_args_is_help=True,
)
pod_app.add_typer(memory_app)
pod_app.add_typer(routine_app)
pod_app.command("records")(cmd_records)

_MEMORY_STATUSES = ("accepted", "pending", "refused")


def _memory_pod(pod_name: str | None) -> str:
    project = _contract.require_pod(pod_name)
    _require_members(project)
    return project


def _memory_decide(project: str, decide: Callable[[], _pod_memory.MemoryEntry]) -> None:
    try:
        decide()
    except _pod_memory.PodMemoryError as ex:
        ui.error(str(ex), f"See: docket pod memory list --pod {project}")
        raise typer.Exit(1) from ex


@memory_app.command("list")
def cmd_memory_list(
    status: str | None = typer.Option(
        None, "--status", help="Only entries that are accepted, pending or refused"
    ),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON"),
    pod_name: str | None = pod_option(),
) -> None:
    """List the pod's memory entries with their status and why.

    Example: docket pod memory list --status pending"""
    project = _memory_pod(pod_name)
    if status is not None and status not in _MEMORY_STATUSES:
        ui.error(f"Unknown status '{status}'", f"Use one of: {', '.join(_MEMORY_STATUSES)}")
        raise typer.Exit(1)
    entries = _pod_memory.list_entries(project, status)
    if json_out:
        _contract.emit_json([e.to_dict() for e in entries])
        return
    if not entries:
        ui.dim(f"No memory entries in pod '{project}'.")
        return
    ui.table(
        [[e.id, e.status, e.kind, e.subject, e.note, e.reason] for e in entries],
        ["ID", "STATUS", "KIND", "SUBJECT", "NOTE", "WHY"],
    )


@memory_app.command("approve")
def cmd_memory_approve(
    entry_id: str = typer.Argument(..., metavar="ID", help="A pending entry id"),
    pod_name: str | None = pod_option(),
) -> None:
    """Accept a pending entry; the pod's next prompt carries it.

    Example: docket pod memory approve mem-0123456789"""
    project = _memory_pod(pod_name)
    _memory_decide(project, lambda: _pod_memory.approve(project, entry_id, actor="cli"))
    ui.success(f"Approved {entry_id}")
    _contract.next_step(f"docket pod memory list --pod {project}")


@memory_app.command("refuse")
def cmd_memory_refuse(
    entry_id: str = typer.Argument(..., metavar="ID", help="A pending entry id"),
    reason: str = typer.Option(..., "--reason", help="Why it is refused"),
    pod_name: str | None = pod_option(),
) -> None:
    """Refuse a pending entry; the same fact is not stored again.

    Example: docket pod memory refuse mem-0123456789 --reason stale"""
    project = _memory_pod(pod_name)
    _memory_decide(project, lambda: _pod_memory.refuse(project, entry_id, reason, actor="cli"))
    ui.success(f"Refused {entry_id}")
    _contract.next_step(f"docket pod memory list --pod {project}")


@memory_app.command("revert")
def cmd_memory_revert(
    entry_id: str = typer.Argument(..., metavar="ID", help="An accepted entry id"),
    pod_name: str | None = pod_option(),
) -> None:
    """Take an accepted entry out of every prompt; it stays as a refusal.

    Example: docket pod memory revert mem-0123456789"""
    project = _memory_pod(pod_name)
    _memory_decide(project, lambda: _pod_memory.revert(project, entry_id, actor="cli"))
    ui.success(f"Reverted {entry_id}")
    _contract.next_step(f"docket pod memory list --pod {project}")


@memory_app.command("reset")
def cmd_memory_reset(
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the confirmation"),
    pod_name: str | None = pod_option(),
) -> None:
    """Remove every memory entry of the pod after confirmation.

    Example: docket pod memory reset --yes"""
    project = _memory_pod(pod_name)
    count = len(_pod_memory.list_entries(project))
    if not _contract.confirm(f"Remove all {count} memory entries of pod {project}", yes=yes):
        ui.warn("Aborted.")
        raise typer.Exit(1)
    removed = _pod_memory.reset(project, actor="cli")
    ui.success(f"Removed {removed} memory entries from pod '{project}'")
    _contract.next_step(f"docket pod memory list --pod {project}")


@pod_app.command("set")
def cmd_set(
    key: str = typer.Argument(..., help="A pod setting (see docket pod show), or verify"),
    value: str = typer.Argument(..., help="The new value"),
    member: str | None = typer.Option(None, "--member", help="Member id, for verify"),
    widen: bool = typer.Option(
        False,
        "--widen",
        help="With network open: let this pod reach the network on a machine at none (asks first)",
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the --widen confirmation"),
    pod_name: str | None = pod_option(),
) -> None:
    """Set a pod setting; with --member, set an implementer's verify command.

    Example: docket pod set budgetUsd 5"""
    project = _contract.require_pod(pod_name)
    if key == "network":
        set_network(project, value, widen=widen, yes=yes)
    elif widen:
        ui.error("--widen applies only to network", "Example: docket pod set network open --widen")
        raise typer.Exit(1)
    else:
        set_setting(project, key, value, member=member)
    _contract.next_step("docket pod show")


@pod_app.command("unset")
def cmd_unset(
    key: str = typer.Argument(..., help="A pod setting (see docket pod show), or verify"),
    member: str | None = typer.Option(None, "--member", help="Member id, for verify"),
    pod_name: str | None = pod_option(),
) -> None:
    """Clear a pod setting back to its default; with --member, clear a verify command.

    Example: docket pod unset verify --member demo-implementer"""
    unset_setting(_contract.require_pod(pod_name), key, member=member)
    _contract.next_step("docket pod show")
