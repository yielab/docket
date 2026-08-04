"""docket pod — provision and manage project pods.

A *pod* is the set of project-scoped agents for one project: a Lead plus one or
more workers (Implementer, Reviewer, Tester), each with its own workspace
(no worker serves two projects). Pod members are ordinary project agents with
id ``<project>-<role>`` (``-N`` for duplicates).

Composition logic lives in `core/pod.py`; the actual provisioning I/O
(workspace + templates + meta + fleet registration, with rollback on a
partial failure) lives in `core/pod_provisioning.py` (P22-5) so it is
reachable from `serve.py`'s `POST /pods` without that module ever importing
`docket.cli`. This module renders around that core module's typed results —
`docket add`'s pod path and `POST /pods` both call the same
`core.pod_provisioning.provision_pod`, so the two surfaces cannot drift apart.
"""

from __future__ import annotations

import typer
from rich.table import Table

import docket.config as _cfg
from docket import ui
from docket.core import archetypes as _arch
from docket.core import dispatch as _dispatch
from docket.core import fleet as _fleet
from docket.core import models_policy as _mp
from docket.core import pipeline as _pipeline
from docket.core import pod
from docket.core import pod_provisioning as _pp
from docket.core.audit import audit_log

# Re-exports: this module's public surface (and several tests) reference
# these names on `docket.cli._pod` directly — see core/pod_provisioning.py
# for the real implementation and docstrings.
POD_TEMPLATE_VERSION = _pp.POD_TEMPLATE_VERSION
_MAX_VERIFY_CMD_LEN = _pp._MAX_VERIFY_CMD_LEN
VerifyCmdError = _pp.VerifyCmdError
_validate_verify_cmd = _pp.validate_verify_cmd
_worktree_branch = _pp.worktree_branch
_provision_worktree = _pp.provision_worktree
_member_soul = _pp._member_soul
_member_agents = _pp._member_agents
_member_tools = _pp._member_tools
teardown_member = _pp.teardown_member
free_pod_resources = _pp.free_pod_resources
pod_member_ids = _pp.pod_member_ids


