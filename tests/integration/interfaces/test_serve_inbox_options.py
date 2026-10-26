"""GET /inbox and `inbox --json` carry a parked consultation as an escalation with its options."""

from __future__ import annotations

import json
import threading
import urllib.request
from pathlib import Path
from typing import Any

import jsonschema
import pytest
from tests.support.pods import build_pod
from tests.support.tasks import put_task, task
from typer.testing import CliRunner

from docket.interfaces.cli.app import app as _app
from docket.interfaces.http.server import _DocketHandler
from docket.kernel.home import Home, use_home
from docket.kernel.operator_contract import QuestionV11
from docket.kernel.threads import ContextHTTPServer
from docket.tasks.application import escalations as _escalations

SUBJECT = "docket.interfaces.http.server"

_TOKEN = "test-serve-token-inbox-options"
_SCHEMA = Path(__file__).resolve().parents[3] / "docs/contracts/operator-v2/inbox.schema.json"

_QUESTION = QuestionV11.model_validate(
    {
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
)


@pytest.fixture()
def server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    home = tmp_path / ".docket"
    (home / "workspaces" / "projects").mkdir(parents=True)
    (home / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    with use_home(Home(home)):
        build_pod("demo", ("lead", "implementer"), codebase="/src/demo")
        put_task(
            "demo",
            task(
                id="task-q",
                status="waiting_input",
                description="ship it",
                created="2026-10-19T00:00:00+00:00",
            ),
        )
        _escalations.open_for_question(
            _QUESTION, kind="consult", role="implementer", caused_by="c1"
        )

        class _Handler(_DocketHandler):
            serve_token = _TOKEN

        srv = ContextHTTPServer(("127.0.0.1", 0), _Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        yield f"http://127.0.0.1:{srv.server_address[1]}"
        srv.shutdown()


def _http_inbox(base: str) -> dict[str, Any]:
    req = urllib.request.Request(f"{base}/inbox", headers={"Authorization": f"Bearer {_TOKEN}"})
    with urllib.request.urlopen(req, timeout=5) as resp:
        body = json.loads(resp.read())
    jsonschema.validate(body, json.loads(_SCHEMA.read_text(encoding="utf-8")))
    return body  # type: ignore[no-any-return]


def test_the_http_inbox_item_names_its_escalation_which_carries_the_options(server: str) -> None:
    body = _http_inbox(server)

    (item,) = body["needsYou"]
    (escalation,) = body["escalations"]
    assert item["escalation"] == escalation["id"]
    assert "question" not in item and "approvalToken" not in item
    assert escalation["kind"] == "consult"
    assert [(o["id"], o["label"]) for o in escalation["options"]] == [
        ("redis", "Redis"),
        ("sqlite", "SQLite"),
        ("decline", "Decline"),
    ]
    assert escalation["recommendation"]["optionId"] == "sqlite"


def test_inbox_json_carries_the_same_escalation_as_http(server: str) -> None:
    result = CliRunner().invoke(_app, ["inbox", "--json", "--peek"])

    assert result.exit_code == 0, result.output
    cli = json.loads(result.output)
    http = _http_inbox(server)
    assert cli["needsYou"][0]["escalation"] == http["needsYou"][0]["escalation"]
    assert [e["id"] for e in cli["escalations"]] == [e["id"] for e in http["escalations"]]
