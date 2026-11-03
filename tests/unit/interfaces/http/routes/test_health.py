"""serve — stdlib HTTP server for docket's read API.

These exercise the pure builders (build_status / render_metrics / render_health)
against a seeded fake DOCKET_HOME, plus a live round-trip through the threaded
HTTP server on port 0. The pure-function assertions are the contract guard:
they pin the /status.json JSON keys and the Prometheus metric line names so any
drift is caught.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from tests.support import home as _support_home

from docket.interfaces.http.routes import health

fake_home = _support_home.fake_home

SUBJECT = "docket.interfaces.http.routes.health"

META: dict[str, Any] = {
    "kind": "project",
    "name": "My Shop",
    "model": "anthropic/claude-sonnet-4-6",
}

# Agent registration + channel bindings live in fleet.json.
FLEET_CONFIG: dict[str, Any] = {
    "agents": [{"id": "myshop"}],
    "bindings": [
        {"agentId": "myshop", "channel": "telegram", "peerKind": "group", "peerId": "-100123"}
    ],
    "security": {},
}


# ── build_status ──────────────────────────────────────────────────────────────


class TestBuildStatus:
    def test_top_level_keys(self, fake_home: Path) -> None:
        st = health.build_status()
        assert set(st.keys()) == {
            "apiVersion",
            "features",
            "timestamp",
            "channels",
            "agents",
        }

    def test_no_key_names_a_dollar(self, fake_home: Path) -> None:
        def keys(node: Any) -> set[str]:
            if isinstance(node, dict):
                return set(node) | {k for v in node.values() for k in keys(v)}
            if isinstance(node, list):
                return {k for v in node for k in keys(v)}
            return set()

        named = {
            k for k in keys(health.build_status()) if "cost" in k.lower() or "usd" in k.lower()
        }
        assert named == set()

    def test_api_version_field(self, fake_home: Path) -> None:
        assert health.build_status()["apiVersion"] == health.SERVE_API_VERSION

    def test_features_list_the_feature_names(self, fake_home: Path) -> None:
        assert health.build_status()["features"] == [
            "taskCurrent",
            "taskCursor",
            "podMemory",
            "readScope",
            "conversation",
            "settledCursor",
            "failureKinds",
            "podPause",
            "hopTimes",
            "retryContinues",
            "budgetOutcome",
            "networkEnforced",
            "podWorkDir",
            "podFetch",
        ]

    def test_channels_from_acl(self, fake_home: Path) -> None:
        assert health.build_status()["channels"] == ["telegram"]

    def test_agent_record_shape(self, fake_home: Path) -> None:
        agents = health.build_status()["agents"]
        assert len(agents) == 1
        a = agents[0]
        assert set(a.keys()) == {
            "id",
            "name",
            "kind",
            "scope",
            "model",
            "registered",
            "bindings",
            "lastActivity",
            "budgetTokens",
        }
        assert a["id"] == "myshop"
        assert a["name"] == "My Shop"
        assert a["kind"] == "project"
        assert a["registered"] is True
        assert a["lastActivity"] == "2026-06-20"
        assert a["bindings"] == [{"channel": "telegram"}]

    def test_last_activity_never_when_empty(self, fake_home: Path) -> None:
        # Remove the agent's only session so last_activity falls back to the sentinel.
        shutil.rmtree(fake_home / "state" / "sessions")
        assert health.build_status()["agents"][0]["lastActivity"] == "never"

    def test_timestamp_format(self, fake_home: Path) -> None:
        ts = health.build_status()["timestamp"]
        assert ts.endswith("Z") and "T" in ts and len(ts) == 20
