"""Dual-source consistency checker: .docket-meta.json ↔ openclaw.json.

The model and sessionKey fields must agree in both stores. This module detects
discrepancies so `docket doctor` and `docket maintain check` can surface and
optionally fix them.
"""

from __future__ import annotations

from dataclasses import dataclass

from docket.edges.adapters import openclaw as oc

# Fields that must agree in both stores.
SYNCED_FIELDS = ("model", "sessionKey")


@dataclass
class Drift:
    agent_id: str
    field: str  # camelCase field name (matches JSON key)
    meta_value: str  # value in .docket-meta.json
    oc_value: str  # value in openclaw.json


def check_agent(agent_id: str) -> list[Drift]:
    """Return a list of Drift items for one agent.

    An empty list means the two stores agree on all synced fields.
    """
    drifts: list[Drift] = []

    meta = oc.meta_read(agent_id)
    oc_agent = oc.get_agent(agent_id)

    if oc_agent is None:
        # Not registered in openclaw.json at all — not a sync drift, it's a
        # registration error; callers (doctor) handle it separately.
        return drifts

    # model
    if meta.model != oc_agent.model:
        drifts.append(
            Drift(
                agent_id=agent_id,
                field="model",
                meta_value=meta.model,
                oc_value=oc_agent.model,
            )
        )

    # sessionKey
    meta_sk = meta.session_key
    oc_sk = oc_agent.metadata.session_key
    if meta_sk != oc_sk:
        drifts.append(
            Drift(
                agent_id=agent_id,
                field="sessionKey",
                meta_value=meta_sk,
                oc_value=oc_sk,
            )
        )

    return drifts


def check_all() -> list[Drift]:
    """Check every registered agent.  Skips agents with no meta file."""
    from docket.config import meta_path  # avoid circular at module level

    all_drifts: list[Drift] = []
    for oc_agent in oc.list_agents():
        if not meta_path(oc_agent.id).exists():
            continue
        all_drifts.extend(check_agent(oc_agent.id))
    return all_drifts
