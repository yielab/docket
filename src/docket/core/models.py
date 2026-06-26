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


class AgentType(StrEnum):
    repo = "repo"
    task = "task"


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


# Backfill inference for legacy metas written before ``scope`` existed.
# The authoritative split lives in config.py; this inline set exists only so a
# pre-Phase-10 record can resolve its scope on read without importing config.
_PROJECT_SPECIALIST_ROLES = frozenset({"programmer", "reviewer", "tester"})


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
    type: AgentType | None = None
    codebase: str = ""
    stack: str = ""
    description: str = ""
    role: str = ""
    model: str = ""
    model_source: ModelSource = Field(ModelSource.policy, alias="modelSource")
    created: str = ""
    session_key: str = Field("", alias="sessionKey")
    project_key: str = Field("", alias="projectKey")
    budget_usd: float | None = Field(None, alias="budgetUsd")
    paused: bool = False
    paused_reason: str = Field("", alias="pausedReason")

    # Implementer-only; allocated at pod provisioning; never synced to openclaw.json.
    port_range_start: int | None = Field(None, alias="portRangeStart")
    port_range_count: int | None = Field(None, alias="portRangeCount")
    scratch_dir: str | None = Field(None, alias="scratchDir")

    # Implementer-only; shell command run after each hop. Non-zero exit blocks done.
    verify_cmd: str = Field("", alias="verifyCmd")

    template_version: str = Field("", alias="templateVersion")

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
