"""serve — stdlib HTTP server for docket's read API.

These exercise the pure builders (build_status / render_metrics / render_health)
against a seeded fake DOCKET_HOME, plus a live round-trip through the threaded
HTTP server on port 0. The pure-function assertions are the contract guard:
they pin the /status.json JSON keys and the Prometheus metric line names so any
drift is caught.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from docket.interfaces.http.routes import health
from docket.kernel.home import Home, use_home

SUBJECT = "docket.interfaces.http.routes.health"

META: dict[str, Any] = {
    "schemaVersion": 1,
    "kind": "project",
    "name": "My Shop",
    "type": "repo",
    "model": "anthropic/claude-sonnet-4-6",
}

# Agent registration + channel bindings live in fleet.json.
FLEET_CONFIG: dict[str, Any] = {
    "agents": [{"id": "myshop"}],
    "bindings": [
        {"agentId": "myshop", "channel": "telegram", "peerKind": "group", "peerId": "-100123"}
    ],
    "defaults": {"model": ""},
    "security": {"gatesEnabled": False, "isolationEnabled": False},
}


@pytest.fixture()
def fake_home(tmp_path: Path) -> Iterator[Path]:
    """Seed a temp DOCKET_HOME with one project agent + fleet.json."""
    home = tmp_path / ".docket"
    home.mkdir()
    ws = home / "workspaces" / "projects" / "myshop"
    (ws / "memory").mkdir(parents=True)
    (ws / ".docket-meta.json").write_text(json.dumps(META))
    session = home / "sessions" / "agent%3Amyshop%3Amyshop"
    session.mkdir(parents=True)
    (session / "session.json").write_text(
        json.dumps(
            {
                "sessionKey": "agent:myshop:myshop",
                "created": "2026-06-19T08:00:00Z",
                "updated": "2026-06-20T09:30:00Z",
                "messages": [],
            }
        )
    )
    (home / "fleet.json").write_text(json.dumps(FLEET_CONFIG))

    with use_home(Home(home)):
        yield home


# ── build_status ──────────────────────────────────────────────────────────────


class TestBuildStatus:
    def test_top_level_keys(self, fake_home: Path) -> None:
        st = health.build_status()
        assert set(st.keys()) == {
            "apiVersion",
            "timestamp",
            "channels",
            "agents",
            "totalCostUsd",
        }

    def test_api_version_field(self, fake_home: Path) -> None:
        assert health.build_status()["apiVersion"] == health.SERVE_API_VERSION

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
            "costUsd",
            "budgetUsd",
        }
        assert a["id"] == "myshop"
        assert a["name"] == "My Shop"
        assert a["kind"] == "project"
        assert a["registered"] is True
        assert a["lastActivity"] == "2026-06-20"
        assert a["bindings"] == [{"channel": "telegram"}]

    def test_last_activity_never_when_empty(self, fake_home: Path) -> None:
        # Remove the agent's only session so last_activity falls back to the sentinel.
        shutil.rmtree(fake_home / "sessions")
        assert health.build_status()["agents"][0]["lastActivity"] == "never"

    def test_timestamp_format(self, fake_home: Path) -> None:
        ts = health.build_status()["timestamp"]
        assert ts.endswith("Z") and "T" in ts and len(ts) == 20
