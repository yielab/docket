"""M5 tests: serve — stdlib HTTP server port of lib/commands/serve.sh.

These exercise the pure builders (build_status / render_metrics / render_health)
against a seeded fake OPENCLAW_DIR, plus a live round-trip through the threaded
HTTP server on port 0. The pure-function assertions are the contract guard:
they pin the /status.json JSON keys and the Prometheus metric line names so any
drift from serve.sh is caught.
"""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path
from threading import Thread
from typing import Any

import pytest

import docket.config as _cfg
import docket.edges.adapters.openclaw as _oc
import docket.serve as serve
from docket.serve import _DocketHandler

META: dict[str, Any] = {
    "schemaVersion": 1,
    "kind": "project",
    "name": "My Shop",
    "type": "repo",
    "model": "anthropic/claude-sonnet-4-6",
    "modelSource": "policy",
}

OC_CONFIG: dict[str, Any] = {
    "agents": {
        "defaults": {"model": ""},
        "list": [
            {
                "id": "myshop",
                "model": "anthropic/claude-sonnet-4-6",
                "metadata": {"sessionKey": "agent:myshop:default", "projectKey": "default"},
            }
        ],
    },
    "bindings": [
        {
            "agentId": "myshop",
            "match": {"channel": "telegram", "peer": {"kind": "group", "id": "-100123"}},
        }
    ],
    "channels": {"telegram": {"enabled": True}},
    "security": {"gates": {"enabled": False}, "isolation": {"enabled": False}},
}


@pytest.fixture()
def fake_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Seed a temp OPENCLAW_DIR with one project agent + openclaw.json."""
    oc_dir = tmp_path / ".openclaw"
    oc_dir.mkdir()
    ws = oc_dir / "workspaces" / "projects" / "myshop"
    (ws / "memory").mkdir(parents=True)
    (ws / ".docket-meta.json").write_text(json.dumps(META))
    (ws / "memory" / "2026-06-20.md").write_text("# log\n")
    (oc_dir / "openclaw.json").write_text(json.dumps(OC_CONFIG))

    config_file = oc_dir / "openclaw.json"
    monkeypatch.setenv("OPENCLAW_DIR", str(oc_dir))
    monkeypatch.setattr(_cfg, "OPENCLAW_DIR", oc_dir)
    monkeypatch.setattr(_cfg, "CONFIG_FILE", config_file)
    monkeypatch.setattr(_cfg, "PROJECTS_DIR", oc_dir / "workspaces" / "projects")
    monkeypatch.setattr(_oc, "CONFIG_FILE", config_file)
    # Force gateway "down" for deterministic gateway fields.
    monkeypatch.setattr(serve.utils, "gateway_active", lambda: False)
    return oc_dir


# ── build_status ──────────────────────────────────────────────────────────────


class TestBuildStatus:
    def test_top_level_keys(self, fake_home: Path) -> None:
        st = serve.build_status()
        assert set(st.keys()) == {
            "timestamp",
            "gateway",
            "channels",
            "agents",
            "totalCostUsd",
        }

    def test_gateway_inactive_string(self, fake_home: Path) -> None:
        assert serve.build_status()["gateway"] == "inactive"

    def test_channels_from_acl(self, fake_home: Path) -> None:
        assert serve.build_status()["channels"] == ["telegram"]

    def test_agent_record_shape(self, fake_home: Path) -> None:
        agents = serve.build_status()["agents"]
        assert len(agents) == 1
        a = agents[0]
        assert set(a.keys()) == {
            "id",
            "name",
            "type",
            "kind",
            "model",
            "registered",
            "bindings",
            "lastActivity",
            "costUsd",
        }
        assert a["id"] == "myshop"
        assert a["name"] == "My Shop"
        assert a["type"] == "repo"
        assert a["kind"] == "project"
        assert a["registered"] is True
        assert a["lastActivity"] == "2026-06-20"
        assert a["bindings"] == [{"channel": "telegram", "peerId": "-100123"}]

    def test_last_activity_never_when_empty(
        self, fake_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Remove the memory log so last_activity falls back to the sentinel.
        (fake_home / "workspaces" / "projects" / "myshop" / "memory" / "2026-06-20.md").unlink()
        assert serve.build_status()["agents"][0]["lastActivity"] == "never"

    def test_timestamp_format(self, fake_home: Path) -> None:
        ts = serve.build_status()["timestamp"]
        assert ts.endswith("Z") and "T" in ts and len(ts) == 20


# ── render_metrics ────────────────────────────────────────────────────────────


class TestRenderMetrics:
    def test_metric_names_present(self, fake_home: Path) -> None:
        text = serve.render_metrics()
        for name in (
            "docket_agents_total",
            "docket_agent_cost_usd",
            "docket_agent_turns_total",
            "docket_cost_usd_total",
            "docket_gateway_up",
        ):
            assert name in text

    def test_help_and_type_headers(self, fake_home: Path) -> None:
        text = serve.render_metrics()
        assert "# HELP docket_agents_total Number of project agents" in text
        assert "# TYPE docket_agents_total gauge" in text
        assert "# HELP docket_gateway_up Gateway service active (1) or not (0)" in text

    def test_agents_total_and_gateway_value(self, fake_home: Path) -> None:
        lines = serve.render_metrics().splitlines()
        assert "docket_agents_total 1" in lines
        assert "docket_gateway_up 0" in lines

    def test_per_agent_labels(self, fake_home: Path) -> None:
        lines = serve.render_metrics().splitlines()
        cost_line = next(line for line in lines if line.startswith("docket_agent_cost_usd{"))
        assert 'agent="myshop"' in cost_line
        assert 'model="anthropic/claude-sonnet-4-6"' in cost_line
        turns_line = next(line for line in lines if line.startswith("docket_agent_turns_total{"))
        assert 'agent="myshop"' in turns_line

    def test_no_trailing_newline(self, fake_home: Path) -> None:
        assert not serve.render_metrics().endswith("\n")


# ── render_health ─────────────────────────────────────────────────────────────


class TestRenderHealth:
    def test_health_down(self, fake_home: Path) -> None:
        assert serve.render_health() == '{"status":"ok","gateway":0}\n'

    def test_health_up(self, fake_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(serve.utils, "gateway_active", lambda: True)
        assert serve.render_health() == '{"status":"ok","gateway":1}\n'


# ── live HTTP round-trip (port 0) ─────────────────────────────────────────────


class TestHttpServer:
    def test_endpoints_over_socket(self, fake_home: Path) -> None:
        from http.server import ThreadingHTTPServer

        server = ThreadingHTTPServer(("127.0.0.1", 0), _DocketHandler)
        port = server.server_address[1]
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f"http://127.0.0.1:{port}"
            with urllib.request.urlopen(base + "/health", timeout=5) as r:
                assert json.loads(r.read().decode()) == {"status": "ok", "gateway": 0}
            with urllib.request.urlopen(base + "/status.json", timeout=5) as r:
                status = json.loads(r.read().decode())
                assert status["agents"][0]["id"] == "myshop"
            with urllib.request.urlopen(base + "/metrics", timeout=5) as r:
                metrics = r.read().decode()
                assert metrics.startswith("# HELP docket_agents_total")
                assert metrics.endswith("\n")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
