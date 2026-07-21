"""docket pod — provision and manage project pods.

A *pod* is the set of project-scoped agents for one project: a Lead plus one or
more workers (Implementer, Reviewer, Tester), each with its own workspace
(no worker serves two projects). Pod members are ordinary project agents with
id ``<project>-<role>`` (``-N`` for duplicates).

Composition logic lives in `core/pod.py`; this module does the I/O: workspace +
templates + meta + daemon registration via the ACL.
"""

from __future__ import annotations

import contextlib
import shutil
from datetime import UTC, datetime

import typer
from rich.table import Table

import docket.config as _cfg
from docket import ui
from docket.core import dispatch as _dispatch
from docket.core import memory as _mem
from docket.core import models_policy as _mp
from docket.core import pod
from docket.core import resources as _res
from docket.edges import store as _store
from docket.edges.adapters import openclaw as _oc
from docket.edges.adapters import system as _sys

# Bump when the pod-member templates change (doctor flags older members).
POD_TEMPLATE_VERSION = 2

# One-line purpose per pod role (shown in `docket pod <project>`).
_ROLE_PURPOSE: dict[str, str] = {
    "lead": "orchestrates the pod; never edits code",
    "implementer": "writes code in the project workspace",
    "reviewer": "read-only veto on diffs",
    "tester": "behaviour-only PASS/FAIL",
}


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
        f"## Codebase\n{codebase or '(no codebase configured)'}\n\n"
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
            "- **Marker convention:** the first non-blank line of your reply must be "
            "exactly `PASS` or `FAIL` (case-insensitive) — dispatch parses this line "
            "to gate the pipeline. Evidence goes on the lines after it. Anything else "
            "on that first line blocks the pipeline the same as a FAIL.\n"
        )
    return head + body


def _member_tools(
    project: str,
    role: str,
    codebase: str,
    port_range_start: int,
    port_range_count: int,
    scratch_dir: str,
    verify_cmd: str = "",
) -> str:
    """TOOLS.md for an Implementer — includes allocated runtime resources.

    ``verify_cmd``, when set, is the mechanical gate ``dispatch.py`` runs after this
    Implementer's hop (CD-2) — surfaced here so the agent can see what its work
    must pass before signaling done.
    """
    port_end = port_range_start + port_range_count - 1
    lines = [
        f"# TOOLS.md — {project} · {role}",
        "",
        "## Runtime Resources (pod-isolated — allocated by docket)",
        "",
        "These are real **environment variables** docket sets on your process at "
        "dispatch time — not just documentation here, so read them at runtime "
        "instead of hardcoding values.",
        "",
        "Your pod has a reserved, non-overlapping port range.  "
        "**Never use ports outside it** — other pods may have adjacent ranges.",
        f"- `DOCKET_PORT_BASE={port_range_start}` — bind services to {port_range_start}-{port_end}",
        f"- `DOCKET_PORT_COUNT={port_range_count}`",
        "",
        "Isolated scratch data directory (yours alone — safe for test DBs, caches, temp state):",
        f"- `DOCKET_SCRATCH_DIR={scratch_dir}`",
        f"- DB namespace prefix: `{project}_`  (e.g. `{project}_test`, `{project}_cache`)",
    ]
    if codebase:
        lines += [
            "",
            "## Codebase",
            f"Project root: `{codebase}`",
        ]
    if verify_cmd:
        lines += [
            "",
            "## Verification Gate",
            "After each of your hops, docket mechanically runs this command and blocks "
            "completion on a non-zero exit — make it pass before signaling done:",
            f"- `{verify_cmd}`",
        ]
    return "\n".join(lines) + "\n"


