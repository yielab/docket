"""CD-8: Stable read API — contract shape pinning.

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

import pytest

import docket.config as _cfg
import docket.edges.adapters.openclaw as _oc
import docket.serve as serve

# ── test fixtures (mirrors test_m5_serve.py fake_home) ───────────────────────

META: dict[str, Any] = {
    "schemaVersion": 1,
    "kind": "project",
    "name": "Api Test Agent",
    "type": "lead",
    "scope": "project",
    "model": "anthropic/claude-haiku-4-5-20251001",
    "modelSource": "policy",
    "budgetUsd": "5.0",
}

OC_CONFIG: dict[str, Any] = {
    "agents": {
        "defaults": {"model": ""},
        "list": [
            {
                "id": "apitest",
                "model": "anthropic/claude-haiku-4-5-20251001",
                "metadata": {"sessionKey": "agent:apitest:default"},
            }
        ],
    },
    "bindings": [],
    "channels": {},
    "security": {"gates": {"enabled": False}, "isolation": {"enabled": False}},
}


@pytest.fixture()
def api_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    oc_dir = tmp_path / ".openclaw"
    oc_dir.mkdir()
    ws = oc_dir / "workspaces" / "projects" / "apitest"
    ws.mkdir(parents=True)
    (ws / ".docket-meta.json").write_text(json.dumps(META))
    (oc_dir / "openclaw.json").write_text(json.dumps(OC_CONFIG))

    config_file = oc_dir / "openclaw.json"
    monkeypatch.setenv("OPENCLAW_DIR", str(oc_dir))
    monkeypatch.setattr(_cfg, "OPENCLAW_DIR", oc_dir)
    monkeypatch.setattr(_cfg, "CONFIG_FILE", config_file)
    monkeypatch.setattr(_cfg, "PROJECTS_DIR", oc_dir / "workspaces" / "projects")
    monkeypatch.setattr(_oc, "CONFIG_FILE", config_file)
    monkeypatch.setattr(serve.utils, "gateway_active", lambda: True)
    # No approvals dir — list_pending() returns [] gracefully
    monkeypatch.setattr(_cfg, "APPROVALS_DIR", tmp_path / "approvals")
    return oc_dir


# ── TestApiContract: machine-readable contract pins ───────────────────────────


class TestApiContract:
    """Break one of these → you've changed the API contract → bump SERVE_API_VERSION."""

    # /status.json top-level keys
    STATUS_TOP_LEVEL_KEYS = frozenset(
        {"apiVersion", "timestamp", "gateway", "channels", "agents", "totalCostUsd"}
    )

    # /status.json per-agent keys
    AGENT_KEYS = frozenset(
        {
            "id",
            "name",
            "type",
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
            "docket_gateway_up",
            "docket_approvals_pending_total",
        }
    )

    def test_api_version_is_string(self, api_home: Path) -> None:
        st = serve.build_status()
        assert isinstance(st["apiVersion"], str)
        assert st["apiVersion"] == serve.SERVE_API_VERSION

    def test_status_top_level_keys(self, api_home: Path) -> None:
        st = serve.build_status()
        # Allow superset (new keys OK) — missing keys are the breaking change.
        assert self.STATUS_TOP_LEVEL_KEYS.issubset(set(st.keys()))

    def test_agent_keys_present(self, api_home: Path) -> None:
        agents = serve.build_status()["agents"]
        assert len(agents) >= 1
        for agent in agents:
            assert self.AGENT_KEYS.issubset(set(agent.keys())), (
                f"Agent record missing keys: {self.AGENT_KEYS - set(agent.keys())}"
            )

    def test_agent_scope_field(self, api_home: Path) -> None:
        agents = serve.build_status()["agents"]
        for agent in agents:
            assert agent["scope"] in ("project", "org"), (
                f"scope must be 'project' or 'org', got {agent['scope']!r}"
            )

    def test_agent_budget_field(self, api_home: Path) -> None:
        agents = serve.build_status()["agents"]
        for agent in agents:
            budget = agent["budgetUsd"]
            assert budget is None or isinstance(budget, (int, float)), (
                f"budgetUsd must be float or null, got {type(budget)}"
            )

    def test_agent_kind_field(self, api_home: Path) -> None:
        agents = serve.build_status()["agents"]
        for agent in agents:
            assert agent["kind"] in ("project", "specialist")

    def test_gateway_field_values(self, api_home: Path) -> None:
        st = serve.build_status()
        assert st["gateway"] in ("active", "inactive")

    def test_total_cost_is_float(self, api_home: Path) -> None:
        st = serve.build_status()
        assert isinstance(st["totalCostUsd"], float)

    def test_metrics_stable_names_present(self, api_home: Path) -> None:
        text = serve.render_metrics()
        for name in self.METRIC_NAMES:
            assert name in text, f"Stable metric {name!r} missing from /metrics output"

    def test_metrics_no_trailing_newline(self, api_home: Path) -> None:
        assert not serve.render_metrics().endswith("\n")

    def test_health_shape(self, api_home: Path) -> None:
        body = json.loads(serve.render_health())
        assert set(body.keys()) == {"status", "gateway"}
        assert body["status"] == "ok"
        assert body["gateway"] in (0, 1)


# ── TestSpecDocExists ─────────────────────────────────────────────────────────


class TestSpecDocExists:
    def test_spec_file_exists(self) -> None:
        spec = Path("specs/data/serve-read-api.spec.md")
        assert spec.exists(), "specs/data/serve-read-api.spec.md must exist (CD-8)"

    def test_spec_mentions_api_version(self) -> None:
        spec = Path("specs/data/serve-read-api.spec.md")
        text = spec.read_text(encoding="utf-8")
        assert "apiVersion" in text
        assert serve.SERVE_API_VERSION in text

    def test_spec_mentions_stable_metric_names(self) -> None:
        spec = Path("specs/data/serve-read-api.spec.md")
        text = spec.read_text(encoding="utf-8")
        for name in TestApiContract.METRIC_NAMES:
            assert name in text, f"Spec doc missing metric {name!r}"


# ── TestBudgetInStatusJson ────────────────────────────────────────────────────


class TestBudgetInStatusJson:
    def test_budget_read_from_meta(self, api_home: Path) -> None:
        agents = serve.build_status()["agents"]
        assert len(agents) == 1
        # META has budgetUsd = "5.0" → should appear as float 5.0
        assert agents[0]["budgetUsd"] == 5.0

    def test_no_budget_returns_null(self, api_home: Path, tmp_path: Path) -> None:
        # Overwrite meta without budgetUsd
        ws = api_home / "workspaces" / "projects" / "apitest"
        meta_no_budget = {k: v for k, v in META.items() if k != "budgetUsd"}
        (ws / ".docket-meta.json").write_text(json.dumps(meta_no_budget))
        agents = serve.build_status()["agents"]
        assert agents[0]["budgetUsd"] is None
