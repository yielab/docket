"""Pod provisioning — the create-a-pod side effects, UI-free.

Extracted (P22-5) from ``cli/_pod.py``/``cli/_agents.py``, which used to make
these decisions *and* render around them in the same functions (``ui.success``/
``ui.warn`` calls interleaved with workspace writes and fleet registration).
``core/`` may never import ``ui.py`` or print (CLAUDE.md's layer rule), and
``POST /pods`` needs this same effectful path reachable from ``serve.py`` —
which never imports ``docket.cli`` — so the decisions and effects had to move
here first. ``cli/_pod.py`` now renders around this module's typed return
values; ``docket add`` and ``POST /pods`` both call ``provision_pod`` below,
so the two surfaces cannot drift apart.

This is deliberately its own module rather than an extension of
``core/provisioning.py``: that module is documented as small, pure UX helpers
(slug/name/stack suggestions, no I/O) for the interactive prompt flow. Nearly
everything here is the opposite — it creates directories, writes files,
registers fleet entries and shells out to git — so folding it into a "pure
helpers" module would make that file's own docstring false the moment this
one landed.

**Rollback.** ``provision_pod``/``provision_members`` provision a pod
member-by-member (Lead first). If any member after the first fails, every
member already created during *this* call — its workspace directory and its
fleet registration — is torn down, and any pod-level resources (port range,
scratch dir) allocated for this attempt are freed, before ``PodProvisionError``
is raised. A half-created pod is worse than no pod: the HTTP caller (Tack)
rolls back its own project record on a non-2xx response and has no way to roll
back a half-created pod on docket's side for us.
"""

from __future__ import annotations

import contextlib
import shutil
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import unquote as _url_unquote

import docket.config as _cfg
from docket.core import archetypes as _arch
from docket.core import blueprints as _bp
from docket.core import fleet as _fleet
from docket.core import memory as _mem
from docket.core import models_policy as _mp
from docket.core import pod
from docket.core import resources as _res
from docket.core.audit import audit_log
from docket.edges import store as _store
from docket.edges.adapters import system as _sys

# Bump when the pod-member templates change (doctor flags older members).
POD_TEMPLATE_VERSION = 2

# A verify command is stored and later run with shell=True (system.py's
# run_verify_cmd) because real verify pipelines legitimately use `&&`/pipes/
# redirects. This cap only bounds what gets persisted to .docket-meta.json and
# executed — it is generous for any realistic single-line pipeline, not an
# accommodation for arbitrary scripts (write a script file and call *that*
# instead of pasting one here).
_MAX_VERIFY_CMD_LEN = 2000


class VerifyCmdError(ValueError):
    """A verify command failed validation before being stored."""


class PodAlreadyExistsError(Exception):
    """``project`` already has at least one registered pod member.

    Matches the declarative ``--from`` path's long-standing idempotence
    contract: skip, don't clobber. Raised before anything is touched.
    """


class PodProvisionError(Exception):
    """A fresh pod failed to fully provision.

    Raised only *after* rollback has already run — no member workspace,
    fleet registration, or pod-level resource (port range / scratch dir)
    created during the failing call survives.
    """


@dataclass(frozen=True)
class ProvisionedMember:
    """One pod member actually created by `provision_members`/`provision_pod`."""

    member_id: str
    role: str
    model: str
    worktree_fallback_reason: str = ""


@dataclass(frozen=True)
class PodProvisionResult:
    """A successful `provision_pod` call: the created pod roster."""

    project: str
    blueprint: str
    members: list[ProvisionedMember] = field(default_factory=list)


