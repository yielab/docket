"""docket pod: the pod group, its roster and its settings.

A *pod* is the set of project-scoped agents for one project: a Lead plus workers, each
with its own workspace; member ids are ``<project>-<role>`` (``-N`` for duplicates).
Composition lives in `core/pod.py`; provisioning I/O lives in `core/pod_provisioning.py`
so `serve.py`'s `POST /pods` reaches it without importing `docket.cli`. This module
renders around those typed results, so `docket init` and `POST /pods` cannot drift apart.
"""

from __future__ import annotations

import contextlib
import getpass as _getpass
import hashlib as _hashlib
import json as _json
import os
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any, Literal

import typer
from pydantic import ValidationError
from rich.markup import escape
from rich.table import Table

import docket.config as _cfg
from docket import ui
from docket.cli import _contract
from docket.cli import _pod_show as _show
from docket.cli._target import TargetError, pod_option, resolve_pod
from docket.core import answers as _answers
from docket.core import archetypes as _arch
from docket.core import dispatch as _dispatch
from docket.core import fleet as _fleet
from docket.core import interruptions as _interruptions
from docket.core import memory as _mem
from docket.core import models_policy as _mp
from docket.core import operator_contract as _oc
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


def _actor() -> str:
    """The OS user running this CLI invocation, falling back to '?' (mirrors
    `core.audit`'s own username lookup)."""
    try:
        return _getpass.getuser()
    except Exception:
        return "?"


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


def parse_pod_roles(args: list[str]) -> tuple[str, ...]:
    """Pod composition from `docket init` flags. Default = lean pod (lead + implementer);
    ``--pod full`` = the four-role pod; ``--with reviewer,tester`` = lean plus the named
    roles. Unknown role names are ignored (the lean default still applies)."""
    if "--pod" in args:
        i = args.index("--pod")
        if i + 1 < len(args) and args[i + 1].lower() == "full":
            return pod.FULL_POD_ROLES
    extras: list[str] = []
    for i, tok in enumerate(args):
        spec = ""
        if tok.startswith("--with="):
            spec = tok[len("--with=") :]
        elif tok == "--with" and i + 1 < len(args):
            spec = args[i + 1]
        if spec:
            for raw in spec.split(","):
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


def dispatch(project: str, sub: str | None, extra: list[str]) -> None:
    """Entry point for the `docket pod` command (wired in cli/__init__.py)."""
    action = sub or "list"
    if action == "delegate":
        _pod_delegate(project, extra)
    elif action == "answer":
        _pod_answer(project, extra)
    elif action == "explain":
        _pod_explain(project, extra)
    elif action == "pregrant":
        _pod_pregrant(project, extra)
    elif action == "queue":
        _pod_queue(project, extra)
    elif action == "sync":
        _pod_sync(project, extra)
    elif action == "apply":
        _pod_apply_cmd(project, extra)
    elif action == "export":
        _pod_export_cmd(project, extra)
    elif action == "corrections":
        _pod_corrections(project, extra)
    elif action == "evidence":
        _pod_evidence(project, extra)
    elif action == "worktrees":
        _pod_worktrees(project, extra)
    else:
        ui.error(
            f"Unknown pod action {action!r}. Use: "
            "delegate | answer | explain | pregrant | queue | dispatch | sync | "
            "apply | export | corrections | evidence | worktrees."
        )
        raise typer.Exit(1)


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


def _pod_worktrees(project: str, extra: list[str]) -> None:
    """``worktrees prune [--dry-run] [--force]``: remove finished tasks' worktrees."""
    flags = set(extra[1:])
    if not extra or extra[0] != "prune" or not flags <= {"--dry-run", "--force"}:
        ui.error("Usage: docket pod <project> worktrees prune [--dry-run] [--force]")
        raise typer.Exit(1)
    entries = _pp.prune_task_worktrees(
        project, force="--force" in flags, dry_run="--dry-run" in flags
    )
    if not entries:
        ui.info("No finished task worktrees to prune.")
        return
    for e in entries:
        line = f"{e.task_id}: {e.action}" + (f" ({e.reason})" if e.reason else "")
        (ui.warn if e.action == "kept" else ui.info)(line)


