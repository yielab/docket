"""docket pod — provision and manage project pods.

A *pod* is the set of project-scoped agents for one project: a Lead plus one or more
workers (Implementer, Reviewer, Tester), each with its own workspace (no worker serves
two projects); member ids are ``<project>-<role>`` (``-N`` for duplicates). Composition
logic lives in `core/pod.py`; provisioning I/O (workspace + templates + meta + fleet
registration, with rollback on partial failure) lives in `core/pod_provisioning.py` so
it is reachable from `serve.py`'s `POST /pods` without that module importing
`docket.cli`. This module renders around that core module's typed results — `docket
add`'s pod path and `POST /pods` both call `core.pod_provisioning.provision_pod`, so
the two surfaces cannot drift apart.
"""

from __future__ import annotations

import contextlib
import getpass as _getpass
import hashlib as _hashlib
import json as _json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

import typer
from pydantic import ValidationError
from rich.markup import escape
from rich.table import Table

import docket.config as _cfg
from docket import ui
from docket.cli import _progress
from docket.cli._agents import _pick_agent
from docket.core import answers as _answers
from docket.core import archetypes as _arch
from docket.core import dispatch as _dispatch
from docket.core import fleet as _fleet
from docket.core import interruptions as _interruptions
from docket.core import models_policy as _mp
from docket.core import operator_contract as _oc
from docket.core import orchestrator as _orch
from docket.core import pipeline as _pipeline
from docket.core import pod
from docket.core import pod as _pod_core
from docket.core import pod_apply as _pod_apply
from docket.core import pod_provisioning as _pp
from docket.core import schedule as _sched
from docket.core.audit import audit_log

# Re-exports: this module's public surface (and several tests) reference
# these names on `docket.cli._pod` directly — see core/pod_provisioning.py
# for the real implementation and docstrings.
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


def _actor() -> str:
    """The OS user running this CLI invocation, falling back to '?' (mirrors
    `core.audit`'s own username lookup)."""
    try:
        return _getpass.getuser()
    except Exception:
        return "?"


