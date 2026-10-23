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

import pytest
from tests.support.pods import build_pod

from docket.kernel.home import Home, use_home

SUBJECT = "docket.interfaces.http.server"


# ── TestInboxEndpoint: GET /inbox, live over HTTP ─────────────────────────────

_INBOX_TEST_TOKEN = "test-serve-token-inbox-p34-6"


@pytest.fixture()
def inbox_live_server(tmp_path: Path):  # type: ignore[no-untyped-def]
    import threading

    from docket.interfaces.http.server import _DocketHandler
    from docket.kernel.threads import ContextHTTPServer

    home = tmp_path / ".docket"
    home.mkdir()
    with use_home(Home(home)):

        class _Handler(_DocketHandler):
            serve_token = _INBOX_TEST_TOKEN

        srv = ContextHTTPServer(("127.0.0.1", 0), _Handler)
        port = srv.server_address[1]
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        yield f"http://127.0.0.1:{port}"
        srv.shutdown()


def _get_json(url: str, token: str | None = None) -> tuple[int, dict[str, Any]]:
    import urllib.error
    import urllib.request

    req = urllib.request.Request(url)
    if token is not None:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


class TestInboxEndpoint:
    def test_no_token_rejected(self, inbox_live_server: str) -> None:
        status, body = _get_json(f"{inbox_live_server}/inbox")
        assert status == 401
        assert body["ok"] is False

    def test_authenticated_call_matches_build_inbox(self, inbox_live_server: str) -> None:

        build_pod("demo", ("lead", "implementer"), codebase="/src/demo")
        from docket.tasks.application import queue as _queue

        _queue.enqueue_task_once("demo", "ship it", channel="cli")

        status, body = _get_json(f"{inbox_live_server}/inbox", token=_INBOX_TEST_TOKEN)

        assert status == 200
        assert set(body.keys()) == {"needsYou", "failed", "doneSince", "running", "next"}

    def test_matches_docket_inbox_json_for_the_same_state(self, inbox_live_server: str) -> None:

        build_pod("demo", ("lead", "implementer"), codebase="/src/demo")
        from docket.tasks.application import queue as _queue

        _queue.enqueue_task_once("demo", "ship it", channel="cli")

        status, http_body = _get_json(f"{inbox_live_server}/inbox", token=_INBOX_TEST_TOKEN)
        assert status == 200

        from typer.testing import CliRunner

        from docket.interfaces.cli.app import app

        result = CliRunner().invoke(app, ["inbox", "--json", "--peek"])
        assert result.exit_code == 0
        cli_body = json.loads(result.stdout)

        assert http_body == cli_body
