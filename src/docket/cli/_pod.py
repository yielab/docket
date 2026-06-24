"""docket pod — provision and manage project pods (Phase 10 / AA-3).

A *pod* is the set of project-scoped agents for one project: a Lead plus one or
more workers (Implementer, Reviewer, Tester), each a distinct registered agent
with its **own** workspace (the isolation guarantee — no worker serves two
projects). Pod members are ordinary project agents whose id is ``<project>-<role>``
(``-N`` for duplicates), so `list`/`info`/`cost`/`doctor` see them for free.

Composition logic lives in `core/pod.py`; this module does the I/O: workspace +
templates + meta + daemon registration via the ACL.
"""

from __future__ import annotations

import contextlib
import json
import shutil
from datetime import UTC, datetime

import typer
from rich.table import Table

import docket.config as _cfg
from docket import ui
from docket.core import dispatch as _dispatch
from docket.core import models_policy as _mp
from docket.core import pod
from docket.edges.adapters import openclaw as _oc
from docket.edges.adapters import system as _sys

# Bump when the pod-member templates change (doctor flags older members).
POD_TEMPLATE_VERSION = 1

# One-line purpose per pod role (shown in `docket pod <project>`).
_ROLE_PURPOSE: dict[str, str] = {
    "lead": "orchestrates the pod; never edits code",
    "implementer": "writes code in the project workspace",
    "reviewer": "read-only veto on diffs",
    "tester": "behaviour-only PASS/FAIL",
}


# ── templates (folds AA-4 worker + AA-5 lead essentials) ─────────────────────────


def _member_soul(
    member: pod.PodMember, project: str, codebase: str, stack: str, description: str
) -> str:
    head = (
        f"# SOUL.md — {project} · {member.role}\n\n"
        "## Identity\n"
        f"You are the **{member.role}** of the **{project}** pod (agent id "
        f"`{member.member_id}`).\n\n"
        f"**Session Key:** `{member.session_key}`\n\n"
        "You belong to one project only. Respect the pod session-key boundary — "
        "no cross-project access.\n\n"
        f"## Project\n{description or project}\n\n"
        f"## Codebase\n{codebase or '(task pod — no fixed codebase)'}\n\n"
        f"## Stack\n{stack}\n\n"
    )
    if member.role == "lead":
        body = (
            "## Role — Lead / Orchestrator\n"
            "- You own the pod's context, memory, and human communication.\n"
            "- Decompose work and dispatch it to the pod's workers "
            "(implementer → reviewer → tester).\n"
            "- **You NEVER edit code, run git, or execute the build.** If you are "
            "about to, STOP and delegate to the implementer.\n"
            "- Surface architectural decisions and risky actions to the human (HITL).\n"
        )
    elif member.role == "implementer":
        body = (
            "## Role — Implementer\n"
            f"- You run **inside** this project's workspace and know {codebase or 'it'} "
            "deeply. Read files before changing them.\n"
            "- You implement the tasks the Lead assigns: read/write/edit the codebase.\n"
            "- Signal completion with `<promise>DONE</promise>`.\n"
            "- Never push to main/master without HITL approval; never delete files "
            "without explicit instruction.\n"
        )
    elif member.role == "reviewer":
        body = (
            "## Role — Reviewer (veto power)\n"
            "- You review diffs for correctness, security, and requirement fit.\n"
            "- **Read-only**: no write/edit/exec. Bad code does not proceed.\n"
            "- Output a clear APPROVE or REQUEST-CHANGES with reasons.\n"
        )
    else:  # tester
        body = (
            "## Role — Tester\n"
            "- You run the test suite and reproduction steps and report a binary "
            "**PASS/FAIL** with evidence.\n"
            "- Observe behaviour only — do not read or critique the implementation.\n"
        )
    return head + body


def _member_agents(member: pod.PodMember, project: str) -> str:
    return (
        f"# AGENTS.md — {project} · {member.role}\n\n"
        "## Every Session\n"
        "1. Read SOUL.md\n"
        "2. Read HEARTBEAT.md — any pending tasks?\n"
        "3. Read memory/YYYY-MM-DD.md (today + yesterday)\n\n"
        "## Pod\n"
        f"You are part of the `{project}` pod. Coordinate only within this pod; "
        "the Lead routes work between members.\n"
    )


def _write_member_workspace(
    member: pod.PodMember,
    codebase: str,
    stack: str,
    description: str,
    project: str,
    project_key: str,
) -> None:
    ws = _cfg.PROJECTS_DIR / member.member_id
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "memory").mkdir(exist_ok=True)
    (ws / "SOUL.md").write_text(
        _member_soul(member, project, codebase, stack, description), encoding="utf-8"
    )
    (ws / "AGENTS.md").write_text(_member_agents(member, project), encoding="utf-8")
    (ws / "HEARTBEAT.md").write_text(
        f"# HEARTBEAT — {member.member_id}\n\n_No active tasks._\n", encoding="utf-8"
    )
    with contextlib.suppress(OSError):
        ws.chmod(0o700)

    meta = {
        "schemaVersion": 1,
        "kind": "project",
        "scope": "project",
        "role": member.role,
        "pod": project,
        "name": f"{project} {member.role}",
        "codebase": codebase,
        "stack": stack,
        "model": member.model,
        "modelSource": "policy",
        "description": description,
        "created": datetime.now(UTC).isoformat(),
        "sessionKey": member.session_key,
        "projectKey": project_key,
        "templateVersion": str(POD_TEMPLATE_VERSION),
    }
    meta_file = ws / _cfg.META_FILE
    meta_file.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    with contextlib.suppress(OSError):
        meta_file.chmod(0o600)