def validate_verify_cmd(cmd: str) -> str:
    """Validate a verify command before it is persisted to ``.docket-meta.json``.

    Trust boundary: docket keeps ``run_verify_cmd``'s ``shell=True`` (verify
    commands need `&&`/pipes) because this string is **operator-owned** — it only
    ever reaches docket through an interactive `set-verify`/`--verify` CLI
    invocation (or, since P22-5, the equivalent `POST /pods` field) the operator
    supplied directly, never from agent or network-untrusted input, and docket
    executes it as the operator when the pipeline later runs it. This validation
    only rejects control-character injection and bounds length; it does not
    sandbox, parse, or otherwise interpret the command (that's the Docker
    isolation lane, out of scope here).
    """
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

    Accepts a number or a numeric string. ``None``, ``""``, ``"0"``, a
    non-numeric string, or a value <= 0 all mean "no override" (fall back to
    the blueprint's own default) — matching the declarative ``--from`` path's
    long-standing ``if budget and budget != "0"`` guard, generalized to also
    accept a bare JSON number the way an HTTP body naturally carries one.
    """
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


def worktree_branch(project: str, member_id: str) -> str:
    """Branch name for an Implementer's git worktree: ``docket/<project>/<member-id>``."""
    return f"docket/{project}/{member_id}"


def provision_worktree(member: pod.PodMember, project: str, codebase: str) -> tuple[str, str]:
    """Try to provision a git worktree for a repo Implementer.

    Returns ``(worktree_dir, fallback_reason)``. On success ``worktree_dir``
    is set and ``fallback_reason`` is ''. On failure ``worktree_dir`` is ''
    and ``fallback_reason`` explains why the flat-dir fallback was used.
    """
    if not codebase:
        return "", ""  # no codebase — worktrees do not apply
    if member.role != "implementer":
        return "", ""
    if not _sys.git_is_repo(codebase):
        return "", f"codebase '{codebase}' is not a git repo — using flat workspace"
    branch = worktree_branch(project, member.member_id)
    # Place the worktree inside the docket workspace for this member so it is
    # cleaned up with the workspace dir on teardown.
    wt_path = str(_cfg.PROJECTS_DIR / member.member_id / "worktree")
    ok, err = _sys.git_worktree_add(codebase, wt_path, branch)
    if not ok:
        return "", f"git worktree add failed ({err}) — using flat workspace"
    return wt_path, ""


def _render_context(
    member: pod.PodMember,
    project: str,
    codebase: str,
    stack: str,
    description: str,
    *,
    work_dir: str = "",
) -> dict[str, str]:
    """Template variables for a pod member's SOUL.md/AGENTS.md archetype.

    Guaranteed, cross-archetype variables: ``project``, ``objective``,
    ``codebase``, ``workDir`` (always populated, safe for a user-authored
    archetype to reference). The rest
    (``memberId``/``sessionKey``/``role``/``stack``/``codebaseOrConfigured``/
    ``codebaseOrIt``/``requiredStartupFile``) are additional context docket's
    own built-in/starter archetypes rely on for exact legacy prose parity.

    ``work_dir``: the shared working directory for a `workdir`-kind pod
    blueprint (research/content/ops) — mutually exclusive with ``codebase``.
    Empty for every `codebase`-kind (including `software`) pod, so ``workDir``
    falls back to ``codebase`` (or the workspace dir) as usual.
    """
    return {
        "project": project,
        "role": member.role,
        "memberId": member.member_id,
        "sessionKey": member.session_key,
        "objective": description or project,
        "codebase": codebase,
        "codebaseOrConfigured": codebase or "(no codebase configured)",
        "codebaseOrIt": codebase or "it",
        "stack": stack,
        "workDir": work_dir or codebase or str(_cfg.workspace_dir(member.member_id)),
        "requiredStartupFile": _mem.REQUIRED_STARTUP_FILE,
    }


def _member_soul(
    member: pod.PodMember,
    project: str,
    codebase: str,
    stack: str,
    description: str,
    *,
    work_dir: str = "",
) -> str:
    """Render a pod member's SOUL.md from its archetype's `soulTemplate`.

    Byte-identical to the legacy hand-written per-role generator for the four
    built-in roles (lead/implementer/reviewer/tester) — see
    `tests/python/test_archetypes.py`. No role-specific branching lives
    here; the prose is data in `core/archetypes.py`.
    """
    arch = _arch.load_registry().get(member.role)
    if arch is None:
        raise pod.PodError(f"no archetype registered for role {member.role!r}")
    variables = _render_context(member, project, codebase, stack, description, work_dir=work_dir)
    return _arch.render(arch.soul_template, variables)


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
    Implementer's hop — surfaced here so the agent can see what its work
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
    """Render a pod member's AGENTS.md from its archetype's `agentsTemplate`.

    Byte-identical to the legacy hand-written generator for the four built-in
    roles. Section names matter to the live prompt projection: ``Session
    Startup`` belongs only to the manual/reset file and is omitted after the
    runtime has loaded private state, while ``Red Lines`` and custom H2 blocks
    remain model-visible (see `core.identity.system_prompt_for_agent`).
    """
    arch = _arch.load_registry().get(member.role)
    if arch is None:
        raise pod.PodError(f"no archetype registered for role {member.role!r}")
    variables = _render_context(member, project, "", "", "")
    return _arch.render(arch.agents_template, variables)


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
    work_dir: str = "",
    blueprint_name: str = "",
    budget_usd: float | None = None,
) -> None:
    ws = _cfg.PROJECTS_DIR / member.member_id
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "memory").mkdir(exist_ok=True)
    # The path this member is *told* to work in must be one its tool calls are
    # allowed to reach: the driver's `_resolve_roots` returns the worktree
    # ALONE when there is one, so naming the origin checkout here would advertise
    # a path every read/write is then refused for -- a silent failure that burns
    # the whole token budget on retries. Empty for every non-worktree member, so
    # their files are byte-identical.
    told_root = worktree_dir or codebase
    (ws / "SOUL.md").write_text(
        _member_soul(member, project, told_root, stack, description, work_dir=work_dir),
        encoding="utf-8",
    )
    (ws / "AGENTS.md").write_text(_member_agents(member, project), encoding="utf-8")
    (ws / _mem.HEARTBEAT_FILE).write_text(_mem.heartbeat_seed(member.member_id), encoding="utf-8")
    if member.role == "implementer" and ((port_range_start and scratch_dir) or verify_cmd):
        (ws / "TOOLS.md").write_text(
            _member_tools(
                project,
                member.role,
                told_root,
                port_range_start,
                port_range_count,
                scratch_dir,
                verify_cmd,
            ),
            encoding="utf-8",
        )
    # Seed the files the turn loop's system-prompt composition re-reads every turn,
    # anchoring the codebase (or, for a `workdir`-kind pod, the working
    # directory) path where a just-reset agent will actually see it. Same
    # reachable-root rule as SOUL.md above -- this file is what a just-reset
    # agent trusts about where to `cd`.
    _mem.seed_contract(ws, project=project, codebase=told_root, stack=stack, work_dir=work_dir)

    # Keep pod-member identity docket-owned: quarantine any self-authoring
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
        meta["worktreeBranch"] = worktree_branch(project, member.member_id)
    # Only stamped when this member was provisioned through a blueprint — a
    # bare `provision_members(...)` call (every existing test, and any future
    # non-blueprint caller) leaves meta exactly as before.
    if blueprint_name:
        meta["blueprint"] = blueprint_name
    if work_dir:
        meta["workspaceKind"] = "workdir"
        meta["workDir"] = work_dir
    if budget_usd is not None and member.role == "lead":
        meta["budgetUsd"] = str(budget_usd)
    meta_file = ws / _cfg.META_FILE
    _store.write_json(meta_file, meta)

    # Text files inherit the operator's umask when written above. Docket's
    # workspace contract is stricter (0700 directories, 0600 managed files),
    # so enforce it explicitly after the atomic metadata writer has also
    # created its sibling lock file. The Implementer's ``worktree/`` is a Git
    # checkout, not managed prompt state; never recurse into it or strip
    # repository-owned executable bits.
    for path in ws.iterdir():
        if path.name == "worktree" or path.is_symlink():
            continue
        with contextlib.suppress(OSError):
            path.chmod(0o700 if path.is_dir() else 0o600)
        if path.name == "memory" and path.is_dir():
            for memory_path in path.rglob("*"):
                if memory_path.is_symlink():
                    continue
                with contextlib.suppress(OSError):
                    memory_path.chmod(0o700 if memory_path.is_dir() else 0o600)


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
) -> tuple[bool, str, str]:
    """Create one pod member's workspace + meta and register it in the fleet registry.

    Returns ``(ok, message, worktree_fallback_reason)`` — the caller renders
    ``worktree_fallback_reason`` (never empty except on the happy path with no
    fallback) rather than this module printing it directly.

    Does NOT restart the gateway — the caller batches one restart per command.
    For repo pods, Implementers get a git worktree on a dedicated branch.
    Falls back to the flat docket workspace if git is unavailable or the
    codebase is not a git repo. ``verify_cmd`` (Implementer only) is the
    mechanical gate `dispatch.py` runs after this member's hop.

    ``work_dir``/``blueprint_name``/``budget_usd``: a `workdir`-kind pod
    blueprint's shared working directory, the name of the blueprint that
    provisioned this member, and a default per-pod budget cap applied to the
    Lead only — all no-ops (and no new meta keys) when unset, which is every
    non-blueprint caller.
    """
    worktree_dir, fallback_reason = provision_worktree(member, project, codebase)
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
        work_dir=work_dir,
        blueprint_name=blueprint_name,
        budget_usd=budget_usd,
    )
    # Registration is fleet.json only -- there is no daemon to register with
    # (see cli/_agents.py's run_add for the identical reasoning).
    _fleet.add_agent(member.member_id, member.model, member.session_key, project_key)
    return (True, "", fallback_reason)


