"""Domain models for .docket-meta.json (per-agent workspace metadata)."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError


def unknown_keys_text(exc: ValidationError) -> str:
    """``unknown key a.b, c`` for the keys a closed model refused in *exc*; ``""`` when the
    failure is about something else."""
    keys = [
        ".".join(str(part) for part in e["loc"])
        for e in exc.errors()
        if e["type"] == "extra_forbidden"
    ]
    return f"unknown key {', '.join(keys)}" if keys else ""


class AgentKind(StrEnum):
    project = "project"


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
    """Canonical in-memory representation of .docket-meta.json. The model is closed
    (``extra="forbid"``): a key it does not declare is refused. populate_by_name=True lets callers
    pass either snake_case or the alias."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    kind: AgentKind
    scope: AgentScope = Field(AgentScope.project)
    name: str = ""
    codebase: str = ""
    stack: str = ""
    description: str = ""
    role: str = ""
    # Which pod blueprint provisioned this agent (e.g. "build", "respond")
    # and whether its workspace is anchored to a codebase or a plain working
    # directory.
    blueprint: str = ""
    workspace_kind: WorkspaceKind = Field(WorkspaceKind.codebase, alias="workspaceKind")
    work_dir: str = Field("", alias="workDir")
    model: str = ""
    created: str = ""
    session_key: str = Field("", alias="sessionKey")
    project_key: str = Field("", alias="projectKey")
    budget_usd: float | None = Field(None, alias="budgetUsd", ge=0)
    paused: bool = False
    paused_reason: str = Field("", alias="pausedReason")

    # Pod-wide dispatch timeout overrides, set on the Lead alongside
    # budgetUsd (teams/settings.py reads them the same way it reads the Lead's
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

    # The pod this member belongs to.
    pod: str = ""

    # The pod's settings, kept on the Lead's file. Declared so a write of one validates; their
    # values are checked by ``PodSettings`` (teams/pod_settings.py), never here.
    max_rework_cycles: Any = Field(None, alias="maxReworkCycles")
    approval_mode: Any = Field(None, alias="approvalMode")
    approval_expiry_hours: Any = Field(None, alias="approvalExpiryHours")
    input_expiry_hours: Any = Field(None, alias="inputExpiryHours")
    allow_commands: Any = Field(None, alias="allowCommands")
    pipeline: Any = None
    schedule: Any = None
    project_instructions: Any = Field(None, alias="projectInstructions")
    mcp_servers: Any = Field(None, alias="mcpServers")
    denied_tools: Any = Field(None, alias="deniedTools")
    require_verify: Any = Field(None, alias="requireVerify")
    max_consultations_per_task: Any = Field(None, alias="maxConsultationsPerTask")
    consult_mode: Any = Field(None, alias="consultMode")
    network: Any = None
    profile: Any = None
    read_only: Any = Field(None, alias="readOnly")
    prepare: Any = None
    protects: Any = None
    config_source: Any = Field(None, alias="configSource")
    config_digest: Any = Field(None, alias="configDigest")
    exporters: Any = None
    network_grant: Any = Field(None, alias="networkGrant")

    @staticmethod
    def coerce_paused(value: object) -> bool:
        """Coerce a raw (possibly stringified) ``paused`` value to a real ``bool``. Guards a
        type bug: comparing a JSON boolean against the *string* ``"true"`` is never equal
        to Python ``True``, so a paused agent could silently display as not-paused. Every
        raw-dict read site (and ``hops/application/sweep.py``'s claim-time refusal) should call
        this instead of re-implementing the comparison; tolerates both forms
        (case-insensitive)."""
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() == "true"
