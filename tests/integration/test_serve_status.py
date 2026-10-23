"""GET /status.json reports the API version the routes are served under."""

from __future__ import annotations

import json
import threading
import urllib.request
from pathlib import Path

import pytest

import docket.config as _cfg
from docket.kernel.home import Home, use_home
from docket.kernel.threads import ContextHTTPServer
from docket.serve import _DocketHandler

SUBJECT = "docket.serve"

_TOKEN = "test-serve-token-status"


@pytest.fixture()
def live_server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    with use_home(Home(tmp_path / ".docket")):
        (tmp_path / ".docket").mkdir(exist_ok=True)
        approvals_dir = tmp_path / "approvals"
        approvals_dir.mkdir()
        monkeypatch.setattr(_cfg, "APPROVALS_DIR", approvals_dir, raising=True)

        class _Handler(_DocketHandler):
            serve_token = _TOKEN

        srv = ContextHTTPServer(("127.0.0.1", 0), _Handler)
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        yield f"http://127.0.0.1:{srv.server_address[1]}"
        srv.shutdown()


def test_api_version_is_5(live_server: str) -> None:
    """/status.json carries apiVersion 6."""
    req = urllib.request.Request(f"{live_server}/status.json")
    req.add_header("Authorization", f"Bearer {_TOKEN}")
    with urllib.request.urlopen(req, timeout=5) as resp:
        body = json.loads(resp.read())

    assert body["apiVersion"] == "6"
