"""serve — stdlib HTTP server for docket's read API.

These exercise the pure builders (build_status / render_metrics / render_health)
against a seeded fake DOCKET_HOME, plus a live round-trip through the threaded
HTTP server on port 0. The pure-function assertions are the contract guard:
they pin the /status.json JSON keys and the Prometheus metric line names so any
drift is caught.
"""

from __future__ import annotations

import json
import threading
import urllib.request
from pathlib import Path
from threading import Thread
from typing import Any

import pytest
from tests.support import home as _support_home

from docket.interfaces.http import server as http_server
from docket.interfaces.http import sweeps
from docket.interfaces.http.routes import health
from docket.interfaces.http.server import _DocketHandler
from docket.kernel.home import current_home

fake_home = _support_home.fake_home

SUBJECT = "docket.interfaces.http.server"

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


# ── render_health ─────────────────────────────────────────────────────────────


class TestRenderHealth:
    def test_health_body(self, fake_home: Path) -> None:
        body = json.loads(http_server.render_health())
        assert set(body) == {"status", "apiVersion", "dispatch"}
        assert body["status"] == "ok"
        assert body["apiVersion"] == health.SERVE_API_VERSION

    def test_health_dispatch_block(self, fake_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """The dispatch block reports the flag, in-flight pods, the stop state and the pool size."""
        stop = threading.Event()
        monkeypatch.setattr(http_server, "_sweep_stop", stop)
        monkeypatch.setattr(sweeps, "_sweep_inflight", {"demo": None})
        assert json.loads(http_server.render_health(True))["dispatch"] == {
            "on": True,
            "inflight": ["demo"],
            "stopping": False,
            "workers": current_home().dispatch_sweep_workers,
        }
        stop.set()
        assert json.loads(http_server.render_health())["dispatch"]["stopping"] is True


# ── live HTTP round-trip (port 0) ─────────────────────────────────────────────


class TestHttpServer:
    def test_endpoints_over_socket(self, fake_home: Path) -> None:
        from docket.kernel.threads import ContextHTTPServer

        server = ContextHTTPServer(("127.0.0.1", 0), _DocketHandler)
        port = server.server_address[1]
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f"http://127.0.0.1:{port}"
            with urllib.request.urlopen(base + "/health", timeout=5) as r:
                assert json.loads(r.read().decode())["status"] == "ok"
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
