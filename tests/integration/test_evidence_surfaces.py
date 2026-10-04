"""evidence-v1 surfaces: CLI --json, GET /tasks/<p>/<id>/evidence and the harness result agree."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
import typer
from tests.conftest import repoint_docket_home

import docket.config as _cfg
from docket.cli import _harness_recipe, _pod
from docket.core import dispatch as _dispatch
from docket.core import evidence as _ev
from docket.core import harness_pipeline as _hp
from docket.serve import _DocketHandler

SUBJECT = "docket.core.evidence"
_TOKEN = "test-serve-token-evidence-p36-4"


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOCKET_SERVICE_MANAGER", "none")


def _seed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    home = tmp_path / ".docket"
    (home / "workspaces" / "projects").mkdir(parents=True)
    (home / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    repoint_docket_home(monkeypatch, home)
    approvals = tmp_path / "approvals"
    approvals.mkdir()
    monkeypatch.setattr(_cfg, "APPROVALS_DIR", approvals, raising=True)
    _pod.build_pod("demo", _pod.pod.DEFAULT_POD_ROLES, codebase="/src/demo")
    task = _dispatch.enqueue_task("demo", "evidence please")
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
    return str(task["id"])


@pytest.fixture()
def server() -> Any:
    class _Handler(_DocketHandler):
        serve_token = _TOKEN

    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
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
    def test_cli_http_and_harness_carry_the_same_document(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        server: str,
    ) -> None:
        task_id = _seed(tmp_path, monkeypatch)
        capsys.readouterr()
        _pod._pod_evidence("demo", [task_id, "--json"])
        cli_out = capsys.readouterr().out.strip()
        status, http_body = _get(f"{server}/tasks/demo/{task_id}/evidence", _TOKEN)
        assert status == 200
        assert cli_out.encode() == http_body.strip()
        run = _hp.RecipeRun(project="demo", task={"id": task_id}, hops=[])
        harness_doc = _harness_recipe._task_evidence(run)
        assert json.loads(cli_out) == json.loads(http_body) == harness_doc
        assert json.loads(cli_out) == _ev.task_evidence("demo", task_id).model_dump(
            by_alias=True, mode="json"
        )

    def test_harness_block_is_none_without_a_run(self) -> None:
        assert _harness_recipe._task_evidence(None) is None


class TestErrors:
    def test_unauthenticated_is_401(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, server: str
    ) -> None:
        task_id = _seed(tmp_path, monkeypatch)
        assert _get(f"{server}/tasks/demo/{task_id}/evidence")[0] == 401

    def test_unknown_task_is_404_json(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, server: str
    ) -> None:
        _seed(tmp_path, monkeypatch)
        status, body = _get(f"{server}/tasks/demo/nope/evidence", _TOKEN)
        assert status == 404
        assert json.loads(body)["ok"] is False

    def test_cli_unknown_task_exits_1(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed(tmp_path, monkeypatch)
        with pytest.raises(typer.Exit) as exc:
            _pod._pod_evidence("demo", ["nope"])
        assert exc.value.exit_code == 1

    def test_cli_table_lists_the_hop(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        task_id = _seed(tmp_path, monkeypatch)
        _pod._pod_evidence("demo", [task_id])
        assert "implementer" in capsys.readouterr().out
