"""Pod provisioning: the create-a-pod side effects, UI-free.

Split out of ``interfaces/cli/commands/pod.py``/``interfaces/cli/commands/agents.py``: application code must never import
``ui.py`` or print, and ``POST /pods`` (``interfaces/http/server.py``) needs the same effectful
path ``docket init`` uses, so both callers of ``provision_pod`` share this file.
Kept separate from ``teams/provisioning.py``, whose docstring promises pure,
I/O-free UX helpers -- nearly everything here writes files and shells to git.

Rollback contract: see specs/data/serve-read-api.spec.md (POST /pods) and
specs/data/docket-meta.spec.md (attempt-owned resources).
"""

from __future__ import annotations

import contextlib
import shutil
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote as _url_unquote

from docket.governance.audit import audit_log
from docket.kernel.errors import Conflict, InvalidInput, Unavailable
from docket.kernel.home import current_home
from docket.kernel.ports import git as _git
from docket.models import selection as _mp
from docket.platform import read_json, read_modify_write, with_lock
from docket.teams import blueprints as _bp
from docket.teams import fleet as _fleet
from docket.teams import pod
from docket.teams import provisioning as _prov
from docket.teams import resources as _res
from docket.teams.member_workspace import provision_member
from docket.teams.task_worktrees import (
    TASK_WORKTREES_DIRNAME,
    _teardown_worktree_branch,
    worktree_branch,
)

# A verify command is stored and later run with shell=True (system.py's
# run_command) because real verify pipelines legitimately use `&&`/pipes/
# redirects. This cap only bounds what gets persisted to .docket-meta.json and
# executed — it is generous for any realistic single-line pipeline, not an
# accommodation for arbitrary scripts (write a script file and call *that*
# instead of pasting one here).
_MAX_VERIFY_CMD_LEN = 2000


class VerifyCmdError(InvalidInput):
    """A verify command failed validation before being stored."""


class PodAlreadyExistsError(Conflict):
    """``project`` already has at least one registered pod member.

    Idempotence contract: skip, don't clobber. Raised before anything is touched."""


class PodProvisionError(Unavailable):
    """A fresh pod failed to fully provision.

    Raised only after rollback removes every member/resource the failing call created."""


@dataclass(frozen=True)
class ProvisionedMember:
    """One pod member actually created by `provision_members`/`provision_pod`."""

    member_id: str
    role: str
    model: str


@dataclass(frozen=True)
class PodProvisionResult:
    """A successful `provision_pod` call: the created pod roster."""

    project: str
    blueprint: str
    members: list[ProvisionedMember] = field(default_factory=list)


def validate_verify_cmd(cmd: str) -> str:
    """Validate a verify command before it is persisted to ``.docket-meta.json``.

    Trust boundary: ``run_command`` keeps ``shell=True`` (a real verify
    pipeline needs ``&&``/pipes) because this string is operator-owned -- it
    only reaches docket via an interactive `pod set verify`/`--verify` call (or the
    equivalent `POST /pods` field) and runs as the operator, never as agent or
    network-untrusted input. This only rejects control-character injection and
    bounds length; it does not sandbox, parse, or interpret the command (that's
    the Docker isolation lane)."""
    if "\x00" in cmd:
        raise VerifyCmdError("verify command must not contain a NUL byte")
    if "\n" in cmd or "\r" in cmd:
        raise VerifyCmdError("verify command must not contain a newline")
    if len(cmd) > _MAX_VERIFY_CMD_LEN:
        raise VerifyCmdError(
            f"verify command too long ({len(cmd)} chars, limit {_MAX_VERIFY_CMD_LEN})"
        )
    return cmd


def parse_budget_usd(raw: object) -> float | None:
    """Parse a ``budgetUsd``/``budget`` override from spec or HTTP input.

    Non-positive, ``None``, empty, or non-numeric input all mean "no override"."""
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        value = float(raw)
    else:
        text = str(raw).strip()
        if not text or text == "0":
            return None
        try:
            value = float(text)
        except ValueError:
            return None
    return value if value > 0 else None


def pod_member_ids(project: str) -> list[str]:
    """Registered agent ids that belong to ``project``'s pod (Lead first)."""
    all_ids = [a.id for a in _fleet.list_agents()]
    return [mid for mid, _role, _idx in pod.members_of(all_ids, project)]


def _provision_lock_dir(project: str) -> Path:
    return current_home().workspaces_dir / ".pod-provision-locks" / project.encode().hex()


@contextlib.contextmanager
def _project_provision_lock(project: str) -> Iterator[None]:
    """Serialize one project's provisioning lifecycle without coupling projects.

    Lives outside ``PODS_DIR / project`` since rollback deletes it; an inside lock would relock."""
    lock_dir = _provision_lock_dir(project)
    lock_dir.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        lock_dir.parent.chmod(0o700)
        lock_dir.chmod(0o700)
    with with_lock(lock_dir / ".provision"):
        yield