def _member_agents(member: pod.PodMember, project: str) -> str:
    # Section names matter: the openclaw runtime re-injects the "Session Startup"
    # and "Red Lines" H2 blocks after every compaction (readPostCompactionContext).
    # Keep these headings verbatim or the injection silently stops firing.
    return (
        f"# AGENTS.md — {project} · {member.role}\n\n"
        "## Session Startup\n"
        "_Lean — re-sent every turn._\n"
        f"1. Read {_mem.REQUIRED_STARTUP_FILE} — startup protocol + your codebase\n"
        "   path (the runtime requires this after every context reset).\n"
        "2. Read HEARTBEAT.md — active tasks/decisions (small; always). Unchecked\n"
        "   items mean you were interrupted mid-task: resume them, don't greet idle.\n"
        "3. Read memory/YYYY-MM-DD.md only when the task needs prior context;\n"
        "   don't slurp the whole memory/ dir — what you read is re-sent every\n"
        "   later turn.\n\n"
        "## Red Lines\n"
        f"- Stay within the `{project}` pod; coordinate only within it (the Lead\n"
        "  routes work between members). No cross-project access.\n"
        "- Never push to main/master or delete files without HITL approval.\n"
        "- Before starting multi-step work, write it to HEARTBEAT.md — an unwritten\n"
        "  task does not survive a context reset.\n"
    )


def _worktree_branch(project: str, member_id: str) -> str:
    """Branch name for an Implementer's git worktree: ``docket/<project>/<member-id>``."""
    return f"docket/{project}/{member_id}"


def _write_member_workspace(
    member: pod.PodMember,
    codebase: str,
    stack: str,
    description: str,
    project: str,
    project_key: str,
    *,
    port_range_start: int = 0,
    port_range_count: int = 0,
    scratch_dir: str = "",
    worktree_dir: str = "",
    verify_cmd: str = "",
) -> None:
    ws = _cfg.PROJECTS_DIR / member.member_id
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "memory").mkdir(exist_ok=True)
    (ws / "SOUL.md").write_text(
        _member_soul(member, project, codebase, stack, description), encoding="utf-8"
    )
    (ws / "AGENTS.md").write_text(_member_agents(member, project), encoding="utf-8")
    (ws / "HEARTBEAT.md").write_text(_mem.heartbeat_seed(member.member_id), encoding="utf-8")
    if member.role == "implementer" and ((port_range_start and scratch_dir) or verify_cmd):
        (ws / "TOOLS.md").write_text(
            _member_tools(
                project,
                member.role,
                worktree_dir or codebase,
                port_range_start,
                port_range_count,
                scratch_dir,
                verify_cmd,
            ),
            encoding="utf-8",
        )
    # Seed the files the openclaw post-compaction audit re-reads every reset,
    # anchoring the codebase path where a just-reset agent will actually see it.
    _mem.seed_contract(ws, project=project, codebase=codebase, stack=stack)

    # Keep pod-member identity docket-owned: quarantine OpenClaw's self-authoring
    # scaffolding (IDENTITY.md/BOOTSTRAP.md) so it can't split the member's identity.
    from docket.core import identity as _identity

    _identity.quarantine_scaffolding(ws)

    with contextlib.suppress(OSError):
        ws.chmod(0o700)

    meta: dict[str, object] = {
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
    if member.role == "implementer" and port_range_start:
        meta["portRangeStart"] = port_range_start
        meta["portRangeCount"] = port_range_count
        meta["scratchDir"] = scratch_dir
    if member.role == "implementer" and verify_cmd:
        meta["verifyCmd"] = verify_cmd
    if worktree_dir:
        meta["worktreeDir"] = worktree_dir
        meta["worktreeBranch"] = _worktree_branch(project, member.member_id)
    meta_file = ws / _cfg.META_FILE
    _store.write_json(meta_file, meta)


def _provision_worktree(member: pod.PodMember, project: str, codebase: str) -> tuple[str, str]:
    """Try to provision a git worktree for a repo Implementer.

    Returns ``(worktree_dir, fallback_reason)``.  On success ``worktree_dir``
    is set and ``fallback_reason`` is ''.  On failure ``worktree_dir`` is ''
    and ``fallback_reason`` explains why the flat-dir fallback was used.
    """
    if not codebase:
        return "", ""  # no codebase — worktrees do not apply
    if member.role != "implementer":
        return "", ""
    if not _sys.git_is_repo(codebase):
        return "", f"codebase '{codebase}' is not a git repo — using flat workspace"
    branch = _worktree_branch(project, member.member_id)
    # Place the worktree inside the docket workspace for this member so it is
    # cleaned up with the workspace dir on teardown.
    wt_path = str(_cfg.PROJECTS_DIR / member.member_id / "worktree")
    ok, err = _sys.git_worktree_add(codebase, wt_path, branch)
    if not ok:
        return "", f"git worktree add failed ({err}) — using flat workspace"
    return wt_path, ""


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
) -> tuple[bool, str]:
    """Create one pod member's workspace + meta and register it with the daemon.

    Does NOT restart the gateway — the caller batches one restart per command.
    For repo pods, Implementers get a git worktree on a dedicated branch.
    Falls back to the flat docket workspace if git is unavailable or the
    codebase is not a git repo. ``verify_cmd`` (Implementer only) is the
    mechanical gate `dispatch.py` runs after this member's hop (CD-2/FD-1).
    """
    worktree_dir, fallback_reason = _provision_worktree(member, project, codebase)
    if fallback_reason:
        ui.dim(f"  [{member.member_id}] worktree fallback: {fallback_reason}")
    _write_member_workspace(
        member,
        codebase,
        stack,
        description,
        project,
        project_key,
        port_range_start=port_range_start,
        port_range_count=port_range_count,
        scratch_dir=scratch_dir,
        worktree_dir=worktree_dir,
        verify_cmd=verify_cmd,
    )
    ws_path = str(_cfg.PROJECTS_DIR / member.member_id)

    if shutil.which("openclaw"):
        ok, msg = _oc.register_agent_cli(member.member_id, ws_path, member.model)
        if not ok:
            return (False, msg)
    else:
        _oc.add_agent(member.member_id, member.model, member.session_key, project_key)

    _oc.sync_session_key(member.member_id, member.session_key, project_key)
    return (True, "")


