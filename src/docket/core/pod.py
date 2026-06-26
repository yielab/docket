"""Pod composition model.

A *pod* is the set of project-scoped agents that make up one project. Pure logic
only — no I/O. The CLI (`docket add` / `docket pod`) and the ACL turn a `PodPlan`
into registered agents; this module just decides *what* a pod contains and how
its members are named.

Default pod is **lean**: a Lead + an Implementer (2 agents).
Reviewer, Tester, or **additional Implementers** are added later.
A role may be **duplicated** (e.g. two Implementers); duplicates get an
indexed member id (``<project>-implementer``, ``<project>-implementer-2``).
"""

from __future__ import annotations

from dataclasses import dataclass

from docket.core import models_policy as _mp

# The roles a pod member can take. Distinct from the org specialist roles.
POD_ROLES: tuple[str, ...] = ("lead", "implementer", "reviewer", "tester")

DEFAULT_POD_ROLES: tuple[str, ...] = ("lead", "implementer")
FULL_POD_ROLES: tuple[str, ...] = ("lead", "implementer", "reviewer", "tester")

# Pod role → role→model policy key. Lead coordinates (cheap), Implementer writes
# code (strong); reviewer/tester map to their own policy entries. This is why a
# Lead lands on the cheap coordination model and an Implementer on the strong one.
POD_ROLE_POLICY: dict[str, str] = {
    "lead": "manager",
    "implementer": "programmer",
    "reviewer": "reviewer",
    "tester": "tester",
}

# At most one Lead per pod — a pod has a single orchestrator.
_SINGLETON_POD_ROLES: frozenset[str] = frozenset({"lead"})


class PodError(ValueError):
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


def normalize_role(role: str) -> str:
    """Map user input to a canonical pod role (accepts the ``programmer`` alias)."""
    r = role.strip().lower()
    if r == "programmer":
        r = "implementer"
    if r not in POD_ROLES:
        raise PodError(f"unknown pod role {role!r}; valid roles: {', '.join(POD_ROLES)}")
    return r


def member_id(project: str, role: str, index: int = 1) -> str:
    """``<project>-<role>`` for the first of a role, ``…-<role>-<index>`` after."""
    base = f"{project}-{role}"
    return base if index <= 1 else f"{base}-{index}"


def pod_prefix(project: str) -> str:
    """The id prefix every member of a pod shares."""
    return f"{project}-"


def session_key(project: str, project_key: str = "default") -> str:
    """Pod members share the project's session-key namespace."""
    return f"agent:{project}:{project_key}"


def pod_of(member_id: str) -> str | None:
    """Project a member id belongs to, or ``None`` if it isn't a pod member.

    Reverses ``member_id``: ``demo-lead`` → ``demo``; ``demo-implementer-2`` →
    ``demo``; ``my-shop-reviewer`` → ``my-shop``. A plain id with no pod-role
    suffix (e.g. a legacy single agent ``myshop`` or ``my-api``) → ``None``.
    """
    head, sep, tail = member_id.rpartition("-")
    if sep and tail.isdigit():  # …-<role>-<index>
        proj, sep2, role = head.rpartition("-")
        if sep2 and role in POD_ROLES:
            return proj
        return None
    if sep and tail in POD_ROLES:  # …-<role>
        return head
    return None


def members_of(all_agent_ids: list[str], project: str) -> list[tuple[str, str, int]]:
    """Pod members among ``all_agent_ids``, as ``(member_id, role, index)``.

    Sorted by role order (lead first) then index, so a pod always lists its Lead
    before its workers. Ids that don't belong to the pod are ignored.
    """
    found: list[tuple[str, str, int]] = []
    for mid in all_agent_ids:
        parsed = parse_member_id(mid, project)
        if parsed is not None:
            found.append((mid, parsed[0], parsed[1]))
    role_rank = {role: i for i, role in enumerate(POD_ROLES)}
    found.sort(key=lambda t: (role_rank.get(t[1], len(POD_ROLES)), t[2]))
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
    """Split a member id into ``(role, index)`` if it belongs to ``project``.

    Returns ``None`` when the id is not a member of this project's pod.
    """
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
    if role not in POD_ROLES or index < 1:
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
    canon = normalize_role(role)
    policy_role = POD_ROLE_POLICY[canon]
    model = _mp.resolve_role_model(policy_role, role_models)
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
    """Resolve a fresh pod's members from a role list (default = lean pod).

    Duplicate non-singleton roles are indexed in order of appearance. A second
    Lead is rejected (a pod has one orchestrator).
    """
    members: list[PodMember] = []
    counts: dict[str, int] = {}
    for role in roles:
        canon = normalize_role(role)
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
    """Resolve a member being added to an existing pod (handles duplicates).

    Rejects adding a second Lead.
    """
    canon = normalize_role(role)
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