def _pod_delegate(project: str, extra: list[str]) -> None:
    """Queue a task: ``docket pod <project> delegate [--priority P] [--brief FILE.json]
    <task>``. ``--brief`` validates the file as a `TaskBrief` and passes it through;
    an invalid file exits non-zero and enqueues nothing."""
    priority = "normal"
    brief_path: str | None = None
    rest: list[str] = []
    i = 0
    while i < len(extra):
        if extra[i] in ("--priority", "-p"):
            if i + 1 >= len(extra):
                ui.error("Missing priority. Use: high | normal | low")
                raise typer.Exit(1)
            priority = extra[i + 1]
            i += 2
        elif extra[i] == "--brief":
            if i + 1 >= len(extra):
                ui.error("Missing file. Use: --brief FILE.json")
                raise typer.Exit(1)
            brief_path = extra[i + 1]
            i += 2
        else:
            rest.append(extra[i])
            i += 1

    brief: dict[str, Any] | None = None
    if brief_path is not None:
        try:
            raw = _json.loads(Path(brief_path).read_text(encoding="utf-8"))
            _oc.TaskBrief.model_validate(raw)
        except (OSError, _json.JSONDecodeError, ValidationError) as exc:
            ui.error(f"Invalid brief file '{brief_path}': {exc}")
            raise typer.Exit(1) from exc
        brief = raw

    description = " ".join(rest)
    if not description.strip():
        ui.error("Usage: docket pod <project> delegate [--priority high|normal|low] <task>")
        raise typer.Exit(1)
    if priority not in ("high", "normal", "low"):
        ui.error(f"Invalid priority '{priority}'. Use: high | normal | low")
        raise typer.Exit(1)
    if len(description) > 500:
        ui.error(f"Description too long ({len(description)} chars). Limit: 500.")
        raise typer.Exit(1)
    try:
        task = _dispatch.enqueue_task(project, description, priority, brief=brief)
    except _dispatch.DispatchError as ex:
        ui.error(str(ex))
        raise typer.Exit(1) from ex
    ui.success(escape(f"Queued for pod '{project}': [{task['id']}] {description}"))
    ui.info(f"Run the pipeline: docket pod {project} dispatch")
    ui.dim(f"  {_interruption_summary(project)}")


def _pod_answer(project: str, extra: list[str]) -> None:
    """Answer a parked question: ``docket pod <project> answer <task-id> [text]
    [--option <id>] [--field k=v]... [--decline]``. Bare ``text`` fills a one-property
    schema; ``--option`` picks one of a consult's options (required when it has any);
    ``--field`` names each property explicitly; ``--decline`` ignores all three."""
    usage = (
        "Usage: docket pod <project> answer <task-id> [text] [--option <id>] "
        "[--field k=v]... [--decline]"
    )
    task_id: str | None = None
    text_parts: list[str] = []
    fields: dict[str, str] = {}
    option_id: str | None = None
    decline = False
    i = 0
    while i < len(extra):
        tok = extra[i]
        if tok == "--field":
            if i + 1 >= len(extra) or "=" not in extra[i + 1]:
                ui.error("Usage: --field name=value")
                raise typer.Exit(1)
            key, value = extra[i + 1].split("=", 1)
            fields[key] = value
            i += 2
        elif tok == "--option":
            if i + 1 >= len(extra):
                ui.error("Usage: --option <id>")
                raise typer.Exit(1)
            option_id = extra[i + 1]
            i += 2
        elif tok == "--decline":
            decline = True
            i += 1
        elif task_id is None:
            task_id = tok
            i += 1
        else:
            text_parts.append(tok)
            i += 1

    if task_id is None:
        ui.error(usage)
        raise typer.Exit(1)

    if decline:
        action = "decline"
        content: dict[str, Any] | None = None
    else:
        action = "accept"
        content = dict(fields)
        text = " ".join(text_parts).strip()
        task = next((t for t in _dispatch.read_tasks(project) if t.get("id") == task_id), None)
        if task is None:
            ui.error(f"Task '{task_id}' not found in pod '{project}'.")
            raise typer.Exit(1)
        question = task.get("question")
        if not isinstance(question, dict):
            ui.error(f"Task '{task_id}' has no pending question.")
            raise typer.Exit(1)
        if text:
            properties = question.get("requestedSchema", {}).get("properties", {})
            if len(properties) == 1:
                (prop_name,) = properties
                content.setdefault(prop_name, text)
            else:
                ui.error(
                    "A bare text answer requires a single-property question; use "
                    "--field name=value for each property instead."
                )
                raise typer.Exit(1)
        raw_options = question.get("options")
        option_ids = (
            [str(o.get("id", "")) for o in raw_options if isinstance(o, dict)]
            if isinstance(raw_options, list)
            else []
        )
        if option_id:
            content["optionId"] = option_id
        elif option_ids:
            ui.error(
                "This question has options; pick one with --option <id>: "
                + ", ".join(option_ids)
                + " (or --decline)."
            )
            raise typer.Exit(1)
        if not content:
            ui.error(usage)
            raise typer.Exit(1)

    try:
        _answers.answer_task(project, task_id, action, content, channel="cli", actor=_actor())
    except _answers.AnswerRejected as exc:
        ui.error(f"Answer blocked by policy '{exc.policy_id}'.")
        raise typer.Exit(1) from exc
    except _answers.AnswerError as exc:
        ui.error(str(exc))
        raise typer.Exit(1) from exc
    ui.success(f"Answered task '{task_id}' in pod '{project}' ({action}).")


