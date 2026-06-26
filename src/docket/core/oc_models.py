"""Pydantic models for OpenClaw-owned JSON files.

Lenient by design: extra="allow" on every model so round-trips never drop
fields that OpenClaw added between docket versions. The shape here reflects
what openclaw.json and auth-profiles.json look like today; the ACL
(edges/adapters/openclaw.py) is the only caller of these models.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

_LENIENT = ConfigDict(extra="allow", populate_by_name=True)


class OcPeer(BaseModel):
    model_config = _LENIENT

    kind: str = "group"
    id: str = ""


class OcMatch(BaseModel):
    model_config = _LENIENT

    channel: str = "telegram"
    peer: OcPeer = Field(default_factory=lambda: OcPeer())


class OcBinding(BaseModel):
    model_config = _LENIENT

    agent_id: str = Field("", alias="agentId")
    match: OcMatch = Field(default_factory=lambda: OcMatch())


class OcAgentMetadata(BaseModel):
    model_config = _LENIENT

    session_key: str = Field("", alias="sessionKey")
    project_key: str = Field("", alias="projectKey")


class OcAgent(BaseModel):
    model_config = _LENIENT

    id: str = ""
    model: str = ""
    metadata: OcAgentMetadata = Field(default_factory=lambda: OcAgentMetadata())


class OcAgentDefaults(BaseModel):
    model_config = _LENIENT

    # OpenClaw stores the default model either as a bare id string or as a
    # {"primary": "<id>", ...} object (what `docket install` writes). Accept both
    # so a real openclaw.json round-trips; the ACL normalises to a string on read.
    model: str | dict[str, Any] = ""


class OcAgents(BaseModel):
    model_config = _LENIENT

    defaults: OcAgentDefaults = Field(default_factory=lambda: OcAgentDefaults())
    # Field named `list` in JSON; renamed here because `list` shadows the built-in
    # in Pydantic's annotation evaluator.
    items: list[OcAgent] = Field(default_factory=list, alias="list")


class OcSecurityFlag(BaseModel):
    model_config = _LENIENT

    enabled: bool = False


class OcSecurity(BaseModel):
    model_config = _LENIENT

    gates: OcSecurityFlag = Field(default_factory=lambda: OcSecurityFlag())
    isolation: OcSecurityFlag = Field(default_factory=lambda: OcSecurityFlag())


class OpenClawConfig(BaseModel):
    """Top-level shape of ~/.openclaw/openclaw.json."""

    model_config = _LENIENT

    agents: OcAgents = Field(default_factory=lambda: OcAgents())
    bindings: list[OcBinding] = Field(default_factory=list)
    security: OcSecurity = Field(default_factory=lambda: OcSecurity())


class AuthProfileUsage(BaseModel):
    model_config = _LENIENT

    disabled_until: float = Field(0.0, alias="disabledUntil")
    disabled_reason: str = Field("", alias="disabledReason")


class AuthProfile(BaseModel):
    model_config = _LENIENT

    provider: str = ""
    type: str = ""  # "token", "oauth", "api_key"


class AuthProfiles(BaseModel):
    """Shape of ~/.openclaw/agents/<agent>/agent/auth-profiles.json."""

    model_config = _LENIENT

    profiles: dict[str, AuthProfile] = Field(default_factory=dict)
    usage_stats: dict[str, AuthProfileUsage] = Field(default_factory=dict, alias="usageStats")