def allocate_pod_resources(project: str) -> tuple[int, int, str]:
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

    Called by pod teardown paths (docket delete / docket pod remove last-implementer
    / a `provision_pod`/`provision_members` rollback). Idempotent: safe to call
    even if no resources were allocated.
    """
    table = _store.read_json(_cfg.PORT_ALLOC_FILE)
    if table:
        updated = _res.free_pod_ports(project, table)
        _store.write_json(_cfg.PORT_ALLOC_FILE, updated)
    # The whole directory is Docket-owned. Removing only ``.scratch`` left
    # empty pod ids behind forever and leaked an auto-provisioned ``workdir``.
    pod_runtime = _cfg.PODS_DIR / project
    if pod_runtime.is_dir():
        shutil.rmtree(pod_runtime, ignore_errors=True)


def purge_pod_history(project: str, member_ids: list[str]) -> None:
    """Remove durable sessions and traces owned by a deleted pod.

    Session directory names are percent-encoded opaque keys. A pod can own
    project-wide keys (``agent:<project>:...``) and step-scoped member keys
    (``agent:<member>:<project>:...``), so both exact prefixes are removed.
    The audit log is deliberately untouched: deletion must leave evidence.
    """
    prefixes = (f"agent:{project}:", *(f"agent:{member_id}:" for member_id in member_ids))
    if _cfg.SESSIONS_DIR.is_dir():
        for entry in _cfg.SESSIONS_DIR.iterdir():
            if not entry.is_dir() or not _url_unquote(entry.name).startswith(prefixes):
                continue
            shutil.rmtree(entry, ignore_errors=True)

    for trace_owner in (project, *member_ids):
        trace_dir = _cfg.TRACES_DIR / trace_owner
        if trace_dir.is_dir():
            shutil.rmtree(trace_dir, ignore_errors=True)


def teardown_member(member_id: str) -> tuple[bool, str]:
    """Remove one pod member: fleet registration + workspace.

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

    # No daemon to unregister from -- fleet.json only.
    with contextlib.suppress(Exception):
        _fleet.remove_agent(member_id)
    if ws.is_dir():
        shutil.rmtree(ws, ignore_errors=True)
    return (True, "")


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
) -> list[ProvisionedMember]:
    """Provision a fresh pod's members from an already-resolved role list.

    The blueprint-agnostic primitive: given a roster, allocate pod-level
    runtime resources (port range + scratch dir, only when the roster
    contains an Implementer) and provision each member in order (Lead
    first). ``verify_cmd`` (validated by the caller), when set, is applied to
    Implementer members only.

    Raises ``PodProvisionError`` if any member fails to provision — with
    every member already created during *this* call, and any pod-level
    resources allocated for it, rolled back first (see module docstring).
    """
    role_models, _, _ = _mp.load_registry()
    members = pod.plan_pod(project, roles, project_key=project_key, role_models=role_models)

    allocated_resources = "implementer" in roles
    if allocated_resources:
        port_start, port_count, scratch = allocate_pod_resources(project)
    else:
        port_start, port_count, scratch = 0, 0, ""

    created: list[ProvisionedMember] = []
    try:
        for m in members:
            member_verify_cmd = verify_cmd if (verify_cmd and m.role == "implementer") else ""
            ok, msg, fallback = provision_member(
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
                    worktree_fallback_reason=fallback,
                )
            )
    except Exception as exc:
        # Roll back every member created during THIS call, plus any pod-level
        # resources allocated for it -- see module docstring for why this must
        # be unconditional rather than best-effort.
        for cm in created:
            with contextlib.suppress(Exception):
                teardown_member(cm.member_id)
        if allocated_resources:
            with contextlib.suppress(Exception):
                free_pod_resources(project)
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

    The one code path both ``docket add`` (interactive and ``--from``) and
    ``POST /pods`` call — see module docstring. ``location`` is interpreted
    per the blueprint's ``workspace_kind``: a `codebase` blueprint (e.g.
    `software`) treats it as the pod's codebase path; a `workdir` blueprint
    treats it as the pod's shared working directory, auto-provisioning one
    under ``config.pod_work_dir(project)`` (0700) when ``location`` is empty.

    ``roles``, when given, overrides the blueprint's own roster (e.g.
    `docket add`'s ``--pod full``/``--with`` flags, or `POST /pods`'s ``pod``
    field, extending `software`'s lean default) while still applying the
    blueprint's workspace kind, default budget, and name stamp.

    ``budget_usd``, when given, overrides the blueprint's own default budget
    cap (applied to the Lead only). ``verify_cmd``, when given, is validated
    (``VerifyCmdError``) and applied to Implementer member(s) at creation time
    — the same ``provision_member``/``_write_member_workspace`` parameter
    ``docket pod <p> add --verify``/``set-verify`` already use post-hoc,
    threaded through initial provisioning instead. ``source`` is the
    ``agent.add`` audit entry's ``source=`` field (``"interactive"``,
    ``"declarative"``, or ``"http"``).

    Raises:
      ``PodAlreadyExistsError`` -- ``project`` already has a registered pod
        member. Checked first, before anything (including the blueprint name)
        is resolved.
      ``core.blueprints.BlueprintError`` -- unknown blueprint name.
      ``VerifyCmdError`` -- ``verify_cmd`` fails validation.
      ``PodProvisionError`` -- a member failed to provision after rollback.
    """
    if pod_member_ids(project):
        raise PodAlreadyExistsError(project)

    blueprint = _bp.get_blueprint(blueprint_name)
    roster = roles if roles is not None else blueprint.roles

    if verify_cmd:
        verify_cmd = validate_verify_cmd(verify_cmd)

    codebase = ""
    work_dir = ""
    if blueprint.workspace_kind == "codebase":
        codebase = location
    else:
        work_dir = location or str(_cfg.pod_work_dir(project))
        Path(work_dir).mkdir(parents=True, exist_ok=True)
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
    )

    audit_log(
        "agent.add",
        f"{project} blueprint={blueprint.name} "
        f"pod=({','.join(m.role for m in created)}) source={source}",
    )
    return PodProvisionResult(project=project, blueprint=blueprint.name, members=created)
