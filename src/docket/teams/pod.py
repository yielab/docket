"""Pod composition model: the set of project-scoped agents making up one project. Composition
logic — the CLI (`docket init`/`docket pod`) turns a `PodPlan` into registered agents; this
module only decides what a pod contains and how members are named. Default pod is
**lean** (Lead + Implementer); Reviewer, Tester, or extra Implementers are added later, and a
duplicated role gets an indexed member id (``<project>-implementer``, ``...-implementer-2``).
The set of valid pod roles is not a hardcoded 4-tuple: ``normalize_role``/``member_id``/
``pod_of``/``members_of`` all resolve against ``teams/roles.py``'s registry (built-in
four + starter library + any user-defined archetype), so a fifth role is data, never a new
hardcoded string. ``_role_names()`` reads that registry fresh on every call. ``pod_of`` is the
one function here with I/O — it reads a member's recorded meta via `teams/fleet.py`'s
``meta_get`` before falling back to id-string parsing; see its own docstring."""

from __future__ import annotations

import re as _re
from dataclasses import dataclass
from pathlib import Path

from docket.kernel.errors import DispatchError, InvalidInput
from docket.kernel.home import current_home
from docket.teams import fleet as _fleet
from docket.teams import model_selection as _mp
from docket.teams import pod as _pod
from docket.teams import roles as _archetypes

DEFAULT_POD_ROLES: tuple[str, ...] = ("lead", "implementer")
FULL_POD_ROLES: tuple[str, ...] = ("lead", "implementer", "reviewer", "tester")

# At most one Lead per pod — a pod has a single orchestrator. Not part of the
# archetype schema (that field list has no "singleton" concept) — this is a
# pod-composition rule specific to the Lead role, unaffected by which roles
# the archetype registry knows about.
_SINGLETON_POD_ROLES: frozenset[str] = frozenset({"lead"})


def _role_names(project: str = "") -> tuple[str, ...]:
    """Live set of valid pod role names: built-ins + starter library + user overlay +,
    when *project* is given, that pod's own overlay too. Not cached — always current."""
    return _archetypes.load_registry(project).role_names()


class PodError(InvalidInput):
    """Invalid pod operation (unknown role, duplicate singleton, …)."""


@dataclass(frozen=True)
class PodMember:
    """One agent in a pod, fully resolved and ready to provision."""

    project: str
    role: str
    index: int  # 1-based; 1 → bare id, ≥2 → suffixed id
    member_id: str
    model: str
    session_key: str


def normalize_role(role: str, project: str = "") -> str:
    """Map user input to a canonical pod role. Validates against the live archetype registry, including *project*'s own overlay when given —
    not a hardcoded list, so any registered archetype name is accepted."""
    r = role.strip().lower()
    valid = _role_names(project)
    if r not in valid:
        raise PodError(f"unknown pod role {role!r}; valid roles: {', '.join(valid)}")
    return r


def member_id(project: str, role: str, index: int = 1) -> str:
    """``<project>-<role>`` for the first of a role, ``…-<role>-<index>`` after."""
    base = f"{project}-{role}"
    return base if index <= 1 else f"{base}-{index}"


def pod_prefix(project: str) -> str:
    """The id prefix every member of a pod shares."""
    return f"{project}-"


def session_key(project: str, project_key: str = "default") -> str:
    """Return the base scope key written to pod-member metadata, kept for
    metadata compatibility. Pod-dispatch runtime history does not use it — it derives a
    task/step key per turn via ``hops.application.runner.step_session_key`` instead."""
    return f"agent:{project}:{project_key}"