# ── provisioning / teardown (no restart — caller batches) ────────────────────────


def provision_member(
    member: pod.PodMember,
    *,
    codebase: str,
    stack: str,
    description: str,
    project: str,
    project_key: str,
) -> tuple[bool, str]:
    """Create one pod member's workspace + meta and register it with the daemon.

    Does NOT restart the gateway — the caller batches one restart per command.
    """
    _write_member_workspace(member, codebase, stack, description, project, project_key)
    ws_path = str(_cfg.PROJECTS_DIR / member.member_id)

    if shutil.which("openclaw"):
        ok, msg = _oc.register_agent_cli(member.member_id, ws_path, member.model)
        if not ok:
            return (False, msg)
    else:
        _oc.add_agent(member.member_id, member.model, member.session_key, project_key)

    _oc.sync_session_key(member.member_id, member.session_key, project_key)
    return (True, "")


def teardown_member(member_id: str) -> tuple[bool, str]:
    """Remove one pod member: daemon registration + workspace + agents.list entry.

    Does NOT restart the gateway — the caller batches one restart per command.
    """
    ok, msg = (True, "")
    if shutil.which("openclaw"):
        ok, msg = _oc.unregister_agent_cli(member_id)
    # Belt-and-braces: ensure it's gone from agents.list and the docket workspace.
    with contextlib.suppress(Exception):
        _oc.remove_agent(member_id)
    ws = _cfg.PROJECTS_DIR / member_id
    if ws.is_dir():
        shutil.rmtree(ws, ignore_errors=True)
    return (ok, msg)


def pod_member_ids(project: str) -> list[str]:
    """Registered agent ids that belong to ``project``'s pod (Lead first)."""
    all_ids = [a.id for a in _oc.list_agents()]
    return [mid for mid, _role, _idx in pod.members_of(all_ids, project)]


def parse_pod_roles(args: list[str]) -> tuple[str, ...]:
    """Pod composition from `docket add` flags.

    Default = lean pod (lead + implementer). ``--pod full`` = the four-role pod.
    ``--with reviewer,tester`` = lean pod plus the named roles. Unknown role names
    are ignored (the lean default still applies).
    """
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


def build_pod(
    project: str,
    roles: tuple[str, ...],
    *,
    codebase: str = "",
    stack: str = "",
    description: str = "",
    project_key: str = "default",
) -> list[str]:
    """Provision a fresh pod's members. Returns the created member ids.

    One gateway restart at the end. Used by `docket add` and `docket pod add full`.
    """
    role_models, _, _ = _mp.load_registry()
    members = pod.plan_pod(project, roles, project_key=project_key, role_models=role_models)
    created: list[str] = []
    for m in members:
        ok, msg = provision_member(
            m,
            codebase=codebase,
            stack=stack,
            description=description,
            project=project,
            project_key=project_key,
        )
        if ok:
            ui.success(f"  {m.member_id}  [{m.role}]  {m.model}")
            created.append(m.member_id)
        else:
            ui.warn(f"  {m.member_id}: registration failed — {msg}")
    _sys.restart_gateway()
    return created


# ── command dispatch (docket pod <project> [add|remove] …) ───────────────────────


def dispatch(project: str, sub: str | None, extra: list[str]) -> None:
    """Entry point for the `docket pod` command (wired in cli/__init__.py)."""
    action = sub or "list"
    if action == "list":
        _pod_list(project)
    elif action == "add":
        _pod_add(project, extra)
    elif action == "remove":
        _pod_remove(project, extra)
    elif action == "delegate":
        _pod_delegate(project, extra)
    elif action == "queue":
        _pod_queue(project)
    elif action == "dispatch":
        _pod_dispatch(project)
    else:
        ui.error(
            f"Unknown pod action {action!r}. Use: list | add | remove | delegate | queue | dispatch."
        )
        raise typer.Exit(1)


def _pod_list(project: str) -> None:
    all_ids = [a.id for a in _oc.list_agents()]
    members = pod.members_of(all_ids, project)
    if not members:
        ui.warn(f"No pod found for '{project}'. Create one with: docket add {project}")
        return
    table = Table(title=f"Pod — {project}")
    table.add_column("MEMBER", style="bold")
    table.add_column("ROLE")
    table.add_column("MODEL")
    table.add_column("PURPOSE", style="dim")
    for mid, role, _idx in members:
        model = _oc.meta_get(mid, "model", "?")
        table.add_row(mid, role, model, _ROLE_PURPOSE.get(role, ""))
    ui.console.print(table)