def _allocate_pod_resources(project: str) -> tuple[int, int, str, bool, bool]:
    """Allocate resources and report ownership of its port and scratch state."""
    start = 0
    count = 0
    created = False

    def allocate(table: dict[str, object]) -> dict[str, object] | None:
        nonlocal start, count, created
        start, count, updated = _res.allocate_pod_ports(project, table)
        created = updated is not table
        return updated if created else None

    read_modify_write(current_home().port_alloc_file, allocate)
    scratch = current_home().pod_scratch_dir(project)
    scratch_created = not scratch.exists()
    scratch.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        # scratch's own parents (PODS_DIR, PODS_DIR/project) are created by the same
        # mkdir(parents=True) call above and inherit umask -- harden them too.
        current_home().pods_dir.chmod(0o700)
        scratch.parent.chmod(0o700)
        scratch.chmod(0o700)
    cache = current_home().pod_cache_dir(project)
    cache.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        cache.chmod(0o700)
    return start, count, str(scratch), created, scratch_created


def allocate_pod_resources(project: str) -> tuple[int, int, str]:
    """Allocate (or return existing) port range + scratch dir for *project*.

    Returns (start, count, scratchDirPath); idempotent (specs/data/docket-meta.spec.md)."""
    start, count, scratch, _allocation_created, _scratch_created = _allocate_pod_resources(project)
    return start, count, str(scratch)


def _free_pod_allocation(project: str) -> None:
    """Release a port allocation while the caller holds any required lock."""

    def free(table: dict[str, object]) -> dict[str, object] | None:
        allocations = table.get("allocations", {})
        if not isinstance(allocations, dict) or project not in allocations:
            return None
        return _res.free_pod_ports(project, table)

    read_modify_write(current_home().port_alloc_file, free)


def _remove_attempt_runtime(project: str, *, scratch_created: bool, work_dir_created: bool) -> None:
    """Remove only Docket runtime paths this failed attempt created."""
    if scratch_created:
        shutil.rmtree(current_home().pod_scratch_dir(project), ignore_errors=True)
        shutil.rmtree(current_home().pod_cache_dir(project), ignore_errors=True)
    if work_dir_created:
        shutil.rmtree(current_home().pod_work_dir(project), ignore_errors=True)
    # Drop an otherwise empty directory created only as a parent above, but
    # preserve any pre-existing or independently-created runtime content.
    with contextlib.suppress(OSError):
        (current_home().pods_dir / project).rmdir()


def _free_pod_resources(project: str) -> None:
    """Release all resources during an explicit whole-pod teardown."""
    _free_pod_allocation(project)
    # The whole directory is Docket-owned. Removing only ``.scratch`` left
    # empty pod ids behind forever and leaked an auto-provisioned ``workdir``.
    pod_runtime = current_home().pods_dir / project
    if pod_runtime.is_dir():
        shutil.rmtree(pod_runtime, ignore_errors=True)


def free_pod_resources(project: str) -> None:
    """Release the port range, scratch dir, and provision-lock dir for *project*; idempotent.

    The lock dir is removed last, after releasing it -- never while still held."""
    with _project_provision_lock(project):
        _free_pod_resources(project)
    shutil.rmtree(_provision_lock_dir(project), ignore_errors=True)


def release_implementer_resources(project: str) -> None:
    """Release the port range and remove the scratch and cache directories of a pod that has
    no implementer left; the pod's memory, configuration and working directory stay."""
    with _project_provision_lock(project):
        _free_pod_allocation(project)
        shutil.rmtree(current_home().pod_scratch_dir(project), ignore_errors=True)
        shutil.rmtree(current_home().pod_cache_dir(project), ignore_errors=True)


def purge_pod_history(project: str, member_ids: list[str]) -> None:
    """Remove durable sessions and traces owned by a deleted pod.

    Removes project-wide and member-scoped key prefixes; audit log stays untouched (evidence)."""
    prefixes = (f"agent:{project}:", *(f"agent:{member_id}:" for member_id in member_ids))
    if current_home().sessions_dir.is_dir():
        for entry in current_home().sessions_dir.iterdir():
            if not entry.is_dir() or not _url_unquote(entry.name).startswith(prefixes):
                continue
            shutil.rmtree(entry, ignore_errors=True)

    for trace_owner in (project, *member_ids):
        trace_dir = current_home().traces_dir / trace_owner
        if trace_dir.is_dir():
            shutil.rmtree(trace_dir, ignore_errors=True)


def teardown_member(member_id: str) -> tuple[bool, str]:
    """Remove one pod member: fleet registration + workspace; task worktrees removed first.

    Does not free pod resources (caller's job). ``note`` reports task branches left
    behind unmerged (see ``_teardown_worktree_branch``); empty otherwise."""
    # Remove the git worktrees first (before the workspace dir disappears).
    ws = current_home().projects_dir / member_id
    try:
        raw = read_json(ws / current_home().meta_file)
        codebase = str(raw.get("codebase", ""))
        project = str(raw.get("pod", ""))
    except Exception:
        codebase = ""
        project = ""
    notes: list[str] = []
    tasks_dir = ws / TASK_WORKTREES_DIRNAME
    if codebase and project and tasks_dir.is_dir():
        for task_dir in sorted(p for p in tasks_dir.iterdir() if p.is_dir()):
            _ok, _err = _git.git_worktree_remove(codebase, str(task_dir))
            note = _teardown_worktree_branch(codebase, worktree_branch(project, task_dir.name))
            if note:
                notes.append(note)
        _git.git_worktree_prune(codebase)
    branch_note = "\n".join(notes)

    # No daemon to unregister from -- fleet.json only.
    with contextlib.suppress(Exception):
        _fleet.remove_agent(member_id)
    if ws.is_dir():
        shutil.rmtree(ws, ignore_errors=True)
    return (True, branch_note)