def _caller_default() -> Literal["wait", "park"]:
    """Same TTY resolution `_pod_dispatch` applies to an unset pod `approvalMode`."""
    return "wait" if sys.stdin.isatty() else "park"


def _interruption_summary(project: str) -> str:
    """One line for `delegate`'s own summary (ADR 0016 SS10): what could pause this pod's
    next dispatch before it starts."""
    items = _interruptions.forecast(project, caller_default=_caller_default())
    askers = [i for i in items if i.kind in _interruptions.ASK_KINDS]
    if not askers:
        return _interruptions.NOTHING_WILL_ASK
    counts: dict[str, int] = {}
    for i in askers:
        counts[i.kind] = counts.get(i.kind, 0) + 1
    parts = [f"{n} {kind.replace('_', ' ')}" for kind, n in sorted(counts.items())]
    return f"May ask you: {', '.join(parts)} — see: docket pod {project} explain interruptions"


def _pod_explain(project: str, extra: list[str]) -> None:
    """``docket pod <project> explain interruptions [--json]`` — forecast what could pause
    a task before it is dispatched (ADR 0016 SS10)."""
    if not pod_member_ids(project):
        ui.error(f"No pod for '{project}'. Create one first: docket init {project}")
        raise typer.Exit(1)
    as_json = "--json" in extra
    topic = next((a for a in extra if a != "--json"), "")
    if topic != "interruptions":
        ui.error("Usage: docket pod <project> explain interruptions [--json]")
        raise typer.Exit(1)

    items = _interruptions.forecast(project, caller_default=_caller_default())
    if as_json:
        print(
            _json.dumps(
                {
                    "pod": project,
                    "interruptions": [
                        {"kind": i.kind, "description": i.description, "detail": i.detail}
                        for i in items
                    ],
                },
                indent=2,
            )
        )
        return

    ui.header(f"Interruption forecast — {project}")
    askers = [i for i in items if i.kind in _interruptions.ASK_KINDS]
    if not askers:
        ui.console.print(f"  {_interruptions.NOTHING_WILL_ASK}")
    else:
        for i in askers:
            ui.console.print(escape(f"  - {i.description}"))
    mode_item = next((i for i in items if i.kind == "mode"), None)
    if mode_item is not None:
        ui.console.print()
        ui.dim(f"  {mode_item.description}")
    always_on = [i for i in items if i.kind == "high_risk_class"]
    if always_on:
        ui.dim("  Always enforced, for visibility:")
        for i in always_on:
            ui.dim(escape(f"    - {i.description}"))
    channels = [i for i in items if i.kind == "channel"]
    if channels:
        ui.dim("  Will notify:")
        for i in channels:
            ui.dim(escape(f"    - {i.description}"))