def _role_purpose(role: str) -> str:
    """One-line purpose for a pod role (shown in `docket pod <project>`). Sourced from
    the role's archetype (`RoleArchetype.description`) rather than a second hardcoded
    map that would drift from `core/archetypes.py`'s own descriptions."""
    arch = _arch.load_registry().get(role)
    return arch.description if arch is not None else ""


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
    """Pod composition from `docket add` flags. Default = lean pod (lead + implementer);
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
    """Provision a fresh pod's members; returns the created member ids. Allocates
    pod-level runtime resources (port range + scratch dir) once, injected into each
    Implementer's workspace (skipped with no Implementer). A partial failure rolls
    back every member and any pod-level resources created — the same all-or-nothing
    contract `POST /pods` needs, since both surfaces share this one code path."""
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
    """Provision a fresh pod from a named blueprint; returns the created member ids.
    Thin rendering wrapper over `core.pod_provisioning.provision_pod` — the one path
    `docket add` and `POST /pods` both share. ``location`` is interpreted per the
    blueprint's `workspaceKind` (codebase path vs. shared working directory);
    ``roles`` overrides the blueprint's roster (a starting point, not a ceiling) while
    still applying its workspace kind/budget/name stamp. See
    specs/functional/pod-blueprints.spec.md. ``BlueprintError``/``VerifyCmdError``
    render as a clean CLI error, not a traceback; an already-existing pod or a
    mid-provisioning failure both warn and return ``[]`` rather than raising, since
    every caller already treats an empty return as the failure signal.
    """
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
    if action == "list":
        _pod_list(project)
    elif action == "add":
        _pod_add(project, extra)
    elif action == "remove":
        _pod_remove(project, extra)
    elif action == "set-verify":
        _pod_set_verify(project, extra)
    elif action == "delegate":
        _pod_delegate(project, extra)
    elif action == "answer":
        _pod_answer(project, extra)
    elif action == "explain":
        _pod_explain(project, extra)
    elif action == "pregrant":
        _pod_pregrant(project, extra)
    elif action == "queue":
        _pod_queue(project, extra)
    elif action == "dispatch":
        _pod_dispatch(project, extra)
    elif action == "config":
        _pod_config(project, extra)
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
            f"Unknown pod action {action!r}. Use: list | add | remove | set-verify | "
            "delegate | answer | explain | pregrant | queue | dispatch | config | sync | "
            "apply | export | corrections | evidence | worktrees."
        )
        raise typer.Exit(1)


def _pod_list(project: str) -> None:
    all_ids = [a.id for a in _fleet.list_agents()]
    members = pod.members_of(all_ids, project)
    if not members:
        ui.warn(f"No pod found for '{project}'. Create one with: docket init {project}")
        return
    has_resources = any(bool(_fleet.meta_get(mid, "portRangeStart", "")) for mid, _, _ in members)
    table = Table(title=f"Pod — {project}")
    table.add_column("MEMBER", style="bold")
    table.add_column("ROLE")
    table.add_column("MODEL")
    table.add_column("PURPOSE", style="dim")
    if has_resources:
        table.add_column("PORTS")
        table.add_column("SCRATCH")
    for mid, role, _idx in members:
        model = _fleet.meta_get(mid, "model", "?")
        if has_resources:
            port_start_s = _fleet.meta_get(mid, "portRangeStart", "")
            port_count_s = _fleet.meta_get(mid, "portRangeCount", "")
            scratch = _fleet.meta_get(mid, "scratchDir", "")
            if port_start_s and port_count_s:
                try:
                    port_end = int(port_start_s) + int(port_count_s) - 1
                    ports_str = f"{port_start_s}-{port_end}"
                except ValueError:
                    ports_str = port_start_s
            else:
                ports_str = "—"
            table.add_row(mid, role, model, _role_purpose(role), ports_str, scratch or "—")
        else:
            table.add_row(mid, role, model, _role_purpose(role))
    ui.console.print(table)


def _pod_add(project: str, extra: list[str]) -> None:
    if not pod_member_ids(project):
        ui.error(f"No pod for '{project}'. Create one first: docket init {project}")
        raise typer.Exit(1)
    role, count, verify_cmd = _parse_add_args(extra)
    if role is None:
        ui.error('Usage: docket pod <project> add <role> [--count N] [--verify "<cmd>"]')
        raise typer.Exit(1)
    if verify_cmd:
        try:
            verify_cmd = _validate_verify_cmd(verify_cmd)
        except VerifyCmdError as ex:
            ui.error(str(ex))
            raise typer.Exit(1) from ex

    # Inherit codebase/stack/description (and, for a `workdir`-kind pod, the
    # shared working directory + blueprint name) from the pod's Lead (or any
    # member) — a new member of a workdir pod must not fall back to being a
    # codebase-kind member.
    base_id = pod_member_ids(project)[0]
    codebase = _fleet.meta_get(base_id, "codebase", "")
    stack = _fleet.meta_get(base_id, "stack", "")
    description = _fleet.meta_get(base_id, "description", "")
    project_key = _fleet.meta_get(base_id, "projectKey", "default") or "default"
    work_dir = _fleet.meta_get(base_id, "workDir", "")
    blueprint_name = _fleet.meta_get(base_id, "blueprint", "")
    role_models, _, _ = _mp.load_registry()

    canon_role = pod.normalize_role(role, project)
    if canon_role == "implementer":
        port_start, port_count, scratch = _pp.allocate_pod_resources(project)
    else:
        port_start, port_count, scratch = 0, 0, ""
        if verify_cmd:
            ui.warn(
                f"--verify only applies to implementer members — ignoring for role '{canon_role}'."
            )
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
            codebase=codebase,
            stack=stack,
            description=description,
            project=project,
            project_key=project_key,
            port_range_start=port_start,
            port_range_count=port_count,
            scratch_dir=scratch,
            verify_cmd=verify_cmd,
            work_dir=work_dir,
            blueprint_name=blueprint_name,
        )
        if ok:
            ui.success(escape(f"Added {member.member_id} [{member.role}] {member.model}"))
            created.append(member.member_id)
            if verify_cmd:
                audit_log("pod.set-verify", f"member={member.member_id} cmd={verify_cmd!r}")
        else:
            ui.warn(f"{member.member_id}: registration failed — {msg}")
    if created:
        audit_log("pod.add", f"{project} role={canon_role} members={','.join(created)}")


def _pod_remove(project: str, extra: list[str]) -> None:
    if not extra:
        ui.error("Usage: docket pod <project> remove <member-id>")
        raise typer.Exit(1)
    member_id = extra[0]
    if pod.parse_member_id(member_id, project) is None:
        ui.error(f"'{member_id}' is not a member of the '{project}' pod.")
        raise typer.Exit(1)
    # Read role before teardown removes the workspace.
    role = _fleet.meta_get(member_id, "role", "")
    ok, msg = teardown_member(member_id)
    if ok:
        ui.success(f"Removed {member_id}")
        if msg:
            ui.dim(f"  {msg}")
    else:
        ui.warn(f"{member_id}: fleet deregistration reported: {msg} (workspace cleaned)")
    audit_log("pod.remove", f"{project} member={member_id} role={role}")
    # Free runtime resources if this was the last implementer in the pod.
    if role == "implementer":
        remaining = pod_member_ids(project)
        remaining_roles = {_fleet.meta_get(mid, "role", "") for mid in remaining}
        if "implementer" not in remaining_roles:
            free_pod_resources(project)


def _regenerate_member_tools(member_id: str, project: str) -> None:
    """Rewrite TOOLS.md for an existing Implementer after a meta change (e.g.
    set-verify). No-op for non-implementers, and for members with no allocated
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


