"""Pod composition model: the set of project-scoped agents making up one project. Composition
logic — the CLI (`docket add`/`docket pod`) turns a `PodPlan` into registered agents; this
module only decides what a pod contains and how members are named. Default pod is
**lean** (Lead + Implementer); Reviewer, Tester, or extra Implementers are added later, and a
duplicated role gets an indexed member id (``<project>-implementer``, ``...-implementer-2``).
The set of valid pod roles is not a hardcoded 4-tuple: ``normalize_role``/``member_id``/
``pod_of``/``members_of`` all resolve against ``core/archetypes.py``'s registry (built-in
four + starter library + any user-defined archetype), so a fifth role is data, never a new
hardcoded string. ``_role_names()`` reads that registry fresh on every call. ``pod_of`` is the
one function here with I/O — it reads a member's recorded meta via `core/fleet.py`'s
``meta_get`` before falling back to id-string parsing; see its own docstring."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic import ValidationError as _PydanticValidationError

import docket.config as _cfg
from docket.core import archetypes as _archetypes
from docket.core import fleet as _fleet
from docket.core import models_policy as _mp
from docket.core import security as _security

DEFAULT_POD_ROLES: tuple[str, ...] = ("lead", "implementer")
FULL_POD_ROLES: tuple[str, ...] = ("lead", "implementer", "reviewer", "tester")

# At most one Lead per pod — a pod has a single orchestrator. Not part of the
# archetype schema (that field list has no "singleton" concept) — this is a
# pod-composition rule specific to the Lead role, unaffected by which roles
# the archetype registry knows about.
_SINGLETON_POD_ROLES: frozenset[str] = frozenset({"lead"})


def _role_names() -> tuple[str, ...]:
    """Live set of valid pod role names: built-ins + starter library + user overlay. Not cached
    — re-reads the archetype registry every call (mirrors ``models_policy.load_registry``'s
    no-caching pattern), so a freshly added archetype is always picked up without a reload."""
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
    """Map user input to a canonical pod role (accepts the ``programmer`` alias). Validates
    against the live archetype registry (``core/archetypes.py``), not a hardcoded list, so any
    built-in, starter-library, or user-defined archetype name is accepted."""
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
    """Return the base scope key written to pod-member metadata, kept for ``docket scope`` and
    metadata compatibility. Pod-dispatch runtime history does not use it — it derives a
    task/step key per turn via ``core.dispatch.step_session_key`` instead."""
    return f"agent:{project}:{project_key}"


def pod_of(member_id: str) -> str | None:
    """Project a member id belongs to, or ``None`` if it isn't a pod member. Meta-first (see
    below); reverses ``member_id`` in the fallback: ``demo-lead`` -> ``demo``,
    ``demo-implementer-2`` -> ``demo``, ``my-shop-reviewer`` -> ``my-shop``."""
    # The member's own recorded meta (written at provisioning, core/pod_provisioning.py) is
    # authoritative -- read it before ever guessing from the id string. The string-parsing
    # fallback below rpartitions on "-" and treats the last segment that matches a *registered
    # role name* as the role, which mis-splits a custom role whose own name ends in another
    # registered role's name (e.g. `security-reviewer`'s member id `proj-security-reviewer`
    # would otherwise parse as role `reviewer` of project `proj-security`). A member with no
    # meta, or whose meta carries no `pod` field (a plain legacy/non-pod agent), falls back to
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
    """Resolve a fresh pod's members from a role list (default = lean pod). Duplicate
    non-singleton roles are indexed in order of appearance; a second Lead is rejected (a pod
    has one orchestrator)."""
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
    """Resolve a member being added to an existing pod (handles duplicates); rejects adding a
    second Lead."""
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
    """The role→model policy key ``role``'s archetype resolves through: the archetype's
    ``policyRole`` override if set (the four legacy roles), else its own name (every
    starter-library/user role); ``models_policy.agent_role()`` calls this directly."""
    arch = _archetypes.load_registry().get(role)
    return arch.resolved_policy_role if arch is not None else role


def resolve_member_cwd(member_id: str, worktree_dir: str = "", codebase: str = "") -> str:
    """Resolve the real working directory for a pod member's mechanical operations. Preference
    order: the member's own git **worktree** (set at provisioning, see ``cli/_pod.py``'s
    ``_provision_worktree``) -> the pod's shared **codebase** root -> the member's own docket
    **workspace** dir. Both the verification gate (``core/dispatch.py``) and the TOOLS.md
    generator (``cli/_pod.py``) resolve through this one helper so they can never disagree
    about which tree an implementer's work is checked against."""
    if worktree_dir:
        return worktree_dir
    if codebase:
        return codebase
    return str(_cfg.workspace_dir(member_id))


