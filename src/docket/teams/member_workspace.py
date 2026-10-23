from __future__ import annotations

import contextlib
import difflib
from dataclasses import dataclass, field

from docket.agent import memory as _mem
from docket.kernel import clock as _clock
from docket.kernel.home import current_home
from docket.platform import read_json, write_json
from docket.teams import fleet as _fleet
from docket.teams import pod
from docket.teams import role_schema as _role_schema
from docket.teams import roles as _arch
from docket.teams.task_worktrees import TASK_WORKTREES_DIRNAME

# Bump when the pod-member templates change (doctor flags older members).
# v3: built-in/starter AGENTS.md templates no longer instruct a private
# HEARTBEAT.md write -- it contradicted the live runtime contract (see
# teams/roles.py's Red Lines templates).
# v4: SOUL.md names no path, AGENTS.md carries the shared method and no private-file
# reads, and no template asks for a completion promise.
POD_TEMPLATE_VERSION = 5


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

    Guaranteed set: role-archetypes.spec.md; work_dir excludes codebase (pod-blueprints.spec.md)."""
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
        "workDir": work_dir or codebase or str(current_home().workspace_dir(member.member_id)),
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

    No role-specific branching (role-archetypes.spec.md)."""
    arch = _arch.load_registry(project).get(member.role)
    if arch is None:
        raise pod.PodError(f"no archetype registered for role {member.role!r}")
    variables = _render_context(member, project, codebase, stack, description, work_dir=work_dir)
    return _role_schema.render(arch.soul_template, variables)