def _allocate_pod_resources(project: str) -> tuple[int, int, str]:
    """Allocate (or return existing) port range + scratch dir for *project*.

    Returns ``(portRangeStart, portRangeCount, scratchDirPath)``.
    Writes the updated port-allocation table atomically via store.py.
    Creates the scratch dir (0700) if it does not exist.

    Idempotent: re-calling for the same project returns the same values.
    """
    table = _store.read_json(_cfg.PORT_ALLOC_FILE)
    start, count, updated = _res.allocate_pod_ports(project, table)
    if updated is not table:
        _store.write_json(_cfg.PORT_ALLOC_FILE, updated)
    scratch = _cfg.pod_scratch_dir(project)
    scratch.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        scratch.chmod(0o700)
    return start, count, str(scratch)


def free_pod_resources(project: str) -> None:
    """Release the port range and remove the scratch dir for *project*.

    Called by pod teardown paths (docket delete / docket pod remove last-implementer).
    Idempotent: safe to call even if no resources were allocated.
    """
    table = _store.read_json(_cfg.PORT_ALLOC_FILE)
    if table:
        updated = _res.free_pod_ports(project, table)
        _store.write_json(_cfg.PORT_ALLOC_FILE, updated)
    scratch = _cfg.pod_scratch_dir(project)
    if scratch.is_dir():
        shutil.rmtree(scratch, ignore_errors=True)


