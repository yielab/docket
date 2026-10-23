from __future__ import annotations

import json
from typing import Any

from docket.hops.gates import pre_hop as _pre_hop
from docket.interfaces.http.exchange import HttpExchange
from docket.kernel import clock as _clock
from docket.kernel.home import current_home
from docket.platform import store
from docket.teams import fleet, utils

# Bumped on any breaking change to /status.json or /metrics contract, or to the
# authenticated write/read-registry endpoints (/dispatch, /runs).
# Pinned by tests/unit/test_serve__read_api.py (TestApiContract).
SERVE_API_VERSION = "6"


def _with_token_budget(task: dict[str, Any]) -> dict[str, Any]:
    """*task* plus ``tokenBudget``, the measured-token ceiling its next hop runs under."""

    left = _pre_hop._task_token_budget(task)
    return {
        **task,
        "tokenBudget": current_home().agent_loop_token_budget if left is None else max(0, left),
    }


def _last_activity_or_never(agent_id: str) -> str:
    """Like utils.last_activity but returns 'never' (cmd_snapshot's sentinel)."""
    val = utils.last_activity(agent_id)
    return "never" if val == "—" else val


def _agent_record(agent_id: str, *, kind: str, registered: set[str]) -> dict[str, Any]:
    meta_path = current_home().meta_path(agent_id)
    meta: dict[str, Any] = store.read_json(meta_path) if meta_path.exists() else {}
    cost = round(utils.aggregate_cost(agent_id).cost_usd, 6)
    budget_raw = meta.get("budgetUsd")
    budget: float | None = (
        float(budget_raw) if budget_raw and str(budget_raw) not in ("", "0") else None
    )
    return {
        "id": agent_id,
        "name": str(meta.get("name", agent_id)),
        "kind": kind,
        "scope": str(meta.get("scope", "project")),
        "model": str(meta.get("model", "")),
        "registered": agent_id in registered,
        "bindings": [{"channel": b["channel"]} for b in fleet.agent_bindings(agent_id)],
        "lastActivity": _last_activity_or_never(agent_id),
        "costUsd": cost,
        "budgetUsd": budget,
    }


def build_status() -> dict[str, Any]:
    """Build the /status.json payload. Schema, versioned by ``SERVE_API_VERSION``:
    specs/data/serve-read-api.spec.md (GET /status.json).
    """
    channels = fleet.channel_names()
    registered = {a.id for a in fleet.list_agents()}

    agents: list[dict[str, Any]] = []
    total_cost = 0.0

    for pid in utils.project_ids():
        rec = _agent_record(pid, kind="project", registered=registered)
        total_cost += float(rec["costUsd"])
        agents.append(rec)

    return {
        "apiVersion": SERVE_API_VERSION,
        "timestamp": _clock.stamp(),
        "channels": channels,
        "agents": agents,
        "totalCostUsd": round(total_cost, 6),
    }


def render_status() -> str:
    """Render the /status.json body (indent=2, matching cmd_snapshot)."""
    return json.dumps(build_status(), indent=2)


def get_status(h: HttpExchange, _arg: str) -> None:
    h._send(render_status().encode("utf-8"), "application/json")


def get_health(h: HttpExchange, _arg: str) -> None:
    h._send(h._render_health().encode("utf-8"), "application/json")
