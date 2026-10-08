"""Domain models for .docket-meta.json (per-agent workspace metadata)."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class AgentKind(StrEnum):
    project = "project"


class ModelSource(StrEnum):
    policy = "policy"
    pinned = "pinned"


class AgentScope(StrEnum):
    """Whose data an agent may see: ``project`` is scoped to a single project/pod,
    never shared across projects."""

    project = "project"


class WorkspaceKind(StrEnum):
    """Whether a project agent's workspace is anchored to a codebase or a plain working
    directory (mutually exclusive). ``codebase`` is a git-tracked project directory
    (the default); ``workdir`` assumes no codebase, for
    objectives that aren't "build a web site"."""

    codebase = "codebase"
    workdir = "workdir"


class AgentMeta(BaseModel):
    """Canonical in-memory representation of .docket-meta.json. extra="allow" keeps
    unknown fields on round-trips (forward-compat); populate_by_name=True lets callers
    pass either snake_case or the alias."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    kind: AgentKind
    scope: AgentScope = Field(AgentScope.project)
    name: str = ""
    codebase: str = ""
    stack: str = ""
    description: str = ""
    role: str = ""
    # Which pod blueprint provisioned this agent (e.g. "software", "research")
    # and whether its workspace is anchored to a codebase or a plain working
    # directory.
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

    # Pod-wide dispatch timeout overrides, set on the Lead alongside
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

    def display_name(self) -> str:
        """The name a human sees: ``name`` → role. Never derived from a
        self-authored ``IDENTITY.md`` — identity of record is docket metadata."""
        return self.name or self.role or ""

    def is_paused(self) -> bool:
        """Real ``bool`` for the ``paused`` flag; the one place any caller should read
        it, since pydantic coerces a string value on ``model_validate``. See
        ``coerce_paused`` for the raw-dict equivalent."""
        return self.paused

    @staticmethod
    def coerce_paused(value: object) -> bool:
        """Coerce a raw (possibly stringified) ``paused`` value to a real ``bool``. Guards a
        type bug: comparing a JSON boolean against the *string* ``"true"`` is never equal
        to Python ``True``, so a paused agent could silently display as not-paused. Every
        raw-dict read site (and ``core/dispatch.py``'s claim-time refusal) should call
        this instead of re-implementing the comparison; tolerates both forms
        (case-insensitive)."""
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() == "true"