def _pod_pregrant(project: str, extra: list[str]) -> None:
    """``docket pod <project> pregrant <task-id> "<command>" [--tool bash]`` — a single-use
    pre-grant for one exact command on one task, ahead of dispatch (ADR 0016 SS10)."""
    if not pod_member_ids(project):
        ui.error(f"No pod for '{project}'. Create one first: docket init {project}")
        raise typer.Exit(1)
    tool = "bash"
    rest: list[str] = []
    i = 0
    while i < len(extra):
        if extra[i] == "--tool":
            if i + 1 >= len(extra):
                ui.error("Missing tool name. Use: --tool bash")
                raise typer.Exit(1)
            tool = extra[i + 1]
            i += 2
        else:
            rest.append(extra[i])
            i += 1
    if len(rest) < 2:
        ui.error('Usage: docket pod <project> pregrant <task-id> "<command>" [--tool bash]')
        raise typer.Exit(1)
    task_id, command = rest[0], " ".join(rest[1:])

    try:
        token = _interruptions.record_pregrant(
            project, task_id, command, tool=tool, channel="cli", actor=_actor()
        )
    except _interruptions.InterruptionsError as exc:
        ui.error(str(exc))
        raise typer.Exit(1) from exc
    ui.success(
        escape(f"Pre-granted '{command}' on task '{task_id}' in pod '{project}' (token={token}).")
    )


def _pod_queue(project: str, extra: list[str]) -> None:
    """Show the pod's task queue, or ``queue --retry <task-id>`` to un-block one task.
    A ``blocked`` task never retries on its own — ``--retry`` is the explicit,
    single-task way back to ``pending``; a budget change un-blocks the whole queue."""
    if "--retry" in extra:
        i = extra.index("--retry")
        task_id = extra[i + 1] if i + 1 < len(extra) else ""
        if not task_id:
            ui.error("Usage: docket pod <project> queue --retry <task-id>")
            raise typer.Exit(1)
        if _dispatch.retry_task(project, task_id):
            ui.success(f"Requeued '{task_id}' for pod '{project}' — status set to pending.")
        else:
            ui.error(f"'{task_id}' is not a blocked task in pod '{project}'.")
            raise typer.Exit(1)
        return

    tasks = _dispatch.read_tasks(project)
    if not tasks:
        ui.warn(f"No tasks queued for pod '{project}'.")
        return
    table = Table(title=f"Pod queue — {project}")
    table.add_column("ID", style="bold")
    table.add_column("PRI")
    table.add_column("STATUS")
    table.add_column("COST", justify="right")
    table.add_column("DESCRIPTION", style="dim")
    for t in tasks:
        cost = t.get("costUsd")
        table.add_row(
            str(t.get("id", "?"))[:18],
            str(t.get("priority", "normal")),
            str(t.get("status", "?")),
            f"${float(cost):.4f}" if cost else "—",
            str(t.get("description", "")),
        )
    ui.console.print(table)


def _implementer_member(project: str, member_id: str) -> None:
    """Exit 1 unless ``member_id`` is an implementer of the pod (the only role with a verify gate)."""
    role = _require_member(project, member_id)
    if role != "implementer":
        ui.error(
            f"'{member_id}' is a {role or 'unknown role'}",
            "verify applies only to implementers",
        )
        raise typer.Exit(1)


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


