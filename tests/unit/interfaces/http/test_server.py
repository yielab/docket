"""The HTTP server's health rendering."""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest
from tests.support import home as _support_home

from docket.interfaces.http import server as http_server
from docket.interfaces.http import sweeps
from docket.interfaces.http.routes import health
from docket.kernel.home import current_home

SUBJECT = "docket.interfaces.http.server"


fake_home = _support_home.fake_home


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