def _pod_set_verify(project: str, extra: list[str]) -> None:
    """Set the verify command on an existing Implementer and rewrite TOOLS.md. The
    command is validated (no NUL/newline, length-capped — ``_validate_verify_cmd``)
    and audit-logged; docket still runs it with ``shell=True`` once stored."""
    if len(extra) < 2:
        ui.error('Usage: docket pod <project> set-verify <member-id> "<cmd>"')
        raise typer.Exit(1)
    member_id, *cmd_parts = extra
    verify_cmd = " ".join(cmd_parts)
    if pod.parse_member_id(member_id, project) is None:
        ui.error(f"'{member_id}' is not a member of the '{project}' pod.")
        raise typer.Exit(1)
    role = _fleet.meta_get(member_id, "role", "")
    if role != "implementer":
        ui.error(
            f"'{member_id}' is a {role or 'unknown role'} — verifyCmd only applies to implementers."
        )
        raise typer.Exit(1)
    try:
        verify_cmd = _validate_verify_cmd(verify_cmd)
    except VerifyCmdError as ex:
        ui.error(str(ex))
        raise typer.Exit(1) from ex
    _fleet.meta_set(member_id, "verifyCmd", verify_cmd)
    _regenerate_member_tools(member_id, project)
    audit_log("pod.set-verify", f"member={member_id} cmd={verify_cmd!r}")
    ui.success(f"Set verify command for {member_id}: {verify_cmd!r}")


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


@dataclass(frozen=True, slots=True)
class DispatchArgs:
    """Parsed ``docket pod <p> dispatch`` flags."""

    resume: bool
    timeout: int | None
    progress: bool
    no_prompt: bool


def _parse_dispatch_args(extra: list[str]) -> DispatchArgs:
    """Parse ``[--resume] [--timeout SECONDS] [--progress] [--no-prompt]``.
    ``--timeout`` overrides the agent-turn/verifyCmd timeout over the pod's
    persisted Lead-meta values. Raises ValueError on a bad ``--timeout``."""
    resume = "--resume" in extra
    progress = "--progress" in extra
    no_prompt = "--no-prompt" in extra
    timeout: int | None = None
    if "--timeout" in extra:
        i = extra.index("--timeout")
        raw = extra[i + 1] if i + 1 < len(extra) else ""
        timeout = int(raw)
        if timeout <= 0:
            raise ValueError(raw)
    return DispatchArgs(resume, timeout, progress, no_prompt)


def _flush_notify_after_dispatch() -> None:
    """One `core.notify.flush` call over every catalog channel, after a CLI dispatch's own
    summary has already printed (ADR 0016 SS7) -- the foreground half of delivery; the
    background half is `serve.py`'s sweep. Prints nothing unless a delivery failed, or the
    flush found events and nothing delivers beyond the console."""
    import datetime as _dt

    from docket.core import channel as _channel
    from docket.core import notify as _notify
    from docket.edges.adapters import channels as _channels

    now = _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    report = _notify.flush(
        list(_channel.load_catalog().entries.values()), _channels.sink_for, now=now
    )
    if report.failed:
        ui.warn(f"  notify: {report.failed} delivery failure(s) — see channels-health.json")
    if report.events:
        unreached = _channel.unreached_warning(_channel.load_catalog().delivering())
        if unreached:
            ui.warn(f"  {unreached}")


