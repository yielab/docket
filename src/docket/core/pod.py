"""Pod composition model: the set of project-scoped agents making up one project. Composition
logic — the CLI (`docket init`/`docket pod`) turns a `PodPlan` into registered agents; this
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

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator
from pydantic import ValidationError as _PydanticValidationError

import docket.config as _cfg
from docket.core import archetypes as _archetypes
from docket.core import fleet as _fleet
from docket.core import mcp_tools as _mcp_tools
from docket.core import models_policy as _mp
from docket.core import schedule as _schedule
from docket.core import security as _security

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
    (``core/dispatch.py``) and the TOOLS.md generator (``cli/_pod.py``) resolve through this
    one helper so they can never disagree about which tree an implementer's work is checked
    against."""
    if task_worktree:
        return task_worktree
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
    "approvalExpiryHours": "approval_expiry_hours",
    "inputExpiryHours": "input_expiry_hours",
    "allowCommands": "allow_commands",
    "pipeline": "pipeline",
    "schedule": "schedule",
    "projectInstructions": "project_instructions",
    "mcpServers": "mcp_servers",
    "deniedTools": "denied_tools",
    "requireVerify": "require_verify",
    "maxConsultationsPerTask": "max_consultations_per_task",
    "network": "network",
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
    # byte-identical), parks it durably for a human to resolve later, or
    # refuses it at once -- threaded into the hop's tool env as
    # DOCKET_APPROVAL_MODE (see core/dispatch.py's `_compose_hop` and
    # core/tools.py's `ToolContext.approval_mode`). The field default stays
    # "wait" (export/apply round-trips and goldens depend on it); "unset" --
    # which caller-scoped default applies (ADR 0016 SS2) -- is detected from
    # whether the Lead's meta carries this key at all
    # (core/dispatch.py's `pod_approval_mode_is_set`), never from this value.
    approval_mode: Literal["wait", "park", "refuse"] = Field("wait", alias="approvalMode")
    # Hours a park-mode approval record stays live before the fail-closed
    # sweep denies it (core/dispatch.py's `_compose_hop`, which stamps each
    # parked call's own `expiresAt`).
    approval_expiry_hours: int = Field(24, alias="approvalExpiryHours", ge=1)
    # Hours an `input` step's unanswered question stays live before it is
    # tagged `blockedReason: "input_expired"` (read by a later execution card;
    # unused by dispatch until then).
    input_expiry_hours: int = Field(72, alias="inputExpiryHours", ge=1)
    allow_commands: tuple[str, ...] = Field((), alias="allowCommands")
    # sha256 hex digest of the docket-owned bound-pipeline copy in the Lead's workspace
    # (``bound_pipeline_path``) -- never the operator's original file path. Set only by
    # ``docket pod set pipeline <file>``, which validates the file and
    # writes the copy before this ever gets written (see core/dispatch.py's
    # ``_blueprint_pipeline``, which verifies the copy still hashes to this value).
    pipeline: str | None = Field(None, alias="pipeline", pattern=r"^[0-9a-f]{64}$")
    # An `@every`/`HH:MM`/cron spec (core/schedule.py). Mirrors the value the dedicated
    # `set schedule <spec>` CLI path (`cli/_pod.py::_pod_config_set_schedule`) persists as
    # this pod's actual source of truth in `docket-schedules.json` -- see that function's
    # docstring for why this field exists alongside a second, non-meta store.
    schedule: str | None = Field(None, alias="schedule")
    # Relative paths (comma-joined in storage, like allowCommands) inside this pod's
    # codebase root, composed into a turn's system prompt right after INSTRUCTIONS.md
    # (core/identity.py's opt-in section) -- the AGENTS.md/CLAUDE.md convention, but
    # never auto-discovered: unset (the default) composes byte-identically to today.
    # Validated here (not at codebase-resolution time) so a path that could only ever
    # escape the root -- absolute, home-relative, or containing a ".." segment -- is
    # refused at `set`, before this pod even has a resolved codebase root to check it
    # against; a plain `coerce` is enough because that check needs no filesystem
    # access, unlike `pipeline`'s dedicated CLI path (which must read and plan an
    # operator file) or `schedule`'s (which writes a second store).
    project_instructions: tuple[str, ...] = Field((), alias="projectInstructions")

    # This pod's own selection from the shared MCP server catalog
    # (core/mcp_tools.py::load_mcp_servers()). ``None`` (the default, and every
    # pod before this field existed) means "every configured server" -- today's
    # behavior, unchanged. A non-empty tuple names the exhaustive subset this
    # pod's turns load; edges/adapters/docket_runtime.py::_load_mcp_tools is the
    # sole reader (see its docstring for the live-turn refusal this feeds).
    # Validated against the *live* catalog at `set` time (below) -- not merely
    # syntactically -- because an unconfigured server name here is always a
    # mistake, unlike allowCommands/projectInstructions, whose validity does not
    # depend on any other docket-owned store.
    mcp_servers: tuple[str, ...] | None = Field(None, alias="mcpServers")
    # Built-in tool names this pod's every role additionally denies, unioned with
    # each role's own `denied_tools` by `core.archetypes.registry_for_role` (see
    # role-archetypes.spec.md's "Per-role tool sets" requirement 7). Validated
    # against the same known tool-name universe `denied_tools` narrowing already
    # keys off (`core.archetypes.BUILTIN_TOOL_KINDS`), so a typo is refused at
    # `set` instead of silently doing nothing at dispatch time.
    denied_tools: tuple[str, ...] = Field((), alias="deniedTools")

    # Whether an Implementer's unset verifyCmd (no verification gate) is
    # treated as skippable (the default, false) or as a required failure
    # (true). When true and verifyCmd is unset, the task fails with a
    # clear reason instead of silently advancing.
    require_verify: bool = Field(False, alias="requireVerify")
    # How many `consult` questions one task's turn may ask (core/consult.py); 0 disables.
    max_consultations_per_task: int = Field(3, alias="maxConsultationsPerTask", ge=0)

    # 'open' (the default: follow the global mode) or 'none': cut this pod's jailed tool calls
    # off the network. It only ever narrows -- see ``effective_network``.
    network: str = Field("open", alias="network")

    # Where this pod's team came from (ADR 0012): the absolute directory `core.pod_apply.apply`
    # last applied, and a sha256 fingerprint of that directory's contents at that moment
    # (`core.pod_apply.directory_digest`). Written only by `apply`, right after a plan that
    # wrote at least one item -- never by `docket pod set` (see `RECORDED_KEYS`) and
    # never carried in a `pod.yaml` `settings` mapping, since both are refused the same way any
    # key outside `KEYS` already is. `docket pod show` recomputes the digest
    # against the still-present directory to report drift.
    config_source: str = Field("", alias="configSource")
    config_digest: str = Field("", alias="configDigest", pattern=r"^(|[0-9a-f]{64})$")

    # Which observability destinations (`core.exporter.load_catalog()` names) this pod's last
    # applied recipe named (ADR 0014 rule 7) -- recorded by `core.pod_apply.apply`, exactly like
    # `configSource`/`configDigest` above, and never configurable directly (`pod set
    # exporters` is refused the same way). Names are already validated against the live catalog
    # by `plan_apply` before this is ever stored, so no catalog dependency is added here.
    exporters: tuple[str, ...] = Field((), alias="exporters")

    # Declaration order the CLI's ``config`` subcommand, ``load_for`` and
    # ``coerce`` all iterate, instead of a second hardcoded key list.
    KEYS: ClassVar[tuple[str, ...]] = (
        "budgetUsd",
        "maxReworkCycles",
        "turnTimeoutS",
        "verifyTimeoutS",
        "approvalMode",
        "approvalExpiryHours",
        "inputExpiryHours",
        "allowCommands",
        "pipeline",
        "schedule",
        "projectInstructions",
        "mcpServers",
        "deniedTools",
        "requireVerify",
        "maxConsultationsPerTask",
        "network",
    )

    # Recorded by `apply`, not operator-settable -- deliberately outside `KEYS` so every
    # settable-key path (`coerce`, `pod set`'s fallthrough, a `pod.yaml` `settings` mapping)
    # already refuses them as unknown; `pod set` checks this tuple first only to give the
    # friendlier "written by apply" message instead of "unknown pod setting".
    RECORDED_KEYS: ClassVar[tuple[str, ...]] = ("configSource", "configDigest", "exporters")

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

    @field_validator("schedule", mode="before")
    @classmethod
    def _parse_schedule(cls, value: Any) -> str | None:
        """A recognized ``@every``/``HH:MM``/cron spec, or None. Rejects (naming the
        reason) exactly the specs ``core.schedule.is_schedule_due`` would otherwise treat
        as silently never-due."""
        if value in (None, ""):
            return None
        text = str(value)
        reason = _schedule.describe_spec_error(text)
        if reason:
            raise ValueError(reason)
        return text

    # Rejects the only shapes that could ever resolve outside the codebase root this
    # pod's agents already have containment-checked access to (core/tools.py's
    # ``roots``). Purely syntactic -- no filesystem access -- so it refuses an
    # escaping value at `set` even before a codebase root exists to check it against.
    @field_validator("project_instructions", mode="before")
    @classmethod
    def _parse_project_instructions(cls, value: Any) -> tuple[str, ...]:
        """Comma-separated relative paths, like ``allow_commands``. Rejects (naming
        the path) an absolute, home-relative (``~``), or ``..``-containing value."""
        if value in (None, ""):
            return ()
        tokens = list(value) if isinstance(value, (list, tuple)) else str(value).split(",")
        kept: dict[str, None] = {}
        for raw in tokens:
            name = str(raw).strip()
            if not name:
                continue
            if "\x00" in name:
                raise ValueError(f"{name!r} contains a null byte")
            if name.startswith("~") or Path(name).is_absolute():
                raise ValueError(f"{name!r} is not a relative path inside the codebase root")
            if ".." in Path(name).parts:
                raise ValueError(f"{name!r} escapes the codebase root")
            kept.setdefault(name, None)
        return tuple(kept.keys())

    # Checked against `core.mcp_tools.load_mcp_servers()` right here -- a name absent
    # from the live catalog is refused (naming it) at `set` time, so a typo or a
    # since-removed server can never silently resolve to "load nothing" at dispatch
    # time.
    @field_validator("mcp_servers", mode="before")
    @classmethod
    def _parse_mcp_servers(cls, value: Any, info: ValidationInfo) -> tuple[str, ...] | None:
        """Comma-separated names from the global MCP catalog plus this pod's own pod-scoped
        servers (``context['project']``, and ``context['mcp_extra']`` for names a recipe is
        installing), or ``None`` (the default) for "every configured server"."""
        if value in (None, ""):
            return None
        tokens = list(value) if isinstance(value, (list, tuple)) else str(value).split(",")
        context = info.context or {}
        project = str(context.get("project", ""))
        catalog = {s.name for s in _mcp_tools.load_mcp_servers(project)}
        catalog.update(context.get("mcp_extra", ()))
        kept: dict[str, None] = {}
        for raw in tokens:
            name = str(raw).strip()
            if not name:
                continue
            if name not in catalog:
                owner = _mcp_tools.pod_scoped_owner(name, exclude=project)
                if owner:
                    raise ValueError(
                        f"{name!r} is an MCP server of another pod ({owner}); "
                        "a pod selects only global servers and its own"
                    )
                raise ValueError(f"{name!r} is not a configured MCP server (docket setup mcp list)")
            kept.setdefault(name, None)
        return tuple(kept.keys()) or None

    # Rejects (naming it) any name outside `core.archetypes.BUILTIN_TOOL_KINDS` -- the
    # same known-tool universe `registry_for_role`'s kind-based narrowing already keys
    # off -- so a typo is refused here rather than silently denying nothing.
    @field_validator("denied_tools", mode="before")
    @classmethod
    def _parse_denied_tools(cls, value: Any) -> tuple[str, ...]:
        """Comma-separated built-in tool names, like ``allow_commands``."""
        if value in (None, ""):
            return ()
        tokens = list(value) if isinstance(value, (list, tuple)) else str(value).split(",")
        known = set(_archetypes.BUILTIN_TOOL_KINDS)
        kept: dict[str, None] = {}
        for raw in tokens:
            name = str(raw).strip()
            if not name:
                continue
            if name not in known:
                raise ValueError(f"{name!r} is not a known tool name ({', '.join(sorted(known))})")
            kept.setdefault(name, None)
        return tuple(kept.keys())

    @field_validator("network", mode="before")
    @classmethod
    def _parse_network(cls, value: Any) -> str:
        """``none`` or ``open``."""
        name = str(value).strip().lower()
        if name not in ("none", "open"):
            raise ValueError("must be 'none' or 'open'")
        return name

    @field_validator("exporters", mode="before")
    @classmethod
    def _parse_exporters(cls, value: Any) -> tuple[str, ...]:
        """Comma-separated exporter catalog names, like ``allow_commands`` -- already
        validated against the catalog by ``core.pod_apply.plan_apply`` before this is ever
        stored, so this parser only reshapes the stored string back into a tuple."""
        if value in (None, ""):
            return ()
        tokens = list(value) if isinstance(value, (list, tuple)) else str(value).split(",")
        kept: dict[str, None] = {}
        for raw in tokens:
            name = str(raw).strip()
            if name:
                kept.setdefault(name, None)
        return tuple(kept.keys())

    @classmethod
    def _validated(
        cls,
        present: dict[str, str],
        *,
        project: str = "",
        mcp_extra: tuple[str, ...] = (),
        stored: bool = True,
    ) -> PodSettings:
        label = "invalid stored value" if stored else "invalid value"
        try:
            return cls.model_validate(present, context={"project": project, "mcp_extra": mcp_extra})
        except _PydanticValidationError as exc:
            first = exc.errors()[0]
            key = str(first["loc"][0]) if first["loc"] else "?"
            raise PodSettingsError(f"{key}: {label} {present.get(key)!r} ({first['msg']})") from exc

    @classmethod
    def load_for(cls, project: str) -> PodSettings:
        """Read and validate one pod Lead's stored settings, ``RECORDED_KEYS`` alongside
        ``KEYS`` (see class docs: never catch the raised error to substitute a default)."""
        lead_id = member_id(project, "lead")
        present = {
            k: v for k in (*cls.KEYS, *cls.RECORDED_KEYS) if (v := _fleet.meta_get(lead_id, k, ""))
        }
        return cls._validated(present, project=project)

    @classmethod
    def coerce(
        cls, key: str, value: str, *, project: str = "", mcp_extra: tuple[str, ...] = ()
    ) -> float | int | str:
        """Validate *value* for *key*; return the form to persist via ``core.fleet.meta_set``.
        Never writes. *project*/*mcp_extra* widen ``mcpServers`` to that pod's own servers."""
        if key not in cls.KEYS:
            raise PodSettingsError(
                f"unknown pod setting {key!r}; valid keys: {', '.join(cls.KEYS)}"
            )
        settings = cls._validated({key: value}, project=project, mcp_extra=mcp_extra, stored=False)
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


