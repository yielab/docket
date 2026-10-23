"""POST /pods/<p>/apply -- applying a reviewed directory over HTTP, with the review code."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
from tests.conftest import repoint_docket_home

import docket.config as _cfg
from docket.core import audit as _audit
from docket.core import fleet as _fleet
from docket.serve import _DocketHandler

SUBJECT = "docket.core"

_TOKEN = "test-serve-token-pods-config"


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOCKET_SERVICE_MANAGER", "none")


@pytest.fixture()
def server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    home = tmp_path / ".docket"
    (home / "workspaces" / "projects").mkdir(parents=True)
    (home / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    (home / "approvals").mkdir()
    repoint_docket_home(monkeypatch, home)

    class _Handler(_DocketHandler):
        serve_token = _TOKEN

    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}"
    codebase = tmp_path / "codebase"
    codebase.mkdir()
    status, _ = _post(f"{url}/pods", {"name": "demo", "location": str(codebase)})
    assert status == 201
    yield url
    srv.shutdown()


def _post(
    url: str, body: dict[str, Any] | None = None, token: str | None = _TOKEN
) -> tuple[int, dict[str, Any]]:
    data = json.dumps(body or {}).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    if token is not None:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def _directory(root: Path, name: str, files: dict[str, str]) -> Path:
    directory = root / name
    for rel, text in files.items():
        path = directory / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return directory


_ROLE = {
    "roles/x-checker.yaml": "kind: role\nname: x-checker\nmodel: cheap\ndescription: x\ncannot: [write]\n",
    "roles/x-checker.md": "Check.",
}
_RUNS = {"pod.yaml": "kind: pod\nname: x\nsettings:\n  allowCommands: [make]\n"}


def _roles(project: str) -> dict[str, Any]:
    path = _cfg.pod_config_dir(project) / "roles.json"
    return json.loads(path.read_text()).get("roles", {}) if path.is_file() else {}


def test_apply_over_http_needs_the_review_code_for_run_items(server: str, tmp_path: Path) -> None:
    """A directory that runs commands is 409 with its code, then applies with that code."""
    directory = _directory(tmp_path, "runs", _RUNS)
    status, body = _post(f"{server}/pods/demo/apply", {"directory": str(directory)})
    assert status == 409
    assert body["runs"][0]["kind"] == "allow-commands"
    code = body["reviewCode"]
    lead = "demo-lead"
    assert _fleet.meta_get(lead, "configSource", "") == ""
    status, _ = _post(
        f"{server}/pods/demo/apply", {"directory": str(directory), "accept": "0" * 16}
    )
    assert status == 409
    assert _fleet.meta_get(lead, "configSource", "") == ""
    status, body = _post(f"{server}/pods/demo/apply", {"directory": str(directory), "accept": code})
    assert status == 200
    assert body["dryRun"] is False
    assert _fleet.meta_get(lead, "configSource", "") == str(directory.resolve())


def test_apply_one_role_records_the_source_and_audits_the_channel(
    server: str, tmp_path: Path
) -> None:
    """A role-only directory applies, records configSource and audits channel=http."""
    directory = _directory(tmp_path, "roles", _ROLE)
    status, body = _post(f"{server}/pods/demo/apply", {"directory": str(directory)})
    assert status == 200
    assert body["ok"] is True and body["dryRun"] is False
    assert [(i["kind"], i["name"], i["action"]) for i in body["items"]] == [
        ("role", "x-checker", "add")
    ]
    assert "x-checker" in _roles("demo")
    assert _fleet.meta_get("demo-lead", "configSource", "") == str(directory.resolve())
    entries = [e for e in _audit.read_audit() if e.get("action") == "pod.apply"]
    assert entries and "channel=http" in str(entries[-1])


def test_dry_run_writes_nothing(server: str, tmp_path: Path) -> None:
    """dryRun answers the plan and changes nothing, even for a directory that runs commands."""
    directory = _directory(tmp_path, "both", {**_ROLE, **_RUNS})
    status, body = _post(f"{server}/pods/demo/apply", {"directory": str(directory), "dryRun": True})
    assert status == 200
    assert body["dryRun"] is True and body["items"]
    assert "x-checker" not in _roles("demo")
    assert _fleet.meta_get("demo-lead", "configSource", "") == ""


def test_a_refused_shell_is_409_without_a_code(server: str, tmp_path: Path) -> None:
    """A directory allowing a shell is refused and offers no review code."""
    directory = _directory(
        tmp_path, "shell", {"pod.yaml": "kind: pod\nname: x\nsettings:\n  allowCommands: [bash]\n"}
    )
    status, body = _post(f"{server}/pods/demo/apply", {"directory": str(directory)})
    assert status == 409
    assert "reviewCode" not in body


def test_bad_requests(server: str, tmp_path: Path) -> None:
    """Relative or missing directory is 400, unknown pod 404, no token 401."""
    assert _post(f"{server}/pods/demo/apply", {"directory": "relative/dir"})[0] == 400
    assert _post(f"{server}/pods/demo/apply", {"directory": str(tmp_path / "nope")})[0] == 400
    directory = _directory(tmp_path, "roles", _ROLE)
    assert _post(f"{server}/pods/ghost/apply", {"directory": str(directory)})[0] == 404
    assert _post(f"{server}/pods/demo/apply", {"directory": str(directory)}, token=None)[0] == 401
    assert _post(f"{server}/pods/demo/apply", {"directory": str(directory)}, token="bad")[0] == 401


def test_an_unknown_pod_is_404_before_the_body_is_read(server: str) -> None:
    """The pod is looked up before the body is parsed: a bad body to a pod that is not there is
    the pod's 404, not the body's 400."""
    req = urllib.request.Request(f"{server}/pods/ghost/apply", data=b"{not json", method="POST")
    req.add_header("Authorization", f"Bearer {_TOKEN}")
    with pytest.raises(urllib.error.HTTPError) as caught:
        urllib.request.urlopen(req, timeout=10)
    assert caught.value.code == 404
    assert json.loads(caught.value.read())["error"] == "Unknown pod: ghost"


def test_the_default_directory_is_the_pods_team_dir(server: str, tmp_path: Path) -> None:
    """Without `directory`, apply reads `.docket/teams/<pod>/` when the repository keeps teams."""
    _directory(tmp_path / "codebase" / ".docket" / "teams", "demo", _ROLE)
    status, _ = _post(f"{server}/pods/demo/apply", {})
    assert status == 200 and "x-checker" in _roles("demo")
    assert _fleet.meta_get("demo-lead", "configSource", "").endswith("teams/demo")


def test_a_pod_with_no_recorded_codebase_is_refused(server: str, tmp_path: Path) -> None:
    """A pod with no codebase meta is 400 and is never reviewed against the directory's parent."""
    _fleet.meta_set("demo-lead", "codebase", "")
    directory = _directory(tmp_path, "runs-nocb", _RUNS)
    status, body = _post(f"{server}/pods/demo/apply", {"directory": str(directory)})
    assert status == 400
    assert "no recorded codebase" in body["error"]
    assert "reviewCode" not in body