def _pod_dispatch(
    project: str,
    extra: list[str],
    *,
    spec: _pipeline.PipelineSpec | None = None,
    variables: dict[str, str] | None = None,
) -> None:
    """Drive the pod's pending tasks through the pipeline (one real turn per hop).
    ``--resume``/``--timeout`` crash-recovery and override semantics: see
    specs/functional/pod-dispatch.spec.md. Recorded in the run registry (source
    ``"cli"``), so a failure is visible afterwards via ``docket runs show``. *spec*,
    when given (by ``docket pipeline run``), is forwarded unchanged; ``None`` resolves
    through ``effective_pipeline`` — the pod's blueprint pipeline, or the built-in
    default — the one shared resolver both CLI surfaces drive, so the prologue names
    the same roles the executor actually runs. *variables* (``docket pipeline run
    --var``) is forwarded to ``dispatch_pod`` unchanged; it validates/resolves them and
    refuses up front if any step's own ``instructions`` is left with an unresolved
    ``${var}`` reference (pipeline-format.spec.md)."""
    from docket.core import runs as _runs

    try:
        dispatch_args = _parse_dispatch_args(extra)
    except ValueError:
        ui.error("--timeout requires a positive integer number of seconds.")
        raise typer.Exit(1) from None
    resume = dispatch_args.resume
    timeout_override = dispatch_args.timeout
    try:
        _dispatch.pod_pipeline(project)  # validates the pod exists and has a Lead
    except _dispatch.DispatchError as ex:
        ui.error(str(ex))
        raise typer.Exit(1) from ex
    tasks = _dispatch.read_tasks(project)
    pending = [t for t in tasks if t.get("status") == "pending"]
    resumable = (
        [
            t
            for t in tasks
            if t.get("status") == "failed"
            and t.get("failureKind") in _dispatch.RESUMABLE_FAILURE_KINDS
        ]
        if resume
        else []
    )
    # A crashed dispatcher leaves a task `running`, not `failed` -- it only becomes
    # resumable once `dispatch_pod`'s own stale-claim sweep judges its claim too old
    # (pod-dispatch.spec.md, "Claiming"/"Per-hop incremental persistence and crash
    # recovery"). Re-checking that staleness here would duplicate the sweep's own
    # CLAIM_STALE_TIMEOUT math; instead, under --resume, a `running` task is enough
    # to let this call proceed into dispatch_pod at all, so its sweep can settle a
    # genuinely stale one in the same call -- no decoy pending task, no timeout
    # override needed just to unblock recovery.
    running = [t for t in tasks if t.get("status") == "running"] if resume else []
    if not pending and not resumable and not running:
        ui.warn(f"No pending tasks for pod '{project}'. Queue one: docket pod {project} delegate")
        return
    count_label = f"{len(pending)} pending"
    if resume:
        count_label += f", {len(resumable)} resumable"
        if running:
            count_label += f", {len(running)} running (reclaimed only if the claim is stale)"
    try:
        if spec is not None:
            ui.info(f"Dispatching {count_label} task(s) through pipeline '{spec.name}'")
        else:
            roles = " → ".join(
                step.role or step.agent or step.id
                for step in _dispatch.effective_pipeline(project, None).steps
            )
            ui.info(f"Dispatching {count_label} task(s) through: {roles}")
        cap = _dispatch.pod_budget(project)
    except _dispatch.DispatchError as ex:
        # An invalid stored setting (see core.pod.PodSettings) refuses here,
        # before any task is claimed, rather than defaulting it away.
        ui.error(str(ex))
        raise typer.Exit(1) from ex
    if cap:
        ui.dim(f"  Pod budget cap: ${cap:.2f} (spent ${_dispatch.pod_recorded_cost(project):.2f})")

    record = _runs.create_run("cli", project)

    def _fn() -> list[Any]:
        # An unset pod `approvalMode` resolves to "wait" on a real TTY (an
        # operator watching this run can answer in place -- see
        # cli/_progress.py) and to "park" otherwise (ADR 0016 SS2): a
        # non-interactive foreground dispatch has nobody to answer an in-turn
        # ask, so it must park rather than block for TOOL_APPROVAL_TIMEOUT.
        approval_default: Literal["wait", "park"] = "wait" if sys.stdin.isatty() else "park"
        return _dispatch.dispatch_pod(
            project,
            resume=resume,
            turn_timeout=timeout_override,
            verify_timeout=timeout_override,
            spec=spec,
            variables=variables,
            approval_default=approval_default,
        )

    # No TTY and no --progress: the exact call this function has always made,
    # so goldens stay byte-identical (specs/api/cli-interface.spec.md,
    # "Foreground dispatch progress and in-place approval").
    if _progress.should_render(progress_flag=dispatch_args.progress):
        results = _progress.dispatch_with_progress(
            record["id"],
            _fn,
            prompt=_progress.should_prompt(no_prompt_flag=dispatch_args.no_prompt, render=True),
        )
    else:
        results = _runs.execute(record["id"], _fn)
    if results is None:
        rec = _runs.get_run(record["id"])
        error = str(rec.get("error", "")) if rec else ""
        ui.error(f"Dispatch failed: {error}")
        ui.dim(f"  Details: docket runs show {record['id']}")
        raise typer.Exit(1)
    for res in results:
        # `core/dispatch.py` never prints (a layering violation) -- it returns
        # this as a typed `HopResult.verification_skipped` flag instead; this
        # is the one place that renders it, before the task's own summary line.
        for hop in res.hops:
            if hop.verification_skipped:
                ui.dim(
                    escape(
                        f"[dispatch] verification skipped — verifyCmd not set for {hop.member_id}"
                    )
                )
        # Task ids and model-written reasons are data, never Rich markup.
        if res.status == "done":
            ui.success(
                escape(f"  [{res.task_id}] done — {len(res.hops)} hop(s), ${res.cost_usd:.4f}")
            )
        elif res.status == "blocked":
            ui.warn(escape(f"  [{res.task_id}] blocked — {res.reason}"))
        elif res.status in ("waiting_approval", "waiting_input"):
            # Waiting on a human decision is an expected pause, not a
            # failure — same warn-not-error treatment as a budget block.
            ui.warn(escape(f"  [{res.task_id}] {res.status} — {res.reason}"))
        else:
            ui.error(escape(f"  [{res.task_id}] {res.status} — {res.reason}"))
    _flush_notify_after_dispatch()
    final = _runs.get_run(record["id"])
    if final is not None and final.get("state") == "failed":
        ui.dim(f"  Details: docket runs show {record['id']}")
        raise typer.Exit(1)