def provision_members(
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
    verify_cmd: str = "",
    work_dir_created: bool = False,
) -> list[ProvisionedMember]:
    """Provision a fresh pod's members from an already-resolved role list.

    Blueprint-agnostic primitive: allocates pod-level resources (port range +
    scratch dir, only when the roster has an Implementer), provisions each
    member in order (Lead first), and applies ``verify_cmd`` to Implementers
    only. Raises ``PodProvisionError`` with full rollback on failure -- see
    module docstring."""
    role_models, _, _ = _mp.load_registry()
    members = pod.plan_pod(project, roles, project_key=project_key, role_models=role_models)

    allocated_resources = "implementer" in roles
    allocation_owned = False
    scratch_owned = False
    if allocated_resources:
        port_start, port_count, scratch, allocation_owned, scratch_owned = _allocate_pod_resources(
            project
        )
    else:
        port_start, port_count, scratch = 0, 0, ""

    created: list[ProvisionedMember] = []
    try:
        for m in members:
            member_verify_cmd = verify_cmd if (verify_cmd and m.role == "implementer") else ""
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
                verify_cmd=member_verify_cmd,
                work_dir=work_dir,
                blueprint_name=blueprint_name,
                budget_usd=budget_usd,
            )
            if not ok:
                raise PodProvisionError(f"{m.member_id}: {msg}")
            created.append(
                ProvisionedMember(
                    member_id=m.member_id,
                    role=m.role,
                    model=m.model,
                )
            )
    except Exception as exc:
        # Roll back every member created during THIS call, plus any pod-level
        # resources allocated for it -- see module docstring for why this must
        # be unconditional rather than best-effort.
        for cm in created:
            with contextlib.suppress(Exception):
                teardown_member(cm.member_id)
        with contextlib.suppress(Exception):
            if allocation_owned:
                _free_pod_allocation(project)
            _remove_attempt_runtime(
                project,
                scratch_created=scratch_owned,
                work_dir_created=work_dir_created,
            )
        if isinstance(exc, PodProvisionError):
            raise
        raise PodProvisionError(f"{project}: provisioning failed: {exc}") from exc

    return created


def provision_pod(
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
) -> PodProvisionResult:
    """Provision a fresh pod from a blueprint.

    The one code path `docket init` and `POST /pods` both call. See
    specs/data/serve-read-api.spec.md (POST /pods) for the full
    ``location``/``roles``/``budget_usd``/``verify_cmd``/``source`` contract.

    Raises:
      ``PodAlreadyExistsError`` -- pod already exists; checked before anything
        else is resolved.
      ``teams.blueprints.BlueprintError`` -- unknown blueprint name.
      ``VerifyCmdError`` -- ``verify_cmd`` fails validation.
      ``PodProvisionError`` -- a member failed to provision after rollback.
      ``teams.provisioning.ProjectIdError`` -- ``project`` fails ``validate_project_id``;
        checked before the lock and before any path is built.
    """
    project = _prov.validate_project_id(project)
    with _project_provision_lock(project):
        if pod_member_ids(project):
            raise PodAlreadyExistsError(project)

        blueprint = _bp.get_blueprint(blueprint_name)
        roster = roles if roles is not None else blueprint.roles

        if verify_cmd:
            verify_cmd = validate_verify_cmd(verify_cmd)

        codebase = ""
        work_dir = ""
        work_dir_created = False
        if blueprint.workspace_kind == "codebase":
            codebase = location
        else:
            work_dir = location or str(current_home().pod_work_dir(project))
            work_dir_new = not Path(work_dir).exists()
            work_dir_created = not location and work_dir_new
            Path(work_dir).mkdir(parents=True, exist_ok=True)
            if work_dir_new:
                with contextlib.suppress(OSError):
                    Path(work_dir).chmod(0o700)

        effective_budget = budget_usd if budget_usd is not None else blueprint.default_budget_usd

        created = provision_members(
            project,
            roster,
            codebase=codebase,
            stack=stack,
            description=description,
            project_key=project_key,
            work_dir=work_dir,
            blueprint_name=blueprint.name,
            budget_usd=effective_budget,
            verify_cmd=verify_cmd,
            work_dir_created=work_dir_created,
        )

        audit_log(
            "agent.add",
            f"{project} blueprint={blueprint.name} "
            f"pod=({','.join(m.role for m in created)}) source={source}",
        )
        return PodProvisionResult(project=project, blueprint=blueprint.name, members=created)