def pod_of(member_id: str) -> str | None:
    """Project a member id belongs to, or ``None`` if it isn't a pod member. Meta-first (see
    below); reverses ``member_id`` in the fallback: ``demo-lead`` -> ``demo``,
    ``demo-implementer-2`` -> ``demo``, ``my-shop-reviewer`` -> ``my-shop``."""
    # The member's own recorded meta (written at provisioning, teams/pod_provisioning.py) is
    # authoritative -- read it before ever guessing from the id string. The string-parsing
    # fallback below rpartitions on "-" and treats the last segment that matches a *registered
    # role name* as the role, which mis-splits a custom role whose own name ends in another
    # registered role's name (e.g. `security-reviewer`'s member id `proj-security-reviewer`
    # would otherwise parse as role `reviewer` of project `proj-security`). A member with no
    # meta, or whose meta carries no `pod` field (a plain non-pod agent), falls back to
    # that string parsing unchanged.
    recorded = _fleet.meta_get(member_id, "pod", "")
    if recorded:
        return recorded
    roles = _role_names()
    head, sep, tail = member_id.rpartition("-")
    if sep and tail.isdigit():  # …-<role>-<index>
        proj, sep2, role = head.rpartition("-")
        if sep2 and role in roles:
            return proj
        return None
    if sep and tail in roles:  # …-<role>
        return head
    return None


def members_of(all_agent_ids: list[str], project: str) -> list[tuple[str, str, int]]:
    """Pod members among ``all_agent_ids``, as ``(member_id, role, index)``, sorted by role
    order (lead first) then index so a pod always lists its Lead before its workers; ids that
    don't belong to the pod are ignored."""
    found: list[tuple[str, str, int]] = []
    for mid in all_agent_ids:
        parsed = parse_member_id(mid, project)
        if parsed is not None:
            found.append((mid, parsed[0], parsed[1]))
    roles = _role_names(project)
    role_rank = {role: i for i, role in enumerate(roles)}
    found.sort(key=lambda t: (role_rank.get(t[1], len(roles)), t[2]))
    return found


def next_index(existing_member_ids: list[str], project: str, role: str) -> int:
    """Lowest free 1-based index for a new member of ``role`` in the pod."""
    taken = {
        m_index
        for mid in existing_member_ids
        if (parsed := parse_member_id(mid, project)) is not None
        and parsed[0] == role
        and (m_index := parsed[1]) > 0
    }
    index = 1
    while index in taken:
        index += 1
    return index


def parse_member_id(member_id_str: str, project: str) -> tuple[str, int] | None:
    """Split a member id into ``(role, index)`` if it belongs to ``project``; ``None`` when the
    id is not a member of this project's pod."""
    prefix = pod_prefix(project)
    if not member_id_str.startswith(prefix):
        return None
    rest = member_id_str[len(prefix) :]
    if not rest:
        return None
    # rest is "<role>" or "<role>-<index>"
    head, sep, tail = rest.rpartition("-")
    if sep and tail.isdigit():
        role, index = head, int(tail)
    else:
        role, index = rest, 1
    if role not in _role_names(project) or index < 1:
        return None
    return role, index


def resolve_member(
    project: str,
    role: str,
    index: int = 1,
    *,
    project_key: str = "default",
    role_models: dict[str, str] | None = None,
) -> PodMember:
    """Resolve one pod member: canonical role, id, policy model, session key."""
    canon = normalize_role(role, project)
    arch = _archetypes.load_registry(project).get(canon)
    assert arch is not None  # normalize_role() already validated membership
    model = _mp.resolve_role_model(arch.name, role_models, project=project)
    return PodMember(
        project=project,
        role=canon,
        index=index,
        member_id=member_id(project, canon, index),
        model=model,
        session_key=session_key(project, project_key),
    )


def plan_pod(
    project: str,
    roles: tuple[str, ...] = DEFAULT_POD_ROLES,
    *,
    project_key: str = "default",
    role_models: dict[str, str] | None = None,
) -> list[PodMember]:
    """Resolve a fresh pod's members from a role list (default = lean pod). Duplicate
    non-singleton roles are indexed in order of appearance; a second Lead is rejected (a pod
    has one orchestrator)."""
    members: list[PodMember] = []
    counts: dict[str, int] = {}
    for role in roles:
        canon = normalize_role(role, project)
        counts[canon] = counts.get(canon, 0) + 1
        if canon in _SINGLETON_POD_ROLES and counts[canon] > 1:
            raise PodError(f"a pod may have only one {canon}")
        members.append(
            resolve_member(
                project,
                canon,
                counts[canon],
                project_key=project_key,
                role_models=role_models,
            )
        )
    return members


