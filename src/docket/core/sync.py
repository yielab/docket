"""Dual-source consistency checker: .docket-meta.json ↔ openclaw.json.

The model and sessionKey fields must agree in both stores. `check_agent`/
`check_all` are the single implementation of that comparison; `docket doctor`'s
config-drift check (`cli/_doctor.py`'s `_check_drift`) renders their `Drift`
records and drives the interactive `--fix` re-sync — it does not reimplement
the comparison itself (core/ owns the logic, cli/ owns the presentation).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from docket.config import meta_path
from docket.core.oc_models import OcAgent, OpenClawConfig
from docket.edges import store
from docket.edges.adapters import openclaw as oc

# Fields that must agree in both stores; camelCase to match the JSON keys in
# both .docket-meta.json and openclaw.json's agent metadata.
SYNCED_FIELDS = ("model", "sessionKey")

# Each SYNCED_FIELDS entry lives at a different depth on the openclaw.json side
# (top-level vs. under .metadata) — this map lets check_agent() iterate
# SYNCED_FIELDS and look up how to read it, instead of one hardcoded
# near-identical `if` block per field.
_OC_GETTERS: dict[str, Callable[[OcAgent], str]] = {
    "model": lambda a: a.model,
    "sessionKey": lambda a: a.metadata.session_key,
}


@dataclass
class Drift:
    agent_id: str
    field: str  # one of SYNCED_FIELDS (camelCase, matches the JSON key)
    meta_value: str  # value in .docket-meta.json
    oc_value: str  # value in openclaw.json


def check_agent(agent_id: str, cfg: OpenClawConfig | None = None) -> list[Drift]:
    """Return one Drift per SYNCED_FIELDS entry the two stores disagree on.

    Reads .docket-meta.json as a raw dict rather than the strict `AgentMeta`
    model — a partially-written or legacy-schema record is a *different*
    health problem than sync drift and must not raise here; a caller that
    cares about shape (`docket doctor`'s other checks) diagnoses that
    separately. An empty/absent value on either side is "nothing to compare"
    (e.g. an agent mid-provisioning with no sessionKey yet is not drift).

    *cfg*, if given, is reused instead of `check_agent` reloading
    openclaw.json itself — callers checking many agents (`check_all`,
    `docket doctor`) pass one config loaded once.
    """
    drifts: list[Drift] = []

    meta_file = meta_path(agent_id)
    if not meta_file.is_file():
        return drifts
    meta = store.read_json(meta_file)

    oc_agent = oc.get_agent(agent_id, cfg)
    if oc_agent is None:
        # Not registered in openclaw.json at all — not a sync drift, it's a
        # registration error; callers (doctor) handle it separately.
        return drifts

    for field in SYNCED_FIELDS:
        meta_value = str(meta.get(field, ""))
        oc_value = _OC_GETTERS[field](oc_agent)
        if meta_value and oc_value and meta_value != oc_value:
            drifts.append(
                Drift(agent_id=agent_id, field=field, meta_value=meta_value, oc_value=oc_value)
            )

    return drifts


def check_all() -> list[Drift]:
    """Check every registered agent that has a .docket-meta.json file."""
    cfg = oc.load_config()
    all_drifts: list[Drift] = []
    for oc_agent in oc.list_agents(cfg):
        if not meta_path(oc_agent.id).exists():
            continue
        all_drifts.extend(check_agent(oc_agent.id, cfg))
    return all_drifts
