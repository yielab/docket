"""Domain models for .docket-meta.json (per-agent workspace metadata)."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Bump when adding required fields or changing semantics of existing ones.
# Records without this field are implicitly version 1 (the current shape).
SCHEMA_VERSION = 1


class AgentKind(StrEnum):
    project = "project"
    specialist = "specialist"


class ModelSource(StrEnum):
    policy = "policy"
    pinned = "pinned"


class AgentScope(StrEnum):
    """Whose data an agent may see. Orthogonal to ``kind``/``role``.

    ``org``     — a shared, cross-cutting agent (one instance serves all projects).
    ``project`` — scoped to a single project/pod; never shared across projects.
    """

    org = "org"
    project = "project"


class WorkspaceKind(StrEnum):
    """Whether a project agent's workspace is anchored to a codebase or a
    plain working directory (ROADMAP Phase 16 W-7's pod blueprints).

    ``codebase`` — a git-tracked project directory (``codebase`` field);
    every project agent before W-7 is implicitly this. ``workdir`` — a plain
    working directory with no codebase assumption (``workDir`` field
    instead), for objectives that aren't "build a web site" (research,
    content, ops blueprints). Mutually exclusive with ``codebase``: an agent
    has one or the other, never both.
    """

    codebase = "codebase"
    workdir = "workdir"


# Backfill inference for legacy metas written before ``scope`` existed.
# The authoritative split lives in config.py; this inline set exists only so a
# pre-Phase-10 record can resolve its scope on read without importing config.
_PROJECT_SPECIALIST_ROLES = frozenset({"programmer", "reviewer", "tester"})


class Persona(BaseModel):
    """Optional, operator-assigned cosmetic identity for an agent.

    docket owns this and renders it into ``SOUL.md`` — it is **not** read from a
    self-authored ``IDENTITY.md``. Keeping the persona as docket metadata
    (re-derivable, re-renderable, healable) is what keeps a friendly name like
    "Orion" congruent with docket's "identity = a pure function of metadata" model
    (see ``internal-docs/agent-structure-analysis.md`` §6). An agent's *role* is its
    real identity; this is only the display skin on top.
    """

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    name: str = ""
    emoji: str = ""
    vibe: str = ""

    def label(self) -> str:
        """Human display label, e.g. ``"Orion 🔭"`` — empty if no name set."""
        if not self.name:
            return ""
        return f"{self.name} {self.emoji}".strip()


class AgentMeta(BaseModel):
    """Canonical in-memory representation of .docket-meta.json.

    extra="allow" keeps unknown fields on round-trips (forward-compat).
    populate_by_name=True lets callers pass either snake_case or the alias.
    """

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    schema_version: int = Field(SCHEMA_VERSION, alias="schemaVersion")

    kind: AgentKind
    scope: AgentScope = Field(AgentScope.project)
    name: str = ""
    codebase: str = ""
    stack: str = ""
    description: str = ""
    role: str = ""
    # ROADMAP Phase 16 W-7: which pod blueprint provisioned this agent (e.g.
    # "software", "research") and whether its workspace is anchored to a
    # codebase or a plain working directory. Absent/default on every record
    # written before W-7 — a legacy agent is implicitly `workspace_kind:
    # codebase`, exactly what it already is.
    blueprint: str = ""
    workspace_kind: WorkspaceKind = Field(WorkspaceKind.codebase, alias="workspaceKind")
    work_dir: str = Field("", alias="workDir")
    model: str = ""
    model_source: ModelSource = Field(ModelSource.policy, alias="modelSource")
    created: str = ""
    session_key: str = Field("", alias="sessionKey")
    project_key: str = Field("", alias="projectKey")
    budget_usd: float | None = Field(None, alias="budgetUsd")
    paused: bool = False
    paused_reason: str = Field("", alias="pausedReason")

    # R-2: pod-wide dispatch timeout overrides, set on the Lead alongside
    # budgetUsd (core/dispatch.py reads them the same way it reads the Lead's
    # budgetUsd for pod_budget()). None = no pod-level override; falls back to
    # DEFAULT_TIMEOUT (or a serve-wide config knob) at dispatch time.
    turn_timeout_s: int | None = Field(None, alias="turnTimeoutS")
    verify_timeout_s: int | None = Field(None, alias="verifyTimeoutS")

    # Implementer-only; allocated at pod provisioning; lives only in .docket-meta.json.
    port_range_start: int | None = Field(None, alias="portRangeStart")
    port_range_count: int | None = Field(None, alias="portRangeCount")
    scratch_dir: str | None = Field(None, alias="scratchDir")

    # Implementer-only; shell command run after each hop. Non-zero exit blocks done.
    verify_cmd: str = Field("", alias="verifyCmd")

    template_version: str = Field("", alias="templateVersion")

    # Optional operator-assigned cosmetic identity, rendered into SOUL.md by docket.
    # Absent (None) for agents with no persona — they display by role/id.
    persona: Persona | None = None

    def display_name(self) -> str:
        """The name a human sees: persona label → ``name`` → role.

        Never derived from a self-authored ``IDENTITY.md`` — identity of record is
        docket metadata. Used by ``docket info``/``edit``/listing surfaces.
        """
        if self.persona and self.persona.label():
            return self.persona.label()
        return self.name or self.role or ""

    def is_paused(self) -> bool:
        """Real ``bool`` for this agent's ``paused`` flag.

        ``paused`` is already typed ``bool`` on this model, so pydantic
        coerces a legacy ``"true"``/``"false"`` string on ``model_validate`` —
        this accessor is the one place any caller should read the flag from,
        rather than re-deriving it. See ``coerce_paused`` for the raw-dict
        equivalent (display code that reads ``.docket-meta.json`` directly
        without constructing a full ``AgentMeta``).
        """
        return self.paused

    @staticmethod
    def coerce_paused(value: object) -> bool:
        """Coerce a raw (possibly legacy) ``paused`` value to a real ``bool``.

        R-5 fixed a type bug: a writer stored a real JSON boolean while
        display code (``cli/_agents.py``) compared it against the *string*
        ``"true"`` (``raw.get("paused", "") == "true"``) — which is never
        equal to a Python ``True``, so a paused agent silently displayed as
        not-paused. This is the one coercion function every raw-dict read
        site (and ``core/dispatch.py``'s claim-time refusal) should call
        instead of re-implementing the comparison. Tolerates both a genuine
        JSON boolean and the legacy string form (case-insensitive).
        """
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() == "true"

    @model_validator(mode="before")
    @classmethod
    def _backfill_scope(cls, data: object) -> object:
        """Derive ``scope`` for records written before it existed.

        Only fills when absent — an explicit ``scope`` is always respected.
        """
        if not isinstance(data, dict) or "scope" in data:
            return data
        if str(data.get("kind", "")) == AgentKind.specialist.value:
            role = str(data.get("role", ""))
            scope = AgentScope.project if role in _PROJECT_SPECIALIST_ROLES else AgentScope.org
        else:
            scope = AgentScope.project
        return {**data, "scope": scope.value}