def _pod_sync(project: str, extra: list[str]) -> None:
    """``docket pod <project> sync [--dry-run]`` -- re-render stale SOUL/AGENTS/TOOLS
    from the current archetype + metadata; ``--dry-run`` diffs without writing.
    Never touches ``INSTRUCTIONS.md`` (operator-owned); an in-sync pod is a no-op."""
    dry_run = "--dry-run" in extra
    member_ids = pod_member_ids(project)
    if not member_ids:
        ui.warn(f"No pod found for '{project}'. Create one with: docket init {project}")
        return
    stale_ids = []
    for member_id in member_ids:
        status = _pp.member_sync_status(member_id)
        if status is None or not status.stale:
            continue
        stale_ids.append(member_id)
        if dry_run:
            ui.console.print(
                f"[bold]{member_id}[/bold] — stale "
                f"(v{status.stored_template_version or '?'} -> v{_pp.POD_TEMPLATE_VERSION})"
            )
            for name, diff in status.diffs.items():
                ui.console.print(escape(diff) if diff else f"  {name}: no content change")
        else:
            written = _pp.resync_member(member_id)
            audit_log("pod.sync", f"member={member_id} files=({','.join(written)})")
            ui.success(f"  {member_id}: re-rendered {', '.join(written) or '(version stamp only)'}")
    if not stale_ids:
        ui.success(f"Pod '{project}' is already in sync.")
    elif dry_run:
        ui.dim(f"  {len(stale_ids)} member(s) stale — rerun without --dry-run to apply.")


def _pod_apply_default_dir(project: str) -> Path:
    """``<codebase>/.docket`` from the Lead's own recorded meta -- the default
    ``apply`` reads when no directory is given."""
    lead_id = pod.member_id(project, "lead")
    codebase = _fleet.meta_get(lead_id, "codebase", "")
    return Path(codebase) / ".docket"


def render_apply_header(project: str, directory: Path, summary: _pod_apply.RecipeSummary) -> None:
    """Print ``Apply plan``, the recipe's own ``description`` when set, then its derived
    summary line -- shown before the plan itself. Shared by ``pod <p> apply`` and ``docket
    init``/``--recipe`` so the two never render a recipe differently."""
    ui.header(f"Apply plan — {project} <- {directory}")
    if summary.description:
        ui.console.print(escape(summary.description))
    ui.console.print(f"  {escape(summary.render())}")


def render_apply_plan(plan: _pod_apply.ApplyPlan) -> None:
    """Print an apply plan one item per line, then one exporter-state line per named
    destination (``render_exporter_states``). Shared by ``pod <p> apply`` and ``docket init``;
    the action is escaped because Rich would otherwise read ``[add]`` as a style tag."""
    for item in plan.items:
        ui.console.print(f"  {escape(f'[{item.action}]')} {item.kind}: {item.name}")
        if item.note:
            ui.console.print(f"      {escape(item.name)}: {escape(item.note)}")
    render_exporter_states(plan.exporters)


def render_exporter_states(names: tuple[str, ...]) -> None:
    """Print one line per exporter in *names* -- its state and (unless ``enabled``) the exact
    enable command -- never activating anything (ADR 0014 rule 7). Shared by
    ``render_apply_plan`` and ``docket recipes show``, so the two never disagree."""
    if not names:
        return
    from docket.core import exporter as _exporter

    catalog = _exporter.load_catalog()
    for name in names:
        spec = catalog.get(name)
        if spec is None:
            continue  # named at apply time; the catalog may have since dropped it
        state, missing = _exporter.activation_state(spec, health=None)
        if state == "enabled":
            line = f"exporter {name}: enabled"
        elif state == "needs credential":
            line = (
                f"exporter {name}: needs credential {', '.join(missing)} "
                f"-> docket exporters enable {name}"
            )
        else:
            line = f"exporter {name}: {state} -> docket exporters enable {name}"
        ui.console.print(f"  {escape(line)}")


def _pod_apply_cmd(project: str, extra: list[str]) -> None:
    """``docket pod <project> apply [<name|dir>] [--dry-run] [--json]`` -- plan and, unless
    ``--dry-run``, write a recipe/manifest directory onto this pod; a bare name resolves to a
    shipped recipe as ``init --recipe`` does. An invalid manifest exits 1 with nothing written."""
    dry_run = "--dry-run" in extra
    json_out = "--json" in extra
    rest = [a for a in extra if a not in ("--dry-run", "--json")]
    if len(rest) > 1:
        ui.error("Usage: docket pod <project> apply [<name|dir>] [--dry-run] [--json]")
        raise typer.Exit(1)

    try:
        directory = _pod_apply.resolve_recipe(rest[0]) if rest else _pod_apply_default_dir(project)
        plan = _pod_apply.plan_apply(project, directory)
    except _pod_apply.PodApplyError as ex:
        ui.error(str(ex))
        raise typer.Exit(1) from ex

    if json_out:
        print(
            _json.dumps(
                {"items": [asdict(item) for item in plan.items]},
                indent=2,
            )
        )
    else:
        render_apply_header(project, directory, _pod_apply.summarize_recipe(directory))
        render_apply_plan(plan)

    if dry_run:
        return

    result = _pod_apply.apply(plan)
    if not json_out:
        changed = [item for item in result.items if item.action != "skip"]
        if changed:
            ui.success(f"Applied {len(changed)} change(s) to pod '{project}' from {directory}.")
        else:
            ui.success(f"Pod '{project}' already matches {directory}.")


