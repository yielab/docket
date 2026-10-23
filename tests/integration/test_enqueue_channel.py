"""Every enqueue and dispatch names its channel in the task record and in the audit log."""

from __future__ import annotations

import json
import threading
import urllib.request
from typing import Any

import pytest
from tests.pods import build_pod
from typer.testing import CliRunner

from docket.governance import audit as _audit
from docket.interfaces.cli.app import app as _app
from docket.interfaces.http.server import _DocketHandler
from docket.interfaces.telegram import bot as _tg
from docket.kernel.threads import ContextHTTPServer
from docket.tasks.application import queue as _queue
from docket.teams import fleet as _fleet

SUBJECT = "docket.core.dispatch"

_TOKEN = "test-serve-token-channel"


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOCKET_SERVICE_MANAGER", "none")


@pytest.fixture()
def live_server():  # type: ignore[no-untyped-def]
    class _Handler(_DocketHandler):
        serve_token = _TOKEN

    srv = ContextHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def _post(url: str, body: dict[str, Any]) -> dict[str, Any]:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST")
    req.add_header("Authorization", f"Bearer {_TOKEN}")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=5) as resp:
        out: dict[str, Any] = json.loads(resp.read())
        return out


def _entries(action: str) -> list[dict[str, Any]]:
    return [e for e in _audit.read_audit() if e.get("action") == action]


def _seed() -> None:
    build_pod("demo", ("lead", "implementer"), codebase="/src/demo")


def test_a_cli_enqueue_records_the_cli_channel() -> None:
    _seed()
    result = CliRunner().invoke(_app, ["task", "add", "fix it", "--pod", "demo"])
    assert result.exit_code == 0, result.output
    task = _queue.read_tasks("demo")[0]
    assert task["channel"] == "cli"
    assert task["source"] == "operator"
    assert "channel=cli" in str(_entries("task.enqueue")[0]["detail"])


def test_an_http_enqueue_records_the_http_channel_and_keeps_source(live_server: str) -> None:
    _seed()
    resp = _post(f"{live_server}/tasks/demo", {"description": "from http"})
    task = _queue.read_tasks("demo")[0]
    assert task["id"] == resp["task"]
    assert task["channel"] == "http"
    assert task["source"] == "operator"
    detail = str(_entries("task.enqueue")[0]["detail"])
    assert "channel=http" in detail and resp["task"] in detail and "demo" in detail


def test_a_telegram_delegate_records_the_telegram_channel() -> None:
    _seed()
    _fleet.upsert_binding("demo-lead", "-100300", "telegram")
    msg = _tg.InboundMessage(chat_id="-100300", user_id="9", text="/delegate do it", update_id=1)
    assert _tg.handle_message(msg).ok
    task = _queue.read_tasks("demo")[0]
    assert task["channel"] == "telegram"
    assert "channel=telegram" in str(_entries("task.enqueue")[0]["detail"])


def test_a_dispatch_post_writes_a_run_dispatch_entry(
    live_server: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("docket.tasks.application.sweep.dispatch_pod", lambda proj, **kw: [])
    resp = _post(f"{live_server}/dispatch/demo", {})
    detail = str(_entries("run.dispatch")[0]["detail"])
    assert resp["run"] in detail and "demo" in detail and "channel=http" in detail


def test_enqueue_requires_a_channel() -> None:
    _seed()
    with pytest.raises(TypeError):
        _queue.enqueue_task_once("demo", "x")  # type: ignore[call-arg]
