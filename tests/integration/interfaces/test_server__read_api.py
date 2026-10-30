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

api_home = _support_home.api_home

SUBJECT = "docket.interfaces.http.server"

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


# ── TestStatusJsonPublishesNoPeerIds: the unauthenticated body, live over HTTP ─


class TestStatusJsonPublishesNoPeerIds:
    """The unauthenticated /status.json never carries a channel peer id."""

    def test_unauthenticated_body_omits_peer_id(self, api_home: Path) -> None:
        import threading

        from docket.interfaces.http.server import _DocketHandler
        from docket.kernel.threads import ContextHTTPServer

        fleet = dict(FLEET_CONFIG)
        fleet["bindings"] = [
            {
                "agentId": "apitest",
                "channel": "telegram",
                "peerKind": "group",
                "peerId": "-100123",
            }
        ]
        (api_home / "state").mkdir(parents=True, exist_ok=True)
        (api_home / "state" / "fleet.json").write_text(json.dumps(fleet))

        class _Handler(_DocketHandler):
            serve_token = "test-serve-token-p40-9"

        srv = ContextHTTPServer(("127.0.0.1", 0), _Handler)
        port = srv.server_address[1]
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            import urllib.request

            with urllib.request.urlopen(f"http://127.0.0.1:{port}/status.json", timeout=5) as resp:
                body = resp.read().decode()
        finally:
            srv.shutdown()

        assert "peerId" not in body
        assert "-100123" not in body
        agent = json.loads(body)["agents"][0]
        assert agent["bindings"] == [{"channel": "telegram"}]
