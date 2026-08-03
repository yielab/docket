"""Domain models for fleet.json — docket's own agent-fleet registry.

ROADMAP Phase 19 P19-6: agent registration, channel bindings, gates/isolation
flags, and the org-wide default model used to live in ``openclaw.json``
(the daemon's file), read/written through the ACL
(``edges/adapters/openclaw.py``) via ``core/oc_models.py``'s
``OpenClawConfig``. That created two writers of overlapping state — the
daemon (or a raw ``openclaw`` CLI call, or a hand edit) could mutate
``openclaw.json`` independently of docket, which is exactly what
``core/sync.py``'s meta<->openclaw.json drift check existed to catch.

``FleetConfig`` (this module) is the replacement: a plain, docket-owned
format written **only** by docket, through ``edges/store.py`` — nothing else
ever writes ``fleet.json``. That is what makes the drift problem disappear
rather than merely relocate: with a single writer, "an older docket version
partially wrote this" is still possible in principle, but "a different
program touched this file" is not.

**Deliberately not duplicated:** a registered agent's ``model``, ``sessionKey``
and ``projectKey`` remain ``.docket-meta.json``'s job (see ``core/models.py``'s
``AgentMeta``) and are NOT tracked here. ``FleetAgent`` records only the bare
fact of registration (its id) — carrying a second copy of fields
``.docket-meta.json`` already owns would just recreate the drift this card
exists to remove. (Historically this duplication was mostly theoretical
anyway: ``edges/adapters/openclaw.py``'s old ``_strip_empty_modeled_keys``
never even persisted ``sessionKey``/``projectKey`` to disk on the openclaw.json
side — see that module's history — so no behavior is lost.)

Lenient by design (``extra="allow"``) so a future field added by one docket
version round-trips through an older one instead of being silently dropped.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

_LENIENT = ConfigDict(extra="allow", populate_by_name=True)


class FleetAgent(BaseModel):
    """One registered agent — presence only; model/session live in AgentMeta."""

    model_config = _LENIENT

    id: str = ""


class FleetBinding(BaseModel):
    """One channel binding: which peer (e.g. a Telegram group) routes to an agent."""

    model_config = _LENIENT

    agent_id: str = Field("", alias="agentId")
    channel: str = "telegram"
    peer_kind: str = Field("group", alias="peerKind")
    peer_id: str = Field("", alias="peerId")


class FleetDefaults(BaseModel):
    """Org-wide defaults. Today: the default model new agents provision with."""

    model_config = _LENIENT

    model: str = ""


class FleetSecurity(BaseModel):
    """Gates/isolation/approval-routing flags (ROADMAP security-gates.spec.md)."""

    model_config = _LENIENT

    gates_enabled: bool = Field(False, alias="gatesEnabled")
    isolation_enabled: bool = Field(False, alias="isolationEnabled")
    # 'unset' | 'off' | a sandbox mode string (e.g. 'non-main') — mirrors the
    # old openclaw.json agents.defaults.sandbox.mode vocabulary.
    isolation_mode: str = Field("unset", alias="isolationMode")
    # 'unset' | 'on' | 'off' — a real tri-state, not a bool, so "never
    # configured" and "explicitly turned off" stay distinguishable (the same
    # shape as isolation_mode above; a bare `enabled: bool` cannot tell those
    # two apart, which is exactly the ambiguity openclaw.json's presence/absence
    # of the `approvals.exec` key used to resolve).
    approval_routing_state: str = Field("unset", alias="approvalRoutingState")
    approval_routing_mode: str = Field("", alias="approvalRoutingMode")


class FleetConfig(BaseModel):
    """Top-level shape of fleet.json."""

    model_config = _LENIENT

    agents: list[FleetAgent] = Field(default_factory=list)
    bindings: list[FleetBinding] = Field(default_factory=list)
    security: FleetSecurity = Field(default_factory=lambda: FleetSecurity())
    defaults: FleetDefaults = Field(default_factory=lambda: FleetDefaults())