def _pod_config(project: str, extra: list[str]) -> None:
    """``docket pod <project> config [get|set <key> <value>|unset <key>] [--json]``.
    Reads/writes the Lead's typed dispatch settings (``core.pod.PodSettings``)
    through the existing meta writer; every write is audited as ``pod.config``."""
    json_out = "--json" in extra
    rest = [a for a in extra if a != "--json"]
    action = rest[0] if rest else "get"

    try:
        _dispatch.pod_pipeline(project)  # validates the pod exists and has a Lead
    except _dispatch.DispatchError as ex:
        ui.error(str(ex))
        raise typer.Exit(1) from ex
    lead_id = pod.member_id(project, "lead")

    if action == "get":
        if len(rest) > 1:
            ui.error("Usage: docket pod <project> config [get] [--json]")
            raise typer.Exit(1)
        try:
            settings = pod.PodSettings.load_for(project)
        except pod.PodSettingsError as ex:
            ui.error(str(ex))
            raise typer.Exit(1) from ex
        rows = [(k, *settings.value_and_source(k, project)) for k in pod.PodSettings.KEYS]
        if json_out:
            print(_json.dumps({k: {"value": v, "source": s} for k, v, s in rows}, indent=2))
        else:
            table = Table(title=f"Pod config — {project}")
            table.add_column("KEY", style="bold")
            table.add_column("VALUE")
            table.add_column("SOURCE", style="dim")
            for k, v, s in rows:
                table.add_row(k, str(v), s)
            ui.console.print(table)
        return

    if action == "set":
        if len(rest) != 3:
            ui.error("Usage: docket pod <project> config set <key> <value>")
            raise typer.Exit(1)
        _, key, value = rest
        if key == "pipeline":
            _pod_config_set_pipeline(project, lead_id, value)
            return
        if key == "schedule":
            _pod_config_set_schedule(project, lead_id, value)
            return
        if key in pod.PodSettings.RECORDED_KEYS:
            ui.error(f"{key} is written by apply, not by config set")
            raise typer.Exit(1)
        try:
            coerced = pod.PodSettings.coerce(key, value, project=project)
        except pod.PodSettingsError as ex:
            ui.error(str(ex))
            raise typer.Exit(1) from ex
        _fleet.meta_set(lead_id, key, coerced)
        audit_log("pod.config", f"project={project} action=set key={key} value={coerced!r}")
        ui.success(f"Set {key}={coerced} for pod '{project}'.")
        return

    if action == "unset":
        if len(rest) != 2:
            ui.error("Usage: docket pod <project> config unset <key>")
            raise typer.Exit(1)
        _, key = rest
        if key not in pod.PodSettings.KEYS:
            ui.error(f"unknown pod setting {key!r}; valid keys: {', '.join(pod.PodSettings.KEYS)}")
            raise typer.Exit(1)
        # None round-trips through AgentMeta's typed fields and reads back
        # exactly like an absent key -- the writer's only way to clear one.
        _fleet.meta_set(lead_id, key, None)
        if key == "pipeline":
            # Best-effort: the meta hash is already cleared (the part that
            # matters -- effective_pipeline falls back the moment it reads
            # no pipeline set), so a failed cleanup here never blocks unset.
            with contextlib.suppress(OSError):
                pod.bound_pipeline_path(project).unlink()
        if key == "schedule":
            # Not best-effort: docket-schedules.json, not the meta key just cleared
            # above, is what the serve sweep actually reads (see
            # `_pod_config_set_schedule`), so this call must succeed for "unset"
            # to really stop the schedule from firing.
            _sched.unset_schedule(_cfg.SCHEDULE_FILE, project)
        audit_log("pod.config", f"project={project} action=unset key={key}")
        ui.success(f"Unset {key} for pod '{project}' — falls back to its default.")
        return

    ui.error(f"Unknown pod config action {action!r}. Use: get | set <key> <value> | unset <key>.")
    raise typer.Exit(1)


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
    """``docket pod <project> config set pipeline <file>``: validate *path_str* and
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
    """``docket pod <project> config set schedule <spec>``: validate *spec*, persist it as
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