def effective_network(project: str | None) -> tuple[str, str]:
    """``(mode, scope)`` for a turn: ``none`` if the global mode or the pod's ``network`` says so,
    else ``open``. Scope is ``global``, ``pod`` or ``default``. A pod's ``open`` never widens a
    global ``none``; unreadable pod settings fail closed to ``none``."""
    if _fleet.get_network_mode() == "none":
        return "none", "global"
    if project is not None:
        try:
            if PodSettings.load_for(project).network == "none":
                return "none", "pod"
        except PodSettingsError:
            return "none", "pod"
    return "open", "default"


# The docket-owned copy of a pod's bound pipeline file lives at this fixed name in the
# Lead's own workspace -- alongside SOUL.md/AGENTS.md/HEARTBEAT.md -- never at the
# operator's original path, which can drift or disappear. ``PodSettings.pipeline`` stores
# only that copy's sha256 hex digest, so a hand-edited or stale copy is detected rather
# than silently trusted (see core/dispatch.py's ``_blueprint_pipeline``).
BOUND_PIPELINE_FILENAME = "PIPELINE.yaml"


def bound_pipeline_path(project: str) -> Path:
    """Where a pod's bound pipeline copy lives, if ``PodSettings.pipeline`` is set."""
    return _cfg.workspace_dir(member_id(project, "lead")) / BOUND_PIPELINE_FILENAME
