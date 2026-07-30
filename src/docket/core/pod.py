"""Pod composition model.

A *pod* is the set of project-scoped agents that make up one project. Pure logic
only — no I/O. The CLI (`docket add` / `docket pod`) and the ACL turn a `PodPlan`
into registered agents; this module just decides *what* a pod contains and how
its members are named.

Default pod is **lean**: a Lead + an Implementer (2 agents).
Reviewer, Tester, or **additional Implementers** are added later.
A role may be **duplicated** (e.g. two Implementers); duplicates get an
indexed member id (``<project>-implementer``, ``<project>-implementer-2``).

ROADMAP Phase 16 W-6: the set of valid pod roles is no longer a hardcoded
4-tuple — ``normalize_role``/``member_id``/``pod_of``/``members_of`` all
resolve against ``core/archetypes.py``'s registry (built-in four roles +
starter library + any user-defined archetype), so a fifth role is data, never
a new hardcoded string here. ``POD_ROLES``/``POD_ROLE_POLICY`` are kept as
module attributes for backward compatibility (via ``__getattr__`` below) but
are now *computed* from the live registry on every access rather than
literal dict/tuple constants — see that function's docstring.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import docket.config as _cfg
from docket.core import archetypes as _archetypes
from docket.core import models_policy as _mp

DEFAULT_POD_ROLES: tuple[str, ...] = ("lead", "implementer")
FULL_POD_ROLES: tuple[str, ...] = ("lead", "implementer", "reviewer", "tester")

# At most one Lead per pod — a pod has a single orchestrator. Not part of the
# archetype schema (W-6's field list has no "singleton" concept) — this is a
# pod-composition rule specific to the Lead role, unaffected by which roles
# the archetype registry knows about.
_SINGLETON_POD_ROLES: frozenset[str] = frozenset({"lead"})


def _role_names() -> tuple[str, ...]:
    """Live set of valid pod role names: built-ins + starter library + user overlay.

    Not cached — re-reads the archetype registry every call (mirrors
    ``models_policy.load_registry``'s own no-caching pattern), so a freshly
    added user archetype (or a test that monkeypatches
    ``cfg.ARCHETYPE_REGISTRY_FILE``) is always picked up without needing to
    reload this module.
    """
    return _archetypes.load_registry().role_names()


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
    """Map user input to a canonical pod role (accepts the ``programmer`` alias).

    Validates against the live archetype registry (``core/archetypes.py``),
    not a hardcoded list — any built-in, starter-library, or user-defined
    archetype name is accepted.
    """
    r = role.strip().lower()
    if r == "programmer":
        r = "implementer"
    valid = _role_names()
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
    """Pod members share the project's session-key namespace."""
    return f"agent:{project}:{project_key}"


def pod_of(member_id: str) -> str | None:
    """Project a member id belongs to, or ``None`` if it isn't a pod member.

    Reverses ``member_id``: ``demo-lead`` → ``demo``; ``demo-implementer-2`` →
    ``demo``; ``my-shop-reviewer`` → ``my-shop``. A plain id with no pod-role
    suffix (e.g. a legacy single agent ``myshop`` or ``my-api``) → ``None``.
    """
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
    """Pod members among ``all_agent_ids``, as ``(member_id, role, index)``.

    Sorted by role order (lead first) then index, so a pod always lists its Lead
    before its workers. Ids that don't belong to the pod are ignored.
    """
    found: list[tuple[str, str, int]] = []
    for mid in all_agent_ids:
        parsed = parse_member_id(mid, project)
        if parsed is not None:
            found.append((mid, parsed[0], parsed[1]))
    roles = _role_names()
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
    if role not in _role_names() or index < 1:
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
    arch = _archetypes.load_registry().get(canon)
    assert arch is not None  # normalize_role() already validated membership
    model = _mp.resolve_role_model(arch.resolved_policy_role, role_models)
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


def policy_role_for(role: str) -> str:
    """The role→model policy key ``role``'s archetype resolves through.

    A typed counterpart to ``POD_ROLE_POLICY.get(role, role)`` (see that
    dict's ``__getattr__`` docstring) that ``models_policy.agent_role()``
    calls directly — avoids round-tripping through the dynamically-typed
    module attribute at a call site that needs a concrete ``str`` back.
    """
    arch = _archetypes.load_registry().get(role)
    return arch.resolved_policy_role if arch is not None else role


def resolve_member_cwd(member_id: str, worktree_dir: str = "", codebase: str = "") -> str:
    """Resolve the real working directory for a pod member's mechanical operations.

    Preference order: the member's own git **worktree** (an isolated checkout set
    at provisioning time — see ``cli/_pod.py``'s ``_provision_worktree``, which
    writes ``worktreeDir`` into the member's meta) → the pod's shared **codebase**
    root → the member's own docket **workspace** dir (``config.workspace_dir``).

    Both the mechanical verification gate (``core/dispatch.py``) and the TOOLS.md
    generator (``cli/_pod.py``'s ``_regenerate_member_tools``) resolve through this
    one helper so they can never disagree again about which tree an implementer's
    work is actually checked against — a worktree-pod implementer's changes used
    to be verified against the shared repo root instead of its own worktree
    (Phase 14 R-6).
    """
    if worktree_dir:
        return worktree_dir
    if codebase:
        return codebase
    return str(_cfg.workspace_dir(member_id))


def __getattr__(name: str) -> Any:
    """Backward-compatible ``POD_ROLES``/``POD_ROLE_POLICY`` module attributes (PEP 562).

    Both used to be literal module-level constants; W-6 replaced their source
    of truth with the archetype registry, so any external code (or a future
    caller) that still does ``pod.POD_ROLES`` / ``pod.POD_ROLE_POLICY`` keeps
    working, now backed by a live registry read instead of a hardcoded 4-tuple
    (this also fires for ``from docket.core.pod import POD_ROLES`` — PEP 562
    module ``__getattr__`` covers both attribute-access forms).
    """
    if name == "POD_ROLES":
        return _role_names()
    if name == "POD_ROLE_POLICY":
        return {n: a.resolved_policy_role for n, a in _archetypes.load_registry().items()}
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