def _parse_add_args(extra: list[str]) -> tuple[str | None, int, str]:
    """Parse ``<role> [--count N | -n N] [--verify "<cmd>"]``.
    ``--verify`` (Implementer only; warned-and-ignored otherwise) sets the mechanical
    verification gate `dispatch.py` runs after the new member's hop."""
    role: str | None = None
    count = 1
    verify_cmd = ""
    i = 0
    while i < len(extra):
        tok = extra[i]
        if tok in ("--count", "-n") and i + 1 < len(extra):
            with_val = extra[i + 1]
            count = int(with_val) if with_val.isdigit() else 1
            i += 2
            continue
        if tok == "--verify" and i + 1 < len(extra):
            verify_cmd = extra[i + 1]
            i += 2
            continue
        if tok.startswith("--verify="):
            verify_cmd = tok[len("--verify=") :]
            i += 1
            continue
        if role is None:
            role = tok
        i += 1
    return role, count, verify_cmd


def cmd_add(ctx: typer.Context) -> None:
    """Add role agents to an existing project pod. Never creates a project.

    Pod inferred from the current directory, or given explicitly with
    `--project <pod>` when running outside the project's configured
    `codebase`/`workDir`. Docket chooses the most-specific registered pod
    containing the cwd and fails clearly when there is no match or the result
    is ambiguous.

    Flags (parsed from the extra CLI args, not fixed Typer options):
      --project <pod>     explicit pod, instead of directory inference
      --count N           add N indexed copies of the role
      --verify "<cmd>"    set the new Implementer's mechanical verify gate"""
    from docket.cli._agents import run_add

    raise typer.Exit(run_add(list(ctx.args)))