def _pod_export_cmd(project: str, extra: list[str]) -> None:
    """``docket pod <project> export [<dir>] [--force]`` -- write this pod's own scope into
    ``<dir>``, defaulting to ``<codebase>/.docket`` like ``apply``. Refuses a non-empty
    ``<dir>`` unless ``--force``; nothing is written on any refusal."""
    force = "--force" in extra
    rest = [a for a in extra if a != "--force"]
    if len(rest) > 1:
        ui.error("Usage: docket pod <project> export [<dir>] [--force]")
        raise typer.Exit(1)
    directory = Path(rest[0]) if rest else _pod_apply_default_dir(project)

    if directory.exists() and any(directory.iterdir()) and not force:
        ui.error(f"'{directory}' is not empty. Use --force to overwrite.")
        raise typer.Exit(1)

    try:
        _pod_apply.export_pod(project, directory)
    except _pod_apply.PodApplyError as ex:
        ui.error(str(ex))
        raise typer.Exit(1) from ex

    audit_log("pod.export", f"project={project} dir={directory}")
    ui.success(f"Exported pod '{project}' to {directory}.")


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


def _pod_corrections(project: str, extra: list[str]) -> None:
    """Show the pod's corrections ledger (deny reasons, REQUEST-CHANGES, declined answers).
    ``docket pod <project> corrections [--json]`` prints a table or JSON."""
    from docket.core import corrections as _corrections

    as_json = "--json" in extra

    records = _corrections.read(project)
    if not records:
        ui.warn(f"No corrections recorded for pod '{project}'.")
        return

    if as_json:
        print(_json.dumps({"pod": project, "corrections": records}, indent=2))
        return

    table = Table(title=f"Corrections — {project}")
    table.add_column("TIMESTAMP", style="dim")
    table.add_column("KIND")
    table.add_column("ROLE")
    table.add_column("TASK")
    table.add_column("TEXT", style="dim")

    for record in records:
        ts = str(record.get("ts", ""))[:19]  # YYYY-MM-DDTHH:MM:SS
        kind = str(record.get("kind", ""))
        role = str(record.get("role", ""))
        task = str(record.get("taskId", ""))[:18]
        text = str(record.get("text", ""))
        # Truncate text to 80 chars
        if len(text) > 80:
            text = text[:77] + "..."

        table.add_row(ts, kind, role, task, text)

    ui.console.print(table)


def _pod_evidence(project: str, extra: list[str]) -> None:
    """``docket pod <project> evidence <task> [--json]``: what the task's hops kept.
    ``--json`` prints the evidence-v1 document exactly as ``core.evidence`` builds it."""
    from docket.core import evidence as _evidence

    task_ids = [a for a in extra if not a.startswith("--")]
    if len(task_ids) != 1:
        ui.error("Usage: docket pod <project> evidence <task-id> [--json]")
        raise typer.Exit(1)
    try:
        ev = _evidence.task_evidence(project, task_ids[0])
    except _evidence.EvidenceNotFound as exc:
        ui.error(str(exc))
        raise typer.Exit(1) from exc

    if "--json" in extra:
        print(ev.model_dump_json(by_alias=True))
        return

    table = Table(title=f"Evidence - {project} {ev.task_id} ({ev.status})")
    for col in ("HOP", "ROLE", "OK", "VERDICT", "VERIFY", "COMMIT", "TOKENS IN", "TOKENS OUT"):
        table.add_column(col)
    for hop in ev.hops:
        table.add_row(
            hop.step_id,
            hop.role,
            "yes" if hop.ok else "no",
            hop.verdict or "-",
            str(hop.verify.exit_code) if hop.verify else "-",
            hop.commit[:8] if hop.commit else "-",
            str(hop.usage.input) if hop.usage else "-",
            str(hop.usage.output) if hop.usage else "-",
        )
    ui.console.print(table)


