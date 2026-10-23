"""POST /dispatch/<project> answers a pipeline that cannot be resolved instead of dropping the call."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest
from tests.pods import build_pod

from docket.cli import _pod
from docket.core import fleet as _fleet
from docket.core import runs as _runs
from docket.kernel.home import Home, use_home
from docket.kernel.threads import ContextHTTPServer
from docket.serve import _DocketHandler

SUBJECT = "docket.serve"

_TOKEN = "test-serve-token-dispatch-webhook"


@pytest.fixture
def server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    monkeypatch.setenv("DOCKET_SERVICE_MANAGER", "none")
    home = tmp_path / ".docket"
    (home / "workspaces" / "projects").mkdir(parents=True)
    (home / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    with use_home(Home(home)):

        class _Handler(_DocketHandler):
            serve_token = _TOKEN

        srv = ContextHTTPServer(("127.0.0.1", 0), _Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        yield f"http://127.0.0.1:{srv.server_address[1]}"
        srv.shutdown()


def _post(url: str) -> tuple[int, dict]:  # type: ignore[type-arg]
    req = urllib.request.Request(url, data=b"{}", method="POST")
    req.add_header("Authorization", f"Bearer {_TOKEN}")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def test_a_missing_bound_pipeline_copy_is_a_400_and_creates_no_run(server: str) -> None:
    build_pod("demo", _pod.pod.DEFAULT_POD_ROLES, codebase="/src/demo")
    _fleet.meta_set(_pod.pod.member_id("demo", "lead"), "pipeline", "a" * 64)
    status, body = _post(f"{server}/dispatch/demo")
    assert status == 400
    assert "bound pipeline" in body["error"]
    assert _runs.list_runs("demo") == []