def cmd_info(
    agent_id: str | None = typer.Argument(None),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Detailed status of one agent.

    Shows identity, codebase/stack, model and its source, session/project
    keys, creation time, workspace path, and Telegram binding for one agent --
    pulled from `.docket-meta.json`. With no agent id given, shows a numbered
    picker."""
    from docket.cli._agents import run_info

    raise typer.Exit(run_info(agent_id, json_out))


def cmd_delete(agent_id: str | None = typer.Argument(None)) -> None:
    """Remove a project agent or a whole pod, and optionally its workspace.

    Given a pod id, lists every member and (in an interactive terminal)
    requires typing the exact pod id to confirm, then removes every member's
    registration, binding, conversation-registry entry, workspace/worktree,
    pod runtime directory, durable session history, and traces. The global
    audit record is preserved. Given a legacy flat agent id, separately asks
    whether to also remove its workspace.

    Cannot be undone -- back up first if unsure. A deleted
    member's git worktree is removed, but its dedicated branch remains in the
    source repository so committed code is not silently destroyed; remove
    that branch separately after reviewing it."""
    from docket.cli._agents import run_delete

    raise typer.Exit(run_delete(agent_id))


def _delete_pod(project: str, members: list[str]) -> int:
    """Tear down every member of a pod. Kept here, not ``cli/_agents.py``, because
    ``tests/integration/test_pod_provisioning.py`` calls it directly as
    ``docket.cli._delete_pod`` -- moving it would be a rename, not an extraction."""
    from docket.cli import _pod

    ui.header(f"Delete pod: {project}  ({len(members)} members)")
    ui.console.print()
    for mid in members:
        role = _fleet.meta_get(mid, "role", "?")
        ui.console.print(f"  - {mid}  ({role})")
    ui.console.print()
    ui.warn(
        "This removes every member's registration, binding, workspace, runtime, session history, "
        "and traces. The audit record is preserved."
    )
    ui.console.print()

    if sys.stdin.isatty():
        confirm = input(f"Type the pod id to confirm deletion [{project}]: ").strip()
        if confirm != project:
            ui.warn("Aborted.")
            return 0

    from docket.core import conversations as _conv

    for mid in members:
        if _fleet.get_binding(mid):
            _fleet.remove_binding(mid)
        _conv.remove_agent_durable(mid)
        ok, msg = _pod.teardown_member(mid)
        if ok:
            ui.success(f"Removed {mid}")
            if msg:
                ui.dim(f"  {msg}")
        else:
            ui.warn(f"{mid}: fleet deregistration reported: {msg} (workspace cleaned)")
    # Free pod runtime resources (port range + scratch dir) after all members gone.
    _pod.free_pod_resources(project)
    _pod.purge_pod_history(project, members)

    audit_log("agent.delete", f"{project} pod ({len(members)} members)")
    ui.success(f"Pod '{project}' deleted.")
    return 0


def cmd_maintain(
    ctx: typer.Context,
    agent_id: str | None = typer.Argument(None),
    mode: str | None = typer.Argument(None),
) -> None:
    """Maintain an agent workspace (check/clean/reset/rebuild/sessions/distill).

    Subcommands:
      check (default)  health check and auto-fix -- permissions (700/600),
                        missing workspace files, session-key sync between
                        `.docket-meta.json` and SOUL.md, memory directory,
                        and a per-turn context-footprint estimate (warns if
                        SOUL/AGENTS/TOOLS/HEARTBEAT/MEMORY together exceed
                        the configured token budget)
      clean             clear memory logs only (`memory/*.md`) -- distills
                        first by default (see below)
      reset             clear memory + MEMORY.md + HEARTBEAT.md -- distills
                        first by default
      rebuild           deep rebuild -- regenerate SOUL.md, AGENTS.md,
                        TOOLS.md from `.docket-meta.json`. Refuses a pod
                        member outright (its files are pod-provisioning's,
                        not this command's); never touches memory/
      sessions          report per-session message counts, on-disk size,
                        and last-active time for this agent -- sizes only,
                        no trimming or archiving
      distill           summarize `memory/*.md` into MEMORY.md via one
                        driver-backed turn, then archive the originals under
                        `memory/<archive-dir>/`

    `--no-distill-first` (clean/reset only) skips the automatic pre-delete
    distillation and deletes/clears memory undistilled.

    Memory is never bare-deleted: before clean deletes `memory/*.md`, or reset
    clears memory + HEARTBEAT.md, docket runs one driver-backed turn that
    summarizes pending logs into MEMORY.md and archives the originals -- the
    same work `distill` does standalone. A failed distillation aborts the
    delete outright; nothing is touched. `failure_kind` (`timeout`,
    `daemon_error`, `invalid_output`) tells you whether to just retry or
    whether the model's output needs a closer look (`daemon_error` means the
    turn didn't complete cleanly). When a reset runs a real distillation, MEMORY.md is
    left freshly distilled rather than immediately cleared again in the same
    breath.

    Preserves identity (`.docket-meta.json`, fleet registration). clean/
    reset/rebuild prompt for confirmation and require a TTY -- a
    non-interactive call is cancelled, not silently applied."""
    from docket.cli._agents import run_maintain

    raise typer.Exit(run_maintain(agent_id, mode, list(ctx.args)))


def cmd_profile(
    agent_id: str | None = typer.Argument(None),
    model: str | None = typer.Argument(None),
    budget: str | None = typer.Option(None, "--budget", help="USD cap (0 = remove)"),
    resume: bool = typer.Option(
        False, "--resume", help="Clear an auto-pause (e.g. a reached budget cap)"
    ),
) -> None:
    """Pin or unpin an agent's model; set a budget cap; resume from auto-pause.

    Every agent follows its role's policy model by default
    (`modelSource: policy`). Pinning (`modelSource: pinned`) detaches it --
    policy and preset changes will no longer touch it.

    With no model argument, shows the current model, role, source, and
    budget. A `provider/model` argument pins it; `default` re-attaches it to
    the role policy. `--budget <USD>` sets a per-agent spend cap (0 = none).
    `--resume` clears an auto-pause (e.g. a reached budget cap) -- when the
    target is a pod's Lead it also un-blocks that pod's blocked tasks so
    dispatch can claim them again, and writes a `profile.resume` audit entry.
    A model argument must be a full `provider/model` id; `docket models`
    shows and sets the role policy."""
    if agent_id is None:
        if not sys.stdin.isatty():
            ui.error("An agent id is required.")
            raise typer.Exit(1)
        agent_id = _pick_agent("Set model for")

    aid: str = agent_id
    ws = _cfg.workspace_dir(aid)
    if not ws.is_dir():
        ui.error(f"Agent '{aid}' not found.")
        raise typer.Exit(1)

    if resume:
        # The only writer that CLEARS an auto-pause (`core/dispatch.py`'s
        # `_pause_lead_for_budget` is the only one that SETS it). Mirrors the
        # `--budget` branch below: if the resumed agent is a pod's Lead, also
        # unblock its budget-blocked tasks — a pause with no way to un-stick
        # the tasks that queued up behind it would be a no-op resume.
        _fleet.meta_set(aid, "paused", False)
        _fleet.meta_set(aid, "pausedReason", "")
        audit_log("profile.resume", f"agent={aid}")
        pod_project = _pod_core.pod_of(aid)
        if pod_project is not None and _pod_core.member_id(pod_project, "lead") == aid:
            unblocked = _dispatch.unblock_pod(pod_project)
            if unblocked:
                ui.info(f"  Unblocked {unblocked} budget-blocked task(s) in pod '{pod_project}'.")
        ui.success(f"Resumed '{aid}' — auto-pause cleared.")
        if budget is None and model is None:
            return

    if budget is not None:
        try:
            bval = float(budget)
            if bval < 0:
                raise ValueError
        except ValueError:
            ui.error(f"Invalid budget '{budget}'. Must be a non-negative number (e.g. 5 or 10.50).")
            raise typer.Exit(1) from None
        _fleet.meta_set(aid, "budgetUsd", bval)
        audit_log("profile.budget", f"{aid}=${budget}")
        # A pod-wide budget change is one of the two sanctioned ways a
        # budget-`blocked` task re-enters `pending` (the other is an explicit
        # `docket pod <p> queue --retry <task-id>`) — a blocked task never
        # retries on its own. Only the Lead owns the pod's cap (dispatch.pod_budget
        # reads the Lead's budgetUsd), so only changing the Lead's budget unblocks.
        pod_project = _pod_core.pod_of(aid)
        if pod_project is not None and _pod_core.member_id(pod_project, "lead") == aid:
            unblocked = _dispatch.unblock_pod(pod_project)
            if unblocked:
                ui.info(f"  Unblocked {unblocked} budget-blocked task(s) in pod '{pod_project}'.")
        if budget != "0":
            _fleet.meta_set(aid, "paused", False)
            _fleet.meta_set(aid, "pausedReason", "")
            ui.success(f"Budget cap set to ${budget} for '{aid}'.")
        else:
            ui.success(f"Budget cap removed for '{aid}'.")
        if model is None:
            return  # budget-only change, nothing more to do

    name = _fleet.meta_get(aid, "name", aid)
    current = _fleet.meta_get(aid, "model", _cfg.DEFAULT_MODEL)
    role = _mp.agent_role(aid)
    src = _mp.agent_model_source(aid)
    bud = _fleet.meta_get(aid, "budgetUsd", "")

    if model is None:
        role_models, _, _ = _mp.load_registry()
        policy_model = _mp.resolve_role_model(
            role, role_models, project=_pod_core.pod_of(aid) or ""
        )
        ui.header(f"Model: {name} ({aid})")
        ui.console.print()
        ui.console.print(f"  [bold]{'Current model:':<18}[/bold] {current}")
        ui.console.print(f"  [bold]{'Role:':<18}[/bold] {role}  [dim]({_mp.role_why(role)})[/dim]")
        if src == "policy":
            ui.console.print(
                f"  [bold]{'Source:':<18}[/bold] policy — follows the role's model (docket models)"
            )
        else:
            ui.console.print(
                f"  [bold]{'Source:':<18}[/bold] pinned — unaffected by policy changes"
            )
        if bud and bud != "0":
            ui.console.print(f"  [bold]{'Budget cap:':<18}[/bold] ${float(bud):.2f}")
        else:
            ui.console.print(f"  [bold]{'Budget cap:':<18}[/bold] none")
        ui.console.print()
        ui.console.print(f"  [bold]Policy for role '{role}':[/bold] {policy_model}")
        ui.console.print()
        ui.console.print(f"  docket profile {aid} <provider/model>   # pin this agent")
        ui.console.print(f"  docket profile {aid} default            # follow role policy")
        ui.console.print(f"  docket profile {aid} --budget <USD>     # spending cap (0=none)")
        ui.console.print("  docket models                         # view/change role policy")
        ui.console.print()
        return

    if model == "default":
        role_models, _, _ = _mp.load_registry()
        new_model = _mp.resolve_role_model(role, role_models, project=_pod_core.pod_of(aid) or "")
        new_src = "policy"
    else:
        try:
            new_model, warnings = _mp.validate_model(model)
        except ValueError as exc:
            ui.error(str(exc))
            raise typer.Exit(1) from None
        for w in warnings:
            ui.warn(w)
        new_src = "pinned"

    if new_model == current and new_src == src:
        ui.warn(f"Already using {new_model} ({new_src}). No change.")
        return

    _fleet.set_model_both(aid, new_model)
    _fleet.meta_set(aid, "modelSource", new_src)
    audit_log("profile.model", f"{aid}={new_model} ({new_src})")

    if new_src == "policy":
        ui.success(f"Model: {current} → {new_model} (follows role policy '{role}')")
    else:
        ui.success(f"Model pinned: {current} → {new_model}")


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