def cmd_pod(
    ctx: typer.Context,
    project: str = typer.Argument(..., help="Project (pod) id"),
    sub: str | None = typer.Argument(
        None,
        help=(
            "list | add <role> [--verify CMD] | remove <member-id> | "
            "set-verify <member-id> CMD | config [get|set <key> <value>|unset <key>] | "
            "sync [--dry-run] | apply [<name|dir>] [--dry-run] [--json] | "
            "export [<dir>] [--force]"
        ),
    ),
) -> None:
    """Manage a project's pod: list members, add/remove a role, set an
    implementer's verify command, and run its dispatch pipeline.

    A pod is the isolated team of project-scoped agents created by
    `docket init`; `pod <project> add <role>` extends an existing one. Every
    member has its own permission-locked workspace, so no role is ever
    shared between projects. See docs/AGENT-TEAMS.md.

    Subcommands:
      list (default)   show the pod's members and their roles
      add <role>       [--count N|-n N] [--verify "<cmd>"]. Role is validated
                        against the open role-archetype registry
                        (`docket roles`), not a hardcoded
                        implementer|reviewer|tester list -- a blueprint role
                        or any user-defined archetype works too. The Lead
                        is unique and cannot be added this way. Duplicated
                        roles get `-2`, `-3` ids. `--count`/`-n` adds several
                        at once. `--verify "<cmd>"` sets the mechanical
                        verification gate dispatch runs after that member's
                        hop -- written into the new member's
                        `.docket-meta.json` (`verifyCmd`) and documented in
                        its TOOLS.md; passing it for a non-implementer role
                        is silently ignored with a warning, since only an
                        Implementer hop is verify-gated. A new member
                        inherits the pod's workspaceKind/workDir/blueprint
                        from its existing members.
      remove <id>      remove one member by id
      set-verify <id> "<cmd>"
                       set (or change) the verify command on an existing
                        Implementer -- the only public way to do this short
                        of the internal debug command. Rewrites the member's
                        TOOLS.md. Validated (no NUL/newline, length-capped)
                        and audit-logged (`pod.set-verify`); runs at dispatch
                        time in the Implementer's git worktree when one
                        exists, falling back to the pod's shared codebase
                        root, then the member's own workspace dir.
      config           [get|set <key> <value>|unset <key>] [--json]. Typed,
                        validated dispatch settings on the pod's Lead
                        (`core.pod.PodSettings`): `budgetUsd`, `maxReworkCycles`,
                        `turnTimeoutS`, `verifyTimeoutS`. `get` (default) shows
                        each key's effective value and whether it is `set` or
                        `default`; `--json` emits the same as a bare object --
                        see cli-json-shapes.spec.md. `set` validates before
                        writing (an invalid value exits 1, nothing persisted)
                        and audit-logs `pod.config`; `unset` removes an
                        override, falling back to the built-in default. A
                        stored value that fails validation (e.g. a hand-edited
                        `.docket-meta.json`) refuses `config get` and
                        `dispatch` alike, naming the key, instead of silently
                        substituting the default.
      delegate <task>  [--priority high|normal|low]. Queue a task on the
                        pod's task queue (in the Lead's workspace). Priority
                        defaults to normal. The description is capped at 500
                        characters. Queues only -- run it with `dispatch`.
      queue            [--retry <task-id>]. Show the queue with per-task
                        status (pending/running/done/failed/blocked) and
                        estimated cost. `--retry` moves one blocked task back
                        to pending -- the explicit, single-task way around a
                        reached budget cap (`docket profile <lead-id>
                        --budget`/`--resume` un-blocks every task in the pod
                        at once instead).
      dispatch         [--resume] [--timeout <seconds>]. Run the pod's
                        pending (and, with --resume, crash-recoverable) tasks
                        through its pipeline -- one real agent turn per hop:
                        Lead -> Implementer -> Reviewer (if present) ->
                        Tester (if present). Only the roles the pod actually
                        has take part. Each task is claimed under a filelock
                        before its first hop runs, so two dispatchers can
                        never double-run the same task, and each hop is
                        persisted as it completes so a crash loses at most
                        the in-flight hop. `--resume` also reclaims any task
                        a prior dispatcher left failed with a stale claim
                        or as `dispatch_refused` (a deterministic refusal
                        settled mid-task), and counts a still-`running`
                        task as work so the stale-claim sweep can judge it,
                        continuing from its last persisted hop. `--timeout`
                        overrides both the agent-turn timeout and the
                        verifyCmd timeout for this run only (otherwise each
                        falls back to the pod's own configured timeouts,
                        then a 300s default).
      sync             [--dry-run]. Re-render SOUL.md/AGENTS.md/TOOLS.md for
                        every member whose managed files have drifted from
                        the current archetype and stored metadata (a
                        template bump, or a role's own archetype content
                        changing). `--dry-run` prints the diff without
                        writing; without it, each stale member is rewritten
                        and its metadata restamped (audit-logged as
                        `pod.sync`). `INSTRUCTIONS.md` is operator-owned and
                        is never read, written, or diffed by this command --
                        an already-current pod changes nothing.
      apply [<name|dir>]  [--dry-run] [--json]. Apply a recipe/manifest
                        directory (role YAML, `pipeline.yaml`, and a small
                        `pod.yaml` naming `members`/`settings`/`pipeline`) to
                        this pod in one command, composing the same writers
                        `roles add`/`add <role>`/`config set pipeline`/
                        `config set <key> <value>` already use. A directory
                        path if one exists there, else a shipped recipe name
                        (`docket recipes list`) as
                        `init --recipe` resolves it; default `<codebase>/.docket`. Validates
                        everything -- roles, the roster the pipeline would
                        resolve against once `members` join, and every
                        setting -- before writing anything; an invalid
                        manifest exits 1 naming the problem with nothing
                        written. Idempotent: applying the same directory
                        twice plans every item `skip` the second time and
                        writes nothing. `--dry-run` prints the plan without
                        writing. Audit-logged once as `pod.apply`, only when
                        something actually changed.
      export [<dir>]   [--force]. Write this pod's own scope -- pod-overlay
                        `roles/*.yaml`, this pod's own `policies/*`, a
                        bound `pipeline.yaml` copy (if any), and a `pod.yaml`
                        naming non-Lead `members` and every non-default
                        `setting` -- into `<dir>`, the same shape `apply`
                        reads back. `<dir>` defaults to `<codebase>/.docket`,
                        like `apply`. Global scope (the operator's own role
                        overlay, fleet-wide policies, other pods) is never
                        exported. Refuses a non-empty `<dir>` unless
                        `--force`, which overwrites any same-named file
                        already there. Audit-logged as `pod.export`.

    Dispatch guarantees: budget-gated with real auto-pause (checked before
    each hop against the Lead's cap; over budget leaves the task blocked and
    pauses the pod's Lead until `docket profile <project>-lead --resume`); a
    timed-out or daemon-error hop retries in place (linear backoff, small
    per-role budget) before failing, a real non-zero exit or bad verdict is
    never retried; a Reviewer's REQUEST-CHANGES sends the task back to the
    Implementer for one rework cycle (default) before a second rejection
    fails it; a set verifyCmd runs in the Implementer's git worktree when one
    exists; every hop/retry/gate outcome/claim/sweep event is traced
    (`docket trace`) on a per-task session; every invocation creates a
    queryable `docket runs` record; dispatch only ever targets the project's
    own pod -- there is no cross-pod dispatch path. See
    specs/functional/pod-dispatch.spec.md."""
    from docket.cli import _pod

    _pod.dispatch(project, sub, list(ctx.args))
