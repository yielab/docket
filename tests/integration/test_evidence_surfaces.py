"""evidence-v1 surfaces: CLI --json and GET /tasks/<p>/<id>/evidence agree."""

from __future__ import annotations

import dataclasses
import json
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from tests.pods import build_pod
from typer.testing import CliRunner

from docket.cli import _pod, app
from docket.core import dispatch as _dispatch
from docket.core import evidence as _ev
from docket.kernel.home import Home, use_home
from docket.kernel.threads import ContextHTTPServer
from docket.serve import _DocketHandler

SUBJECT = "docket.core.evidence"
_TOKEN = "test-serve-token-evidence-p36-4"


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOCKET_SERVICE_MANAGER", "none")


@contextmanager
def _seed(tmp_path: Path) -> Iterator[str]:
    home = tmp_path / ".docket"
    (home / "workspaces" / "projects").mkdir(parents=True)
    (home / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    approvals = tmp_path / "approvals"
    approvals.mkdir()
    with use_home(dataclasses.replace(Home(home), approvals_dir_override=approvals)):
        build_pod("demo", _pod.pod.DEFAULT_POD_ROLES, codebase="/src/demo")
        task = _dispatch.enqueue_task("demo", "evidence please", channel="cli")
        hop = _dispatch._hop_record(
            _dispatch.HopResult(
                role="implementer",
                member_id="demo-implementer",
                ok=True,
                verify={"cmd": "true", "exitCode": 0, "durationS": 0.1, "outputTail": ""},
            )
        )
        path = _dispatch.pod_task_list_path("demo")
        raw = json.loads(path.read_text())
        for t in raw["tasks"]:
            if t["id"] == task["id"]:
                t["hops"] = [hop]
                t["status"] = "done"
        path.write_text(json.dumps(raw))
        yield str(task["id"])


@pytest.fixture()
def seeded(tmp_path: Path) -> Iterator[str]:
    """The id of a finished task, in a seeded home that stays current for the test."""
    with _seed(tmp_path) as task_id:
        yield task_id


@pytest.fixture()
def server(seeded: str) -> Any:
    """Built after the home is seeded: the server serves the home it was built in."""

    class _Handler(_DocketHandler):
        serve_token = _TOKEN

    srv = ContextHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def _get(url: str, token: str | None = None) -> tuple[int, bytes]:
    req = urllib.request.Request(url)
    if token is not None:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


class TestSurfacesAgree:
    def test_cli_and_http_carry_the_same_document(
        self, capsys: pytest.CaptureFixture[str], server: str, seeded: str
    ) -> None:
        task_id = seeded
        capsys.readouterr()
        shown = CliRunner().invoke(app, ["task", "show", task_id, "--json", "--pod", "demo"])
        assert shown.exit_code == 0, shown.output
        cli_doc = json.loads(shown.output)["evidence"]
        status, http_body = _get(f"{server}/tasks/demo/{task_id}/evidence", _TOKEN)
        assert status == 200
        assert cli_doc == json.loads(http_body)
        assert cli_doc == _ev.task_evidence("demo", task_id, "1.1.0").model_dump(
            by_alias=True, mode="json"
        )
        assert cli_doc["v"] == "1.1.0"


class TestErrors:
    def test_unauthenticated_is_401(self, server: str, seeded: str) -> None:
        assert _get(f"{server}/tasks/demo/{seeded}/evidence")[0] == 401

    def test_unknown_task_is_404_json(self, server: str, seeded: str) -> None:
        status, body = _get(f"{server}/tasks/demo/nope/evidence", _TOKEN)
        assert status == 404
        assert json.loads(body)["ok"] is False

    def test_cli_unknown_task_exits_1(self, seeded: str) -> None:
        result = CliRunner().invoke(app, ["task", "show", "nope", "--pod", "demo"])
        assert result.exit_code == 1

    def test_cli_table_lists_the_hop(self, seeded: str) -> None:
        result = CliRunner().invoke(app, ["task", "show", seeded, "--pod", "demo"])
        assert "implementer" in result.output
