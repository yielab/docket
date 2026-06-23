"""Domain models for .docket-meta.json (per-agent workspace metadata)."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

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


class AgentMeta(BaseModel):
    """Canonical in-memory representation of .docket-meta.json.

    extra="allow" keeps unknown fields on round-trips (forward-compat while the
    Bash layer still owns some fields we haven't modelled yet).
    populate_by_name=True lets callers pass either snake_case or the alias.
    """

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    schema_version: int = Field(SCHEMA_VERSION, alias="schemaVersion")

    # --- identity ---
    kind: AgentKind
    name: str = ""

    # --- project agent ---
    type: AgentType | None = None
    codebase: str = ""
    stack: str = ""
    description: str = ""

    # --- specialist ---
    role: str = ""

    # --- model (synced → openclaw.json) ---
    model: str = ""
    model_source: ModelSource = Field(ModelSource.policy, alias="modelSource")

    # --- lifecycle ---
    created: str = ""
    session_key: str = Field("", alias="sessionKey")
    project_key: str = Field("", alias="projectKey")

    # --- budget / pause (local only) ---
    budget_usd: float | None = Field(None, alias="budgetUsd")
    paused: bool = False
    paused_reason: str = Field("", alias="pausedReason")

    # --- internal ---
    template_version: str = Field("", alias="templateVersion")
