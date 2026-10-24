"""GET /inbox and `inbox --json` carry a parked consultation's v1.1 question fields."""

from __future__ import annotations

import json
import threading
import urllib.request
from pathlib import Path
from typing import Any

import jsonschema
import pytest
from tests.support.pods import build_pod
from typer.testing import CliRunner

from docket.interfaces.cli.app import app as _app
from docket.interfaces.http.server import _DocketHandler
from docket.kernel.home import Home, use_home
from docket.kernel.threads import ContextHTTPServer
from docket.platform import store as _store
from docket.teams import settings as _settings

SUBJECT = "docket.interfaces.http.server"

_TOKEN = "test-serve-token-inbox-options"
_SCHEMA = Path(__file__).resolve().parents[3] / "docs/contracts/operator-v1/inbox.schema.json"

_QUESTION = {
    "id": "q-1",
    "taskId": "task-q",
    "pod": "demo",
    "step": "implementer",
    "message": "Which store?",
    "requestedSchema": {
        "type": "object",
        "properties": {"answer": {"type": "string"}},
        "required": [],
    },
    "createdAt": "2026-10-19T00:00:00+00:00",
    "expiresAt": None,
    "kind": "decision",
    "options": [
        {"id": "redis", "label": "Redis", "description": "fast"},
        {"id": "sqlite", "label": "SQLite", "description": "simple"},
    ],
    "recommendation": {"optionId": "sqlite", "rationale": "no new service"},
}


@pytest.fixture()
def server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    home = tmp_path / ".docket"
    (home / "workspaces" / "projects").mkdir(parents=True)
    (home / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    with use_home(Home(home)):
        build_pod("demo", ("lead", "implementer"), codebase="/src/demo")
        task = {
            "id": "task-q",
            "status": "waiting_input",
            "description": "ship it",
            "created": "2026-10-19T00:00:00+00:00",
            "question": _QUESTION,
        }
        _store.write_json(_settings.pod_task_list_path("demo"), {"tasks": [task]})

        class _Handler(_DocketHandler):
            serve_token = _TOKEN

        srv = ContextHTTPServer(("127.0.0.1", 0), _Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        yield f"http://127.0.0.1:{srv.server_address[1]}"
        srv.shutdown()


def _http_item(base: str) -> dict[str, Any]:
    req = urllib.request.Request(f"{base}/inbox", headers={"Authorization": f"Bearer {_TOKEN}"})
    with urllib.request.urlopen(req, timeout=5) as resp:
        body = json.loads(resp.read())
    jsonschema.validate(body, json.loads(_SCHEMA.read_text(encoding="utf-8")))
    (item,) = body["needsYou"]
    return item  # type: ignore[no-any-return]


def test_the_http_inbox_item_carries_kind_options_and_recommendation(server: str) -> None:
    question = _http_item(server)["question"]

    assert question["kind"] == "decision"
    assert [(o["id"], o["label"]) for o in question["options"]] == [
        ("redis", "Redis"),
        ("sqlite", "SQLite"),
    ]
    assert question["recommendation"]["optionId"] == "sqlite"


def test_inbox_json_carries_the_same_question_as_http(server: str) -> None:
    result = CliRunner().invoke(_app, ["inbox", "--json", "--peek"])

    assert result.exit_code == 0, result.output
    cli_item = json.loads(result.output)["needsYou"][0]
    assert cli_item["question"] == _http_item(server)["question"]