def _pod_add(project: str, extra: list[str]) -> None:
    if not pod_member_ids(project):
        ui.error(f"No pod for '{project}'. Create one first: docket add {project}")
        raise typer.Exit(1)
    role, count = _parse_add_args(extra)
    if role is None:
        ui.error("Usage: docket pod <project> add <role> [--count N]")
        raise typer.Exit(1)

    # Inherit codebase/stack/description from the pod's Lead (or any member).
    base_id = pod_member_ids(project)[0]
    codebase = _oc.meta_get(base_id, "codebase", "")
    stack = _oc.meta_get(base_id, "stack", "")
    description = _oc.meta_get(base_id, "description", "")
    project_key = _oc.meta_get(base_id, "projectKey", "default") or "default"
    role_models, _, _ = _mp.load_registry()

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
        )
        if ok:
            ui.success(f"Added {member.member_id} [{member.role}] {member.model}")
            created.append(member.member_id)
        else:
            ui.warn(f"{member.member_id}: registration failed — {msg}")
    if created:
        _sys.restart_gateway()


def _pod_remove(project: str, extra: list[str]) -> None:
    if not extra:
        ui.error("Usage: docket pod <project> remove <member-id>")
        raise typer.Exit(1)
    member_id = extra[0]
    if pod.parse_member_id(member_id, project) is None:
        ui.error(f"'{member_id}' is not a member of the '{project}' pod.")
        raise typer.Exit(1)
    ok, msg = teardown_member(member_id)
    if ok:
        ui.success(f"Removed {member_id}")
    else:
        ui.warn(f"{member_id}: daemon delete reported: {msg} (workspace cleaned)")
    _sys.restart_gateway()


# ── dispatch queue (AA-7): delegate / queue / dispatch ───────────────────────────


def _pod_delegate(project: str, extra: list[str]) -> None:
    """Queue a task for the pod: ``docket pod <project> delegate [--priority P] "<task>"``."""
    priority = "normal"
    rest: list[str] = []
    i = 0
    while i < len(extra):
        if extra[i] in ("--priority", "-p") and i + 1 < len(extra):
            priority = extra[i + 1]
            i += 2
        else:
            rest.append(extra[i])
            i += 1
    description = rest[0] if rest else ""
    if not description:
        ui.error('Usage: docket pod <project> delegate [--priority high|normal|low] "<task>"')
        raise typer.Exit(1)
    if priority not in ("high", "normal", "low"):
        ui.error(f"Invalid priority '{priority}'. Use: high | normal | low")
        raise typer.Exit(1)
    if len(description) > 500:
        ui.error(f"Description too long ({len(description)} chars). Limit: 500.")
        raise typer.Exit(1)
    try:
        task = _dispatch.enqueue_task(project, description, priority)
    except _dispatch.DispatchError as ex:
        ui.error(str(ex))
        raise typer.Exit(1) from ex
    ui.success(f"Queued for pod '{project}': [{task['id']}] {description}")
    ui.info(f"Run the pipeline: docket pod {project} dispatch")


def _pod_queue(project: str) -> None:
    """Show the pod's task queue."""
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


def _pod_dispatch(project: str) -> None:
    """Drive the pod's pending tasks through the pipeline (one real turn per hop)."""
    try:
        pipeline = _dispatch.pod_pipeline(project)
    except _dispatch.DispatchError as ex:
        ui.error(str(ex))
        raise typer.Exit(1) from ex
    pending = [t for t in _dispatch.read_tasks(project) if t.get("status") == "pending"]
    if not pending:
        ui.warn(f"No pending tasks for pod '{project}'. Queue one: docket pod {project} delegate")
        return
    roles = " → ".join(role for role, _mid in pipeline)
    ui.info(f"Dispatching {len(pending)} task(s) through: {roles}")
    cap = _dispatch.pod_budget(project)
    if cap:
        ui.dim(f"  Pod budget cap: ${cap:.2f} (spent ${_dispatch.pod_recorded_cost(project):.2f})")
    results = _dispatch.dispatch_pod(project)
    for res in results:
        if res.status == "done":
            ui.success(f"  [{res.task_id}] done — {len(res.hops)} hop(s), ${res.cost_usd:.4f}")
        elif res.status == "blocked":
            ui.warn(f"  [{res.task_id}] blocked — {res.reason} (left pending)")
        else:
            ui.error(f"  [{res.task_id}] {res.status} — {res.reason}")


def _parse_add_args(extra: list[str]) -> tuple[str | None, int]:
    """Parse ``<role> [--count N | -n N]`` (or a trailing integer) from extra args."""
    role: str | None = None
    count = 1
    i = 0
    while i < len(extra):
        tok = extra[i]
        if tok in ("--count", "-n") and i + 1 < len(extra):
            with_val = extra[i + 1]
            count = int(with_val) if with_val.isdigit() else 1
            i += 2
            continue
        if tok.isdigit():
            count = int(tok)
        elif role is None:
            role = tok
        i += 1
    return role, count