def _role_purpose(role: str) -> str:
    """One-line purpose for a pod role (shown in `docket pod <project>`).

    Sourced from the role's archetype (`RoleArchetype.description`) — built-in,
    starter-library, or user-defined — rather than a second hardcoded map that
    would drift from `core/archetypes.py`'s own descriptions.
    """
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

    Thin rendering wrapper over `core.pod_provisioning.provision_member` —
    prints the worktree-fallback notice (if any) via `ui.dim` and returns the
    legacy `(ok, message)` shape; see the core function for the real docstring.
    """
    ok, msg, fallback_reason = _pp.provision_member(
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
    if fallback_reason:
        ui.dim(f"  [{member.member_id}] worktree fallback: {fallback_reason}")
    return ok, msg


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


def _render_created(members: list[_pp.ProvisionedMember]) -> list[str]:
    """Render each provisioned member's success (+ worktree fallback) line."""
    for m in members:
        if m.worktree_fallback_reason:
            ui.dim(f"  [{m.member_id}] worktree fallback: {m.worktree_fallback_reason}")
        ui.success(f"  {m.member_id}  [{m.role}]  {m.model}")
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
    """Provision a fresh pod's members. Returns the created member ids.

    Thin rendering wrapper over `core.pod_provisioning.provision_members` —
    used by `docket add` (via `build_pod_from_blueprint`) and directly by
    every test that needs a pod fixture with no blueprint involved.
    Allocates pod-level runtime resources (port range + scratch dir) once for
    the whole pod and injects them into each Implementer's workspace —
    skipped entirely when the roster has no Implementer (e.g. a
    research/content/ops blueprint pod). A partial failure (a member after
    the first fails to provision) rolls back every member and any pod-level
    resources this call created, then reports the failure — the same
    all-or-nothing contract `POST /pods` needs, applied here too since the
    two surfaces share one code path.

    ``work_dir``/``blueprint_name``/``budget_usd`` are passed straight
    through to every member — see ``core.pod_provisioning.provision_member``.
    """
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
    """Provision a fresh pod from a named blueprint. Returns the created member ids.

    Thin rendering wrapper over `core.pod_provisioning.provision_pod` — the
    one path `docket add` (interactive, via `cli/_agents.py::run_add`, and
    declarative, via `_provision_pod_from_spec`) and `POST /pods` all share.

    ``location`` is interpreted per the blueprint's ``workspace_kind``: a
    `codebase` blueprint (e.g. `software`) treats it as the pod's codebase
    path — this is the path ``docket add`` with no ``--blueprint`` has always
    passed, so `software` provisions identically to the original
    Lead+Implementer default. A `workdir` blueprint treats it as the pod's
    shared working directory, auto-provisioning one under
    ``config.pod_work_dir(project)`` (0700) when ``location`` is left empty.

    ``roles``, when given, overrides the blueprint's own roster (e.g.
    `docket add`'s ``--pod full``/``--with`` flags extending `software`'s
    lean default) while still applying the blueprint's workspace kind,
    default budget, and name stamp — the blueprint is a starting roster, not
    a hard ceiling. ``budget_usd``/``verify_cmd`` override the blueprint's own
    default budget / apply a verify command to Implementer member(s) at
    creation time — see `core.pod_provisioning.provision_pod`.

    Raises ``core.blueprints.BlueprintError`` for an unknown blueprint name,
    and ``core.pod_provisioning.VerifyCmdError`` for an invalid ``verify_cmd``
    — both render as a clean CLI error upstream, not a traceback. An
    already-existing pod and a genuine mid-provisioning failure both warn and
    return ``[]`` (this function's long-standing "no members" failure
    contract) rather than raising, since every current caller already treats
    an empty return as the failure signal.
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
    elif action == "queue":
        _pod_queue(project, extra)
    elif action == "dispatch":
        _pod_dispatch(project, extra)
    else:
        ui.error(
            f"Unknown pod action {action!r}. "
            "Use: list | add | remove | set-verify | delegate | queue | dispatch."
        )
        raise typer.Exit(1)


def _pod_list(project: str) -> None:
    all_ids = [a.id for a in _fleet.list_agents()]
    members = pod.members_of(all_ids, project)
    if not members:
        ui.warn(f"No pod found for '{project}'. Create one with: docket add {project}")
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
        ui.error(f"No pod for '{project}'. Create one first: docket add {project}")
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

    canon_role = pod.normalize_role(role)
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
            ui.success(f"Added {member.member_id} [{member.role}] {member.model}")
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
    """Rewrite TOOLS.md for an existing Implementer after a meta change (e.g. set-verify).

    No-op for non-implementers and for members with no allocated resources and no
    verify command (nothing to render).
    """
    role = _fleet.meta_get(member_id, "role", "")
    if role != "implementer":
        return
    port_start_s = _fleet.meta_get(member_id, "portRangeStart", "")
    port_count_s = _fleet.meta_get(member_id, "portRangeCount", "")
    scratch = _fleet.meta_get(member_id, "scratchDir", "")
    verify_cmd = _fleet.meta_get(member_id, "verifyCmd", "")
    if not ((port_start_s and scratch) or verify_cmd):
        return
    worktree_dir = _fleet.meta_get(member_id, "worktreeDir", "")
    raw_codebase = _fleet.meta_get(member_id, "codebase", "")
    codebase = pod.resolve_member_cwd(member_id, worktree_dir, raw_codebase)
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
    TOOLS.md so the Implementer sees the updated gate. The command is validated
    (no NUL/newline, length-capped — see ``_validate_verify_cmd``) and the change
    is audit-logged: docket still runs it with ``shell=True`` once stored.
    """
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


def _pod_queue(project: str, extra: list[str]) -> None:
    """Show the pod's task queue, or ``queue --retry <task-id>`` to un-block one task.

    A ``blocked`` task (budget cap reached) never retries on its own —
    ``--retry`` is the explicit, single-task way back to ``pending``; a pod-wide
    budget change (``docket profile <lead-id> --budget ...``) un-blocks the
    whole pod's queue instead.
    """
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


def _parse_dispatch_args(extra: list[str]) -> tuple[bool, int | None]:
    """Parse ``[--resume] [--timeout SECONDS]`` for ``docket pod <p> dispatch``.

    ``--timeout`` overrides *both* the agent-turn and the verifyCmd
    timeout for this one invocation — a blanket ad hoc override, independent of
    (and taking precedence over) the pod's own persisted Lead-meta
    ``turnTimeoutS``/``verifyTimeoutS``. Raises ValueError on a non-positive or
    non-integer value so the caller can render one consistent error message.
    """
    resume = "--resume" in extra
    timeout: int | None = None
    if "--timeout" in extra:
        i = extra.index("--timeout")
        raw = extra[i + 1] if i + 1 < len(extra) else ""
        timeout = int(raw)
        if timeout <= 0:
            raise ValueError(raw)
    return resume, timeout


