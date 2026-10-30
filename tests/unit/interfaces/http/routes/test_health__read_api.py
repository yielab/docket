"""Stable read API — contract shape pinning.

These tests are the machine-readable counterpart to specs/data/serve-read-api.spec.md.
Any test break here is a breaking API change and must bump SERVE_API_VERSION.

Acceptance criteria:
  - /status.json emits a documented, versioned shape
  - /metrics emits a documented set of metric names
  - The contract spec file exists
  - suite green
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tests.support import home as _support_home

from docket.interfaces.http import server
from docket.interfaces.http.routes import health, metrics

api_home = _support_home.api_home

SUBJECT = "docket.interfaces.http.routes.health"

# ── test fixtures (mirrors test_serve.py fake_home) ───────────────────────

META: dict[str, Any] = {
    "kind": "project",
    "name": "Api Test Agent",
    "scope": "project",
    "model": "anthropic/claude-haiku-4-5-20251001",
    "budgetUsd": "5.0",
}

FLEET_CONFIG: dict[str, Any] = {
    "agents": [{"id": "apitest"}],
    "bindings": [],
    "security": {},
}


# ── TestApiContract: machine-readable contract pins ───────────────────────────


class TestApiContract:
    """Break one of these → you've changed the API contract → bump SERVE_API_VERSION."""

    # /status.json top-level keys
    STATUS_TOP_LEVEL_KEYS = frozenset(
        {"apiVersion", "timestamp", "channels", "agents", "totalCostUsd"}
    )

    # /status.json per-agent keys
    AGENT_KEYS = frozenset(
        {
            "id",
            "name",
            "kind",
            "scope",
            "model",
            "registered",
            "bindings",
            "lastActivity",
            "costUsd",
            "budgetUsd",
        }
    )

    # /metrics metric names (the stable set; new ones may be added)
    METRIC_NAMES = frozenset(
        {
            "docket_agents_total",
            "docket_agent_cost_usd",
            "docket_agent_turns_total",
            "docket_cost_usd_total",
            "docket_approvals_pending_total",
            "docket_inbox_items",
        }
    )

    def test_api_version_is_string(self, api_home: Path) -> None:
        st = health.build_status()
        assert isinstance(st["apiVersion"], str)
        assert st["apiVersion"] == health.SERVE_API_VERSION

    def test_status_top_level_keys(self, api_home: Path) -> None:
        st = health.build_status()
        # Allow superset (new keys OK) — missing keys are the breaking change.
        assert self.STATUS_TOP_LEVEL_KEYS.issubset(set(st.keys()))

    def test_agent_keys_present(self, api_home: Path) -> None:
        agents = health.build_status()["agents"]
        assert len(agents) >= 1
        for agent in agents:
            assert self.AGENT_KEYS.issubset(set(agent.keys())), (
                f"Agent record missing keys: {self.AGENT_KEYS - set(agent.keys())}"
            )

    def test_agent_scope_field(self, api_home: Path) -> None:
        agents = health.build_status()["agents"]
        for agent in agents:
            assert agent["scope"] == "project", f"scope must be 'project', got {agent['scope']!r}"

    def test_agent_budget_field(self, api_home: Path) -> None:
        agents = health.build_status()["agents"]
        for agent in agents:
            budget = agent["budgetUsd"]
            assert budget is None or isinstance(budget, (int, float)), (
                f"budgetUsd must be float or null, got {type(budget)}"
            )

    def test_agent_kind_field(self, api_home: Path) -> None:
        agents = health.build_status()["agents"]
        for agent in agents:
            assert agent["kind"] == "project"

    def test_total_cost_is_float(self, api_home: Path) -> None:
        st = health.build_status()
        assert isinstance(st["totalCostUsd"], float)

    def test_metrics_stable_names_present(self, api_home: Path) -> None:
        text = metrics.render_metrics()
        for name in self.METRIC_NAMES:
            assert name in text, f"Stable metric {name!r} missing from /metrics output"

    def test_metrics_no_trailing_newline(self, api_home: Path) -> None:
        assert not metrics.render_metrics().endswith("\n")

    def test_health_shape(self, api_home: Path) -> None:
        body = json.loads(server.render_health())
        assert body["status"] == "ok"
        assert set(body["dispatch"]) == {"on", "inflight", "stopping", "workers"}


# ── TestSpecDocExists ─────────────────────────────────────────────────────────


class TestSpecDocExists:
    def test_spec_file_exists(self) -> None:
        spec = Path("specs/data/serve-read-api.spec.md")
        assert spec.exists(), "specs/data/serve-read-api.spec.md must exist"

    def test_spec_mentions_api_version(self) -> None:
        spec = Path("specs/data/serve-read-api.spec.md")
        text = spec.read_text(encoding="utf-8")
        assert "apiVersion" in text
        assert health.SERVE_API_VERSION in text

    def test_spec_mentions_stable_metric_names(self) -> None:
        spec = Path("specs/data/serve-read-api.spec.md")
        text = spec.read_text(encoding="utf-8")
        for name in TestApiContract.METRIC_NAMES:
            assert name in text, f"Spec doc missing metric {name!r}"


# ── TestBudgetInStatusJson ────────────────────────────────────────────────────


class TestBudgetInStatusJson:
    def test_budget_read_from_meta(self, api_home: Path) -> None:
        agents = health.build_status()["agents"]
        assert len(agents) == 1
        # META has budgetUsd = "5.0" → should appear as float 5.0
        assert agents[0]["budgetUsd"] == 5.0

    def test_no_budget_returns_null(self, api_home: Path, tmp_path: Path) -> None:
        # Overwrite meta without budgetUsd
        ws = api_home / "state" / "workspaces" / "projects" / "apitest"
        meta_no_budget = {k: v for k, v in META.items() if k != "budgetUsd"}
        (ws / ".docket-meta.json").write_text(json.dumps(meta_no_budget))
        agents = health.build_status()["agents"]
        assert agents[0]["budgetUsd"] is None
