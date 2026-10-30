"""A task parked on a ``wait`` step over the HTTP API: its escalation is listed and settled by
``resume``, and neither it nor the task is ever a ``needsYou`` item."""

from __future__ import annotations

import json
import threading
import urllib.error
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
from docket.kernel import clock as _clock
from docket.kernel.home import Home, use_home
from docket.kernel.threads import ContextHTTPServer
from docket.tasks.application import escalations as _escalations
from docket.tasks.domain.task import TaskWait

SUBJECT = "docket.interfaces.http.server"

_TOKEN = "test-serve-token-wait"
_SCHEMA = Path(__file__).resolve().parents[3] / "docs/contracts/operator-v2/inbox.schema.json"


@pytest.fixture()
def server(tmp_path: Path):  # type: ignore[no-untyped-def]
    home = tmp_path / ".docket"
    (home / "workspaces" / "projects").mkdir(parents=True)
    (home / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    with use_home(Home(home)):
        build_pod("demo", ("lead", "implementer"), codebase="/src/demo")
        due = "2999-01-01T00:00:00+00:00"
        put_task(
            "demo",
            task(
                id="task-w",
                status="waiting_input",
                description="wait for the deploy",
                created=_clock.iso(),
                wait=TaskWait(step="hold", dueAt=due),
            ),
        )
        _escalations.open_for_wait(
            pod="demo", task_id="task-w", step="hold", prompt="waiting", due_at=due
        )

        class _Handler(_DocketHandler):
            serve_token = _TOKEN

        srv = ContextHTTPServer(("127.0.0.1", 0), _Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        yield f"http://127.0.0.1:{srv.server_address[1]}"
        srv.shutdown()


def _call(base: str, method: str, path: str, body: Any = None) -> tuple[int, Any]:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(
        f"{base}{path}",
        data=data,
        method=method,
        headers={"Authorization": f"Bearer {_TOKEN}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or b"{}")


def test_the_inbox_lists_the_wait_under_escalations_and_not_under_needs_you(server: str) -> None:
    status, body = _call(server, "GET", "/inbox")

    assert status == 200
    jsonschema.validate(body, json.loads(_SCHEMA.read_text(encoding="utf-8")))
    assert body["needsYou"] == []
    assert body["running"] == []
    (wait,) = body["escalations"]
    assert (wait["kind"], wait["policy"], wait["step"]) == ("wait", "machine", "hold")
    assert wait["affordances"]["options"] == ["resume"]


def test_the_cli_inbox_peek_agrees(server: str) -> None:
    result = CliRunner().invoke(_app, ["inbox", "--json", "--peek"])

    assert result.exit_code == 0, result.output
    cli = json.loads(result.output)
    assert cli["needsYou"] == []
    assert [e["kind"] for e in cli["escalations"]] == ["wait"]
    assert cli["escalations"][0]["command"].endswith("--option resume")


def test_the_cli_inbox_offers_no_approval_for_a_wait(server: str) -> None:
    result = CliRunner().invoke(_app, ["inbox", "--peek"])

    assert result.exit_code == 0, result.output
    assert "approve" not in result.output.lower()


def test_the_task_record_lists_its_wait_escalation(server: str) -> None:
    _status, listed = _call(server, "GET", "/escalations?task=task-w")
    (wait,) = listed["escalations"]

    status, shown = _call(server, "GET", "/tasks/demo/task-w")

    assert status == 200
    assert shown["status"] == "waiting_input"
    assert shown["escalations"] == [wait["id"]]


def test_resume_settles_the_wait_and_reopens_the_task(server: str) -> None:
    _status, listed = _call(server, "GET", "/escalations?task=task-w")
    (wait,) = listed["escalations"]

    status, resolved = _call(
        server, "POST", f"/escalations/{wait['id']}", {"optionId": "resume", "actor": "ci"}
    )

    assert status == 200
    assert resolved["state"] == "resolved"
    assert resolved["resolution"]["optionId"] == "resume"
    _status, shown = _call(server, "GET", "/tasks/demo/task-w")
    assert shown["status"] == "pending"
    again, _body = _call(server, "POST", f"/escalations/{wait['id']}", {"optionId": "resume"})
    assert again == 409


def test_any_other_option_is_unprocessable(server: str) -> None:
    _status, listed = _call(server, "GET", "/escalations?task=task-w")
    (wait,) = listed["escalations"]

    status, _body = _call(server, "POST", f"/escalations/{wait['id']}", {"optionId": "deny"})

    assert status == 422