def _pod_dispatch(
    project: str, extra: list[str], *, spec: _pipeline.PipelineSpec | None = None
) -> None:
    """Drive the pod's pending tasks through the pipeline (one real turn per hop).

    ``--resume`` also reclaims tasks a prior dispatcher left ``failed`` with a
    stale claim (it crashed mid-task) and continues each one from its last
    persisted hop instead of restarting at hop 0 (crash recovery).
    ``--timeout SECONDS`` overrides both the agent-turn and verifyCmd
    timeout for this run only; unset, each falls back to the pod's own
    Lead-meta ``turnTimeoutS``/``verifyTimeoutS``, then ``DEFAULT_TIMEOUT``.

    This invocation is recorded in the run registry (source ``"cli"``)
    like every other dispatch path — an exception here is no longer just a
    traceback, it is also visible afterwards via ``docket runs show``.

    *spec* — when given (by ``docket pipeline run``, the only other
    caller) — is forwarded to ``dispatch_pod`` unchanged; ``None`` (every
    ``docket pod <project> dispatch`` call) resolves the pod's default
    Lead→Implementer→Reviewer→Tester pipeline. This is the one shared
    implementation both CLI surfaces drive, so there is no second,
    drift-prone copy of this rendering logic.
    """
    from docket.core import runs as _runs

    try:
        resume, timeout_override = _parse_dispatch_args(extra)
    except ValueError:
        ui.error("--timeout requires a positive integer number of seconds.")
        raise typer.Exit(1) from None
    try:
        pipeline = _dispatch.pod_pipeline(project)
    except _dispatch.DispatchError as ex:
        ui.error(str(ex))
        raise typer.Exit(1) from ex
    tasks = _dispatch.read_tasks(project)
    pending = [t for t in tasks if t.get("status") == "pending"]
    resumable = (
        [t for t in tasks if t.get("status") == "failed" and t.get("failureKind") == "stale_claim"]
        if resume
        else []
    )
    if not pending and not resumable:
        ui.warn(f"No pending tasks for pod '{project}'. Queue one: docket pod {project} delegate")
        return
    count_label = f"{len(pending)} pending"
    if resume:
        count_label += f", {len(resumable)} resumable"
    if spec is not None:
        ui.info(f"Dispatching {count_label} task(s) through pipeline '{spec.name}'")
    else:
        roles = " → ".join(role for role, _mid in pipeline)
        ui.info(f"Dispatching {count_label} task(s) through: {roles}")
    cap = _dispatch.pod_budget(project)
    if cap:
        ui.dim(f"  Pod budget cap: ${cap:.2f} (spent ${_dispatch.pod_recorded_cost(project):.2f})")

    record = _runs.create_run("cli", project)
    results = _runs.execute(
        record["id"],
        lambda: _dispatch.dispatch_pod(
            project,
            resume=resume,
            turn_timeout=timeout_override,
            verify_timeout=timeout_override,
            spec=spec,
        ),
    )
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
                ui.dim(f"[dispatch] verification skipped — verifyCmd not set for {hop.member_id}")
        if res.status == "done":
            ui.success(f"  [{res.task_id}] done — {len(res.hops)} hop(s), ${res.cost_usd:.4f}")
        elif res.status == "blocked":
            ui.warn(f"  [{res.task_id}] blocked — {res.reason}")
        elif res.status == "waiting_approval":
            # Waiting on a human decision is an expected pause, not a
            # failure — same warn-not-error treatment as a budget block.
            ui.warn(f"  [{res.task_id}] waiting_approval — {res.reason}")
        else:
            ui.error(f"  [{res.task_id}] {res.status} — {res.reason}")


def _parse_add_args(extra: list[str]) -> tuple[str | None, int, str]:
    """Parse ``<role> [--count N | -n N] [--verify "<cmd>"]`` (or a trailing integer).

    ``--verify`` (Implementer only; ignored with a warning for other roles) sets the
    mechanical verification gate `dispatch.py` runs after the new member's hop.
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