def plan_added_member(
    project: str,
    role: str,
    existing_member_ids: list[str],
    *,
    project_key: str = "default",
    role_models: dict[str, str] | None = None,
) -> PodMember:
    """Resolve a member being added to an existing pod (handles duplicates); rejects adding a
    second Lead."""
    canon = normalize_role(role, project)
    if canon in _SINGLETON_POD_ROLES:
        already = any(
            (p := parse_member_id(mid, project)) is not None and p[0] == canon
            for mid in existing_member_ids
        )
        if already:
            raise PodError(f"a pod may have only one {canon}")
    index = next_index(existing_member_ids, project, canon)
    return resolve_member(
        project,
        canon,
        index,
        project_key=project_key,
        role_models=role_models,
    )


def resolve_member_cwd(member_id: str, task_worktree: str = "", codebase: str = "") -> str:
    """Resolve the real working directory for a pod member's mechanical operations. Preference
    order: the running task's own git **worktree** (recorded at claim) -> the pod's shared
    **codebase** root -> the member's own docket **workspace** dir. Both the verification gate
    (``hops/gates/post_hop.py``) and the TOOLS.md generator (``interfaces/cli/commands/pod.py``) resolve through this
    one helper so they can never disagree about which tree an implementer's work is checked
    against."""
    if task_worktree:
        return task_worktree
    if codebase:
        return codebase
    return str(current_home().workspace_dir(member_id))


# The docket-owned copy of a pod's bound pipeline file lives at this fixed name in the
# Lead's own workspace -- alongside SOUL.md/AGENTS.md/HEARTBEAT.md -- never at the
# operator's original path, which can drift or disappear. ``PodSettings.pipeline`` stores
# only that copy's sha256 hex digest, so a hand-edited or stale copy is detected rather
# than silently trusted (see hops/application/steps.py's ``_blueprint_pipeline``).
BOUND_PIPELINE_FILENAME = "PIPELINE.yaml"


def bound_pipeline_path(project: str) -> Path:
    """Where a pod's bound pipeline copy lives, if ``PodSettings.pipeline`` is set."""
    return current_home().workspace_dir(member_id(project, "lead")) / BOUND_PIPELINE_FILENAME


def pod_full_roster(project: str) -> dict[str, str]:
    """Every role this pod has, first member per role (``role -> member_id``). Unlike
    :func:`pod_pipeline` (fixed to ``PIPELINE_ORDER``), this covers every role name so a
    custom :class:`~docket.pipeline.domain.spec.PipelineSpec` can target a role outside the default four."""
    all_ids = [a.id for a in _fleet.list_agents()]
    by_role: dict[str, str] = {}
    for mid, role, _idx in _pod.members_of(all_ids, project):
        by_role.setdefault(role, mid)
    return by_role


# Only roles the pod actually has run — lean pod (lead + implementer) = 2 hops; full pod = 4.
PIPELINE_ORDER: tuple[str, ...] = ("lead", "implementer", "reviewer", "tester")


def pod_pipeline(project: str) -> list[tuple[str, str]]:
    """Present pod roles in pipeline order, as ``(role, member_id)``; raises DispatchError
    with no Lead. Duplicate implementers collapse to the first (one doer per role).
    """
    all_ids = [a.id for a in _fleet.list_agents()]
    members = _pod.members_of(all_ids, project)
    if not members:
        raise DispatchError(f"no pod found for '{project}'")
    by_role: dict[str, str] = {}
    for mid, role, _idx in members:
        by_role.setdefault(role, mid)  # first member of each role wins
    if "lead" not in by_role:
        raise DispatchError(f"pod '{project}' has no lead — cannot dispatch")
    return [(role, by_role[role]) for role in PIPELINE_ORDER if role in by_role]


TASK_PIPELINE_NAME = _re.compile(r"^[a-z0-9][a-z0-9._-]*$")