def teardown_member(member_id: str) -> tuple[bool, str]:
    """Remove one pod member: daemon registration + workspace + agents.list entry.

    Does NOT restart the gateway — the caller batches one restart per command.
    Does NOT free pod resources — the caller is responsible for that when it
    knows the full pod is being torn down or the last implementer is leaving.
    If the member has a git worktree, it is removed before the workspace dir.
    """
    # Remove the git worktree first (before the workspace dir disappears).
    ws = _cfg.PROJECTS_DIR / member_id
    try:
        raw = _store.read_json(ws / _cfg.META_FILE)
        worktree_dir = str(raw.get("worktreeDir", ""))
        codebase = str(raw.get("codebase", ""))
    except Exception:
        worktree_dir = ""
        codebase = ""
    if worktree_dir and codebase:
        _ok, _err = _sys.git_worktree_remove(codebase, worktree_dir)

    ok, msg = (True, "")
    if shutil.which("openclaw"):
        ok, msg = _oc.unregister_agent_cli(member_id)
    # Belt-and-braces: ensure it's gone from agents.list and the docket workspace.
    with contextlib.suppress(Exception):
        _oc.remove_agent(member_id)
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
    Allocates pod-level runtime resources (port range + scratch dir) once for the
    whole pod and injects them into each Implementer's workspace.
    """
    role_models, _, _ = _mp.load_registry()
    members = pod.plan_pod(project, roles, project_key=project_key, role_models=role_models)

    port_start, port_count, scratch = _allocate_pod_resources(project)

    created: list[str] = []
    for m in members:
        ok, msg = provision_member(
            m,
            codebase=codebase,
            stack=stack,
            description=description,
            project=project,
            project_key=project_key,
            port_range_start=port_start if m.role == "implementer" else 0,
            port_range_count=port_count if m.role == "implementer" else 0,
            scratch_dir=scratch if m.role == "implementer" else "",
        )
        if ok:
            ui.success(f"  {m.member_id}  [{m.role}]  {m.model}")
            created.append(m.member_id)
        else:
            ui.warn(f"  {m.member_id}: registration failed — {msg}")
    from docket.cli import _render_restart_result

    _render_restart_result(_sys.restart_gateway())
    return created


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
    elif action == "queue":
        _pod_queue(project)
    elif action == "dispatch":
        _pod_dispatch(project)
    else:
        ui.error(
            f"Unknown pod action {action!r}. "
            "Use: list | add | remove | set-verify | delegate | queue | dispatch."
        )
        raise typer.Exit(1)


def _pod_list(project: str) -> None:
    all_ids = [a.id for a in _oc.list_agents()]
    members = pod.members_of(all_ids, project)
    if not members:
        ui.warn(f"No pod found for '{project}'. Create one with: docket add {project}")
        return
    has_resources = any(bool(_oc.meta_get(mid, "portRangeStart", "")) for mid, _, _ in members)
    table = Table(title=f"Pod — {project}")
    table.add_column("MEMBER", style="bold")
    table.add_column("ROLE")
    table.add_column("MODEL")
    table.add_column("PURPOSE", style="dim")
    if has_resources:
        table.add_column("PORTS")
        table.add_column("SCRATCH")
    for mid, role, _idx in members:
        model = _oc.meta_get(mid, "model", "?")
        if has_resources:
            port_start_s = _oc.meta_get(mid, "portRangeStart", "")
            port_count_s = _oc.meta_get(mid, "portRangeCount", "")
            scratch = _oc.meta_get(mid, "scratchDir", "")
            if port_start_s and port_count_s:
                try:
                    port_end = int(port_start_s) + int(port_count_s) - 1
                    ports_str = f"{port_start_s}-{port_end}"
                except ValueError:
                    ports_str = port_start_s
            else:
                ports_str = "—"
            table.add_row(mid, role, model, _ROLE_PURPOSE.get(role, ""), ports_str, scratch or "—")
        else:
            table.add_row(mid, role, model, _ROLE_PURPOSE.get(role, ""))
    ui.console.print(table)


def _pod_add(project: str, extra: list[str]) -> None:
    if not pod_member_ids(project):
        ui.error(f"No pod for '{project}'. Create one first: docket add {project}")
        raise typer.Exit(1)
    role, count, verify_cmd = _parse_add_args(extra)
    if role is None:
        ui.error('Usage: docket pod <project> add <role> [--count N] [--verify "<cmd>"]')
        raise typer.Exit(1)

    # Inherit codebase/stack/description from the pod's Lead (or any member).
    base_id = pod_member_ids(project)[0]
    codebase = _oc.meta_get(base_id, "codebase", "")
    stack = _oc.meta_get(base_id, "stack", "")
    description = _oc.meta_get(base_id, "description", "")
    project_key = _oc.meta_get(base_id, "projectKey", "default") or "default"
    role_models, _, _ = _mp.load_registry()

    canon_role = pod.normalize_role(role)
    if canon_role == "implementer":
        port_start, port_count, scratch = _allocate_pod_resources(project)
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
        )
        if ok:
            ui.success(f"Added {member.member_id} [{member.role}] {member.model}")
            created.append(member.member_id)
        else:
            ui.warn(f"{member.member_id}: registration failed — {msg}")
    if created:
        from docket.cli import _render_restart_result

        _render_restart_result(_sys.restart_gateway())


def _pod_remove(project: str, extra: list[str]) -> None:
    if not extra:
        ui.error("Usage: docket pod <project> remove <member-id>")
        raise typer.Exit(1)
    member_id = extra[0]
    if pod.parse_member_id(member_id, project) is None:
        ui.error(f"'{member_id}' is not a member of the '{project}' pod.")
        raise typer.Exit(1)
    # Read role before teardown removes the workspace.
    role = _oc.meta_get(member_id, "role", "")
    ok, msg = teardown_member(member_id)
    if ok:
        ui.success(f"Removed {member_id}")
    else:
        ui.warn(f"{member_id}: daemon delete reported: {msg} (workspace cleaned)")
    # Free runtime resources if this was the last implementer in the pod.
    if role == "implementer":
        remaining = pod_member_ids(project)
        remaining_roles = {_oc.meta_get(mid, "role", "") for mid in remaining}
        if "implementer" not in remaining_roles:
            free_pod_resources(project)
    from docket.cli import _render_restart_result

    _render_restart_result(_sys.restart_gateway())


def _regenerate_member_tools(member_id: str, project: str) -> None:
    """Rewrite TOOLS.md for an existing Implementer after a meta change (e.g. set-verify).

    No-op for non-implementers and for members with no allocated resources and no
    verify command (nothing to render).
    """
    role = _oc.meta_get(member_id, "role", "")
    if role != "implementer":
        return
    port_start_s = _oc.meta_get(member_id, "portRangeStart", "")
    port_count_s = _oc.meta_get(member_id, "portRangeCount", "")
    scratch = _oc.meta_get(member_id, "scratchDir", "")
    verify_cmd = _oc.meta_get(member_id, "verifyCmd", "")
    if not ((port_start_s and scratch) or verify_cmd):
        return
    codebase = _oc.meta_get(member_id, "worktreeDir", "") or _oc.meta_get(member_id, "codebase", "")
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


def _pod_set_verify(project: str, extra: list[str]) -> None:
    """Set the verify command on an existing Implementer.

    Usage: ``docket pod <project> set-verify <member-id> "<cmd>"``. Rewrites
    TOOLS.md so the Implementer sees the updated gate.
    """
    if len(extra) < 2:
        ui.error('Usage: docket pod <project> set-verify <member-id> "<cmd>"')
        raise typer.Exit(1)
    member_id, *cmd_parts = extra
    verify_cmd = " ".join(cmd_parts)
    if pod.parse_member_id(member_id, project) is None:
        ui.error(f"'{member_id}' is not a member of the '{project}' pod.")
        raise typer.Exit(1)
    role = _oc.meta_get(member_id, "role", "")
    if role != "implementer":
        ui.error(
            f"'{member_id}' is a {role or 'unknown role'} — verifyCmd only applies to implementers."
        )
        raise typer.Exit(1)
    _oc.meta_set(member_id, "verifyCmd", verify_cmd)
    _regenerate_member_tools(member_id, project)
    ui.success(f"Set verify command for {member_id}: {verify_cmd!r}")


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


def _parse_add_args(extra: list[str]) -> tuple[str | None, int, str]:
    """Parse ``<role> [--count N | -n N] [--verify "<cmd>"]`` (or a trailing integer).

    ``--verify`` (Implementer only; ignored with a warning for other roles) sets the
    mechanical verification gate `dispatch.py` runs after the new member's hop (CD-2).
    """
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
        if tok.isdigit():
            count = int(tok)
        elif role is None:
            role = tok
        i += 1
    return role, count, verify_cmd