class PodSettingsError(ValueError):
    """A pod setting's value is invalid: bad type, out of range, or unknown key."""


# alias -> attribute, so the CLI and dispatch never hardcode a second copy of
# this mapping next to PodSettings.KEYS.
_SETTING_FIELD_BY_ALIAS: dict[str, str] = {
    "budgetUsd": "budget_usd",
    "maxReworkCycles": "max_rework_cycles",
    "turnTimeoutS": "turn_timeout_s",
    "verifyTimeoutS": "verify_timeout_s",
    "approvalMode": "approval_mode",
    "allowCommands": "allow_commands",
    "pipeline": "pipeline",
}

# allowCommands validation: no path segment, no shell metacharacter -- this is
# the same charset a bare basename can use, nothing that could resolve to a
# different binary or escape the allowlist check it feeds.
_INVALID_BIN_NAME_CHARS = re.compile(r"[^A-Za-z0-9_.+-]")
# Opaque/scope-changing shell names: allowlisting these would let a pod
# smuggle an arbitrary binary in behind a name docket cannot statically
# classify, the same reason classify_command keeps them off SAFE_BINS.
_OPAQUE_COMMAND_NAMES: frozenset[str] = frozenset({"eval", "exec", "source", ".", "export"})


# Typed, validated view over the pod Lead's dispatch-configuration meta keys
# (budgetUsd/maxReworkCycles/turnTimeoutS/verifyTimeoutS -- see
# specs/data/docket-meta.spec.md). A missing/blank meta key uses the field
# default below, but a *present, malformed* stored value is never silently
# replaced by it: ``load_for``/``coerce`` raise ``PodSettingsError`` naming the
# key instead, and core/dispatch.py's readers let that propagate, so a bad
# stored value refuses dispatch rather than guessing at one. A later pod
# setting (approvalMode, pipeline, allowCommands) adds a field plus a
# ``KEYS``/alias entry here, never a second reader.
class PodSettings(BaseModel):
    """One pod's dispatch-config settings, validated from the Lead's meta."""

    model_config = ConfigDict(populate_by_name=True)

    budget_usd: float = Field(0.0, alias="budgetUsd", ge=0)
    max_rework_cycles: int = Field(1, alias="maxReworkCycles", ge=0)
    turn_timeout_s: int | None = Field(None, alias="turnTimeoutS", gt=0)
    verify_timeout_s: int | None = Field(None, alias="verifyTimeoutS", gt=0)
    # Whether an unattended hop waits on an `ask` verdict (today's behavior,
    # byte-identical) or refuses it at once -- threaded into the hop's tool
    # env as DOCKET_APPROVAL_MODE (see core/dispatch.py's `_compose_hop`
    # and core/tools.py's `ToolContext.approval_mode`).
    approval_mode: Literal["wait", "refuse"] = Field("wait", alias="approvalMode")
    allow_commands: tuple[str, ...] = Field((), alias="allowCommands")
    # sha256 hex digest of the docket-owned bound-pipeline copy in the Lead's workspace
    # (``bound_pipeline_path``) -- never the operator's original file path. Set only by
    # ``docket pod <project> config set pipeline <file>``, which validates the file and
    # writes the copy before this ever gets written (see core/dispatch.py's
    # ``_blueprint_pipeline``, which verifies the copy still hashes to this value).
    pipeline: str | None = Field(None, alias="pipeline", pattern=r"^[0-9a-f]{64}$")

    # Declaration order the CLI's ``config`` subcommand, ``load_for`` and
    # ``coerce`` all iterate, instead of a second hardcoded key list.
    KEYS: ClassVar[tuple[str, ...]] = (
        "budgetUsd",
        "maxReworkCycles",
        "turnTimeoutS",
        "verifyTimeoutS",
        "approvalMode",
        "allowCommands",
        "pipeline",
    )

    @field_validator("allow_commands", mode="before")
    @classmethod
    def _parse_allow_commands(cls, value: Any) -> tuple[str, ...]:
        """Comma-separated exact binary basenames. Rejects a path segment, a shell
        metacharacter, an opaque/scope-changing name, or a high-risk-class binary;
        a name already on ``SAFE_BINS`` is accepted but dropped (redundant)."""
        if value in (None, ""):
            return ()
        tokens = list(value) if isinstance(value, (list, tuple)) else str(value).split(",")
        high_risk_bins = {b for hrc in _security.HIGH_RISK_PATTERNS for b in hrc.bins}
        kept: dict[str, None] = {}
        for raw in tokens:
            name = str(raw).strip()
            if not name:
                continue
            if _INVALID_BIN_NAME_CHARS.search(name):
                raise ValueError(f"{name!r} is not a valid binary basename")
            if name in _OPAQUE_COMMAND_NAMES:
                raise ValueError(f"{name!r} is opaque/scope-changing, cannot be allowlisted")
            if name in high_risk_bins:
                raise ValueError(f"{name!r} names a high-risk action class, cannot be allowlisted")
            if name in _security.SAFE_BINS:
                continue  # already unattended-safe -- redundant, silently dropped
            kept.setdefault(name, None)
        return tuple(kept.keys())

    @classmethod
    def _validated(cls, present: dict[str, str]) -> PodSettings:
        try:
            return cls.model_validate(present)
        except _PydanticValidationError as exc:
            first = exc.errors()[0]
            key = str(first["loc"][0]) if first["loc"] else "?"
            raise PodSettingsError(
                f"{key}: invalid stored value {present.get(key)!r} ({first['msg']})"
            ) from exc

    @classmethod
    def load_for(cls, project: str) -> PodSettings:
        """Read and validate one pod Lead's stored settings (see class docs:
        never catch the raised error to substitute a default)."""
        lead_id = member_id(project, "lead")
        present = {k: v for k in cls.KEYS if (v := _fleet.meta_get(lead_id, k, ""))}
        return cls._validated(present)

    @classmethod
    def coerce(cls, key: str, value: str) -> float | int | str:
        """Validate *value* for *key* and return the number or comma-joined form a
        caller should persist via ``core.fleet.meta_set``; never writes itself. For
        ``pipeline``, *value* is already the copy's sha256 digest, not a file path."""
        if key not in cls.KEYS:
            raise PodSettingsError(
                f"unknown pod setting {key!r}; valid keys: {', '.join(cls.KEYS)}"
            )
        settings = cls._validated({key: value})
        return cast(
            "float | int | str", cls._stored_form(getattr(settings, _SETTING_FIELD_BY_ALIAS[key]))
        )

    @staticmethod
    def _stored_form(value: float | int | str | tuple[str, ...] | None) -> float | int | str | None:
        """A tuple-valued setting's meta-store form: comma-joined, matching how
        it is read back (``meta_get`` always returns a plain string)."""
        return ",".join(value) if isinstance(value, tuple) else value

    def value_and_source(self, key: str, project: str) -> tuple[float | int | str | None, str]:
        """This setting's value plus whether it is "set" (Lead meta) or
        "default" (this model's own default)."""
        lead_id = member_id(project, "lead")
        source = "set" if _fleet.meta_get(lead_id, key, "") else "default"
        return self._stored_form(getattr(self, _SETTING_FIELD_BY_ALIAS[key])), source


# The docket-owned copy of a pod's bound pipeline file lives at this fixed name in the
# Lead's own workspace -- alongside SOUL.md/AGENTS.md/HEARTBEAT.md -- never at the
# operator's original path, which can drift or disappear. ``PodSettings.pipeline`` stores
# only that copy's sha256 hex digest, so a hand-edited or stale copy is detected rather
# than silently trusted (see core/dispatch.py's ``_blueprint_pipeline``).
BOUND_PIPELINE_FILENAME = "PIPELINE.yaml"


def bound_pipeline_path(project: str) -> Path:
    """Where a pod's bound pipeline copy lives, if ``PodSettings.pipeline`` is set."""
    return _cfg.workspace_dir(member_id(project, "lead")) / BOUND_PIPELINE_FILENAME