def _member_tools(
    project: str,
    role: str,
    codebase: str,
    port_range_start: int,
    port_range_count: int,
    scratch_dir: str,
    verify_cmd: str = "",
) -> str:
    """TOOLS.md for an Implementer -- includes allocated runtime resources.

    ``verify_cmd`` (set) is the post-hop gate (``hops/gates/post_hop.py``) the agent must pass."""
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

    Byte-identical (role-archetypes.spec.md); section-projection rule: agent-loop.spec.md req 30."""
    arch = _arch.load_registry(project).get(member.role)
    if arch is None:
        raise pod.PodError(f"no archetype registered for role {member.role!r}")
    variables = _render_context(member, project, "", "", "")
    return _role_schema.render(arch.agents_template, variables)


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
    verify_cmd: str = "",
    work_dir: str = "",
    blueprint_name: str = "",
    budget_usd: float | None = None,
) -> None:
    ws = current_home().projects_dir / member.member_id
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "memory").mkdir(exist_ok=True)
    told_root = codebase
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

    with contextlib.suppress(OSError):
        ws.chmod(0o700)

    meta: dict[str, object] = {
        "kind": "project",
        "scope": "project",
        "role": member.role,
        "pod": project,
        "name": f"{project} {member.role}",
        "codebase": codebase,
        "stack": stack,
        "model": member.model,
        "description": description,
        "created": _clock.iso(),
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
    # Only stamped when this member was provisioned through a blueprint — a
    # bare `provision_members(...)` call (every existing test, and any future
    # non-blueprint caller) leaves meta exactly as before.
    if blueprint_name:
        meta["blueprint"] = blueprint_name
    if work_dir:
        meta["workspaceKind"] = "workdir"
        meta["workDir"] = work_dir
    if budget_usd is not None and member.role == "lead":
        meta["budgetUsd"] = float(budget_usd)
    meta_file = ws / current_home().meta_file
    write_json(meta_file, meta)

    # Text files inherit the operator's umask when written above. Docket's
    # workspace contract is stricter (0700 directories, 0600 managed files),
    # so enforce it explicitly after the atomic metadata writer has also
    # created its sibling lock file. The Implementer's ``tasks/`` holds Git
    # checkouts, not managed prompt state; never recurse into it or strip
    # repository-owned executable bits.
    for path in ws.iterdir():
        if path.name == TASK_WORKTREES_DIRNAME or path.is_symlink():
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
) -> tuple[bool, str]:
    """Create one pod member's workspace + meta and register it in the fleet registry.

    Returns ``(ok, message)``. Does not restart the gateway -- the caller batches one restart
    per command. No worktree is made here: dispatch creates one per task at claim.

    ``work_dir``/``blueprint_name``/``budget_usd`` are all no-ops (no new meta
    keys) when unset, which is every non-blueprint caller."""
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
        verify_cmd=verify_cmd,
        work_dir=work_dir,
        blueprint_name=blueprint_name,
        budget_usd=budget_usd,
    )
    # Registration is fleet.json only -- there is no daemon to register with
    # (see ``interfaces/cli/commands/pod_members.py``'s ``add_members``).
    _fleet.add_agent(member.member_id)
    return (True, "")


# ── re-rendering an existing member ─────────────────────────────────────────
#
# A pod member's SOUL.md/AGENTS.md/TOOLS.md are generated wholesale from its
# archetype + stored metadata and may be freely overwritten -- an operator's
# own notes belong in INSTRUCTIONS.md (agent/identity.py), which nothing here
# ever reads, writes, or diffs.


def _member_from_meta(member_id: str, meta: dict[str, object]) -> pod.PodMember:
    """A minimal ``PodMember`` reconstructed from stored metadata, sufficient for
    ``_member_soul``/``_member_agents`` -- ``index``/``model`` are unused by either."""
    return pod.PodMember(
        project=str(meta.get("pod", "")),
        role=str(meta.get("role", "")),
        index=1,
        member_id=member_id,
        model=str(meta.get("model", "")),
        session_key=str(meta.get("sessionKey", "")),
    )


def rendered_member_files(member_id: str) -> dict[str, str]:
    """The SOUL.md/AGENTS.md/(TOOLS.md, when applicable) text the current archetype
    and *member_id*'s stored metadata would produce -- read-only, writes nothing.
    Empty when the id has no pod metadata."""
    meta = read_json(current_home().meta_path(member_id))
    project = str(meta.get("pod", ""))
    role = str(meta.get("role", ""))
    if not meta or not project or not role:
        return {}
    member = _member_from_meta(member_id, meta)
    codebase = str(meta.get("codebase", ""))
    stack = str(meta.get("stack", ""))
    description = str(meta.get("description", ""))
    work_dir = str(meta.get("workDir", ""))
    files = {
        "SOUL.md": _member_soul(member, project, codebase, stack, description, work_dir=work_dir),
        "AGENTS.md": _member_agents(member, project),
    }
    verify_cmd = str(meta.get("verifyCmd", ""))
    port_start_s = str(meta.get("portRangeStart", ""))
    scratch = str(meta.get("scratchDir", ""))
    if role == "implementer" and ((port_start_s and scratch) or verify_cmd):
        files["TOOLS.md"] = _member_tools(
            project,
            role,
            codebase,
            int(port_start_s) if port_start_s else 0,
            int(meta.get("portRangeCount", "") or 0),
            scratch,
            verify_cmd,
        )
    return files


@dataclass(frozen=True)
class MemberSyncStatus:
    """One pod member's re-render drift: whether its managed files still match the
    current archetype + metadata, and the per-file unified diff when they do not."""

    member_id: str
    stale: bool
    stored_template_version: str
    diffs: dict[str, str] = field(default_factory=dict)


def member_sync_status(member_id: str) -> MemberSyncStatus | None:
    """Compare *member_id*'s on-disk managed files against what the current archetype
    and its own stored metadata would render right now. ``None`` when *member_id* is
    not a pod member with a workspace (nothing to compare)."""
    rendered = rendered_member_files(member_id)
    if not rendered:
        return None
    meta = read_json(current_home().meta_path(member_id))
    ws = current_home().projects_dir / member_id
    diffs: dict[str, str] = {}
    for name, new_text in rendered.items():
        path = ws / name
        current = path.read_text(encoding="utf-8") if path.is_file() else ""
        if current == new_text:
            continue
        diffs[name] = "".join(
            difflib.unified_diff(
                current.splitlines(keepends=True),
                new_text.splitlines(keepends=True),
                fromfile=f"{name} (current)",
                tofile=f"{name} (rendered)",
            )
        )
    stored_tv = str(meta.get("templateVersion", ""))
    stale = bool(diffs) or stored_tv != str(POD_TEMPLATE_VERSION)
    return MemberSyncStatus(member_id, stale, stored_tv, diffs)


def resync_member(member_id: str) -> list[str]:
    """Rewrite *member_id*'s stale files from the current archetype + metadata and
    stamp ``POD_TEMPLATE_VERSION``; never touches ``INSTRUCTIONS.md`` (operator-owned).
    Returns the files rewritten -- an already-current member writes nothing."""
    status = member_sync_status(member_id)
    if status is None or not status.stale:
        return []
    rendered = rendered_member_files(member_id)
    ws = current_home().projects_dir / member_id
    written: list[str] = []
    for name in status.diffs:
        path = ws / name
        path.write_text(rendered[name], encoding="utf-8")
        with contextlib.suppress(OSError):
            path.chmod(0o600)
        written.append(name)
    _fleet.meta_set(member_id, "templateVersion", str(POD_TEMPLATE_VERSION))
    return written
