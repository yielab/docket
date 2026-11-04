"""POST /pods/<p>/apply -- applying a reviewed directory over HTTP, with the review code."""

from __future__ import annotations

import json
import os
import shutil
import threading
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

import docket.kernel.templates as _templates
from docket.governance import audit as _audit
from docket.hops.application import report as _pod_report
from docket.interfaces.http.server import _DocketHandler
from docket.kernel.home import Home, use_home
from docket.kernel.threads import ContextHTTPServer
from docket.sandbox.launch import Launcher
from docket.teams import fleet as _fleet
from docket.teams import roles as _arch

SUBJECT = "docket.interfaces.http.server"

_TOKEN = "test-serve-token-pods-config"


@pytest.fixture()
def jail_probes() -> dict[str, bool]:
    """The sandbox backends the machine answers to; a test overrides it by parametrizing."""
    return {"landlock": True}


@pytest.fixture()
def server(  # type: ignore[no-untyped-def]
    tmp_path: Path, bind_launcher: Callable[..., Launcher], jail_probes: dict[str, bool]
):
    bind_launcher(**jail_probes)
    home = tmp_path / ".docket"
    (home / "state" / "workspaces" / "projects").mkdir(parents=True)
    (home / "state" / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    (home / "state" / "approvals").mkdir()
    with use_home(Home(home)):

        class _Handler(_DocketHandler):
            serve_token = _TOKEN

        srv = ContextHTTPServer(("127.0.0.1", 0), _Handler)
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


def _roles(project: str) -> set[str]:
    return set(_arch.load_registry(project).role_names())


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


class TestApplyToAFolderPod:
    """A pod that works in a folder has no repository: the directory is the caller's to name."""

    def _outward(self, tmp_path: Path) -> Path:
        copy = tmp_path / "outward-copy"
        shutil.copytree(_templates.RECIPES_DIR / "outward", copy)
        return copy

    def test_a_copy_of_the_outward_recipe_applies_to_a_respond_pod(
        self, server: str, tmp_path: Path
    ) -> None:
        _folder_pod(server)
        status, body = _post(
            f"{server}/pods/research/apply", {"directory": str(self._outward(tmp_path))}
        )
        assert status == 200, body
        assert {(i["kind"], i["action"]) for i in body["items"]} >= {("policy", "add")}
        assert body["dryRun"] is False

    def test_the_roster_gains_the_recipes_members(self, server: str, tmp_path: Path) -> None:
        _folder_pod(server)
        directory = _directory(
            tmp_path,
            "team",
            {"pod.yaml": "kind: pod\nname: x\nshape: respond\nmembers: [analyst]\n"},
        )
        status, body = _post(f"{server}/pods/research/apply", {"directory": str(directory)})
        assert status == 200, body
        assert ("member", "analyst", "add") in {
            (i["kind"], i["name"], i["action"]) for i in body["items"]
        }
        assert "research-analyst" in {
            m["id"] for m in _get(f"{server}/pods/research")[1]["members"]
        }

    def test_a_folder_pod_needs_a_directory(self, server: str) -> None:
        _folder_pod(server)
        status, body = _post(f"{server}/pods/research/apply", {})
        assert status == 400
        assert body["error"] == (
            "directory is required: pod 'research' works in a folder and has no repository "
            "to read .docket/ from"
        )

    def test_a_directory_that_runs_things_needs_the_code_then_applies(
        self, server: str, tmp_path: Path
    ) -> None:
        _folder_pod(server)
        directory = _directory(
            tmp_path,
            "runs-folder",
            {"pipeline.yaml": "name: p\nsteps:\n  - migrate:\n      run: make migrate\n"},
        )
        status, body = _post(f"{server}/pods/research/apply", {"directory": str(directory)})
        assert status == 409
        assert body["runs"][0]["kind"] == "pipeline-step"
        status, applied = _post(
            f"{server}/pods/research/apply",
            {"directory": str(directory), "accept": body["reviewCode"]},
        )
        assert status == 200, applied

    def test_a_shape_that_is_not_the_pods_is_refused(self, server: str, tmp_path: Path) -> None:
        _folder_pod(server)
        directory = _directory(
            tmp_path, "wrong", {"pod.yaml": "kind: pod\nname: x\nshape: build\nprotects: [a]\n"}
        )
        status, body = _post(f"{server}/pods/research/apply", {"directory": str(directory)})
        assert status == 400
        assert (
            body["error"] == "pod.yaml: shape 'build' but pod 'research' was provisioned 'respond'"
        )

    def test_an_apply_that_skips_every_item_is_still_audited(
        self, server: str, tmp_path: Path
    ) -> None:
        _folder_pod(server)
        directory = self._outward(tmp_path)
        assert _post(f"{server}/pods/research/apply", {"directory": str(directory)})[0] == 200
        before = [e for e in _audit.read_audit() if e.get("action") == "pod.apply"]
        status, body = _post(f"{server}/pods/research/apply", {"directory": str(directory)})
        assert status == 200
        assert {i["action"] for i in body["items"]} == {"skip"}
        entries = [e for e in _audit.read_audit() if e.get("action") == "pod.apply"]
        assert len(entries) == len(before) + 1
        assert "channel=http" in str(entries[-1]) and "changed=0" in str(entries[-1])
        assert f"skipped={len(body['items'])}" in str(entries[-1])


_FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "operator-v2"


def _get(url: str) -> tuple[int, dict[str, Any]]:
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Bearer {_TOKEN}")
    with urllib.request.urlopen(req, timeout=10) as resp:
        return resp.status, json.loads(resp.read())


def _with_home_placeholder(value: Any, home: Path) -> Any:
    """*value* with the home directory's path replaced by ``<home>``."""
    if isinstance(value, dict):
        return {k: _with_home_placeholder(v, home) for k, v in value.items()}
    if isinstance(value, list):
        return [_with_home_placeholder(v, home) for v in value]
    if isinstance(value, str):
        return value.replace(str(home), "<home>")
    return value


def _folder_pod(url: str) -> None:
    """A ``respond`` pod on a machine that records isolation on."""
    _fleet.set_sandbox_isolation()
    status, _ = _post(f"{url}/pods", {"name": "research", "blueprint": "respond"})
    assert status == 201


def test_a_folder_pod_reports_its_network_and_its_folder(server: str, tmp_path: Path) -> None:
    _folder_pod(server)
    folder = str(Home(tmp_path / ".docket").pod_work_dir("research"))

    status, detail = _get(f"{server}/pods/research")
    assert status == 200
    assert detail["network"] == {"mode": "none", "scope": "default", "enforced": True}
    assert detail["workDir"] == folder
    assert _pod_report.member_report("research-lead")["network"]["enforced"] is True

    rows = {row["name"]: row for row in _get(f"{server}/pods")[1]["pods"]}
    assert rows["research"]["network"]["enforced"] is True
    assert rows["research"]["workDir"] == folder
    assert "workDir" not in rows["demo"]
    assert "workDir" not in _get(f"{server}/pods/demo")[1]

    features = _get(f"{server}/status.json")[1]["features"]
    assert {"networkEnforced", "podWorkDir"} <= set(features)


def test_the_pod_reach_answers_are_the_recorded_fixture(server: str, tmp_path: Path) -> None:
    _folder_pod(server)
    row = next(r for r in _get(f"{server}/pods")[1]["pods"] if r["name"] == "research")
    actual = _with_home_placeholder(
        {"row": row, "detail": _get(f"{server}/pods/research")[1]}, tmp_path / ".docket"
    )
    if record := os.environ.get("OPERATOR_RECORD_DIR"):
        Path(record, "pod-reach.json").write_text(json.dumps(actual, indent=2) + "\n", "utf-8")
        return
    recorded = json.loads((_FIXTURES / "pod-reach.json").read_text(encoding="utf-8"))
    assert actual == recorded


@pytest.mark.parametrize("jail_probes", [{"landlock": False, "seatbelt": False, "docker": False}])
def test_network_is_not_enforced_without_a_backend(server: str) -> None:
    _folder_pod(server)
    detail = _get(f"{server}/pods/research")[1]
    assert detail["network"]["enforced"] is False
    assert _pod_report.member_report("research-lead")["network"]["enforced"] is False
    rows = {row["name"]: row for row in _get(f"{server}/pods")[1]["pods"]}
    assert rows["research"]["network"]["enforced"] is False


def _fetching_pod(url: str) -> None:
    """A ``respond`` pod whose Lead declares one host for `fetch`."""
    _folder_pod(url)
    _fleet.meta_set("research-lead", "fetchDomains", "docs.python.org")


def test_a_pod_that_declares_a_host_offers_fetch_to_the_members_that_may_hold_it(
    server: str,
) -> None:
    _fetching_pod(server)
    status, detail = _get(f"{server}/pods/research")
    assert status == 200
    assert detail["fetchDomains"] == ["docs.python.org"]
    held = [m for m in detail["members"] if "fetch" in m["capabilities"]["tools"]]
    assert held
    for member in held:
        assert member["capabilities"]["fetchDomains"] == ["docs.python.org"]
    for member in detail["members"]:
        if member not in held:
            assert "fetchDomains" not in member["capabilities"]
    assert _pod_report.pod_report("research")["fetchDomains"] == ["docs.python.org"]
    assert "podFetch" in _get(f"{server}/status.json")[1]["features"]


def test_a_pod_without_hosts_declares_none_and_holds_no_fetch(server: str) -> None:
    _folder_pod(server)
    detail = _get(f"{server}/pods/research")[1]
    assert detail["fetchDomains"] == []
    assert all("fetch" not in m["capabilities"]["tools"] for m in detail["members"])
    assert all("fetchDomains" not in m["capabilities"] for m in detail["members"])


def test_the_pod_fetch_answer_is_the_recorded_fixture(server: str, tmp_path: Path) -> None:
    _fetching_pod(server)
    actual = _with_home_placeholder(
        {"detail": _get(f"{server}/pods/research")[1]}, tmp_path / ".docket"
    )
    if record := os.environ.get("OPERATOR_RECORD_DIR"):
        Path(record, "pod-fetch.json").write_text(json.dumps(actual, indent=2) + "\n", "utf-8")
        return
    recorded = json.loads((_FIXTURES / "pod-fetch.json").read_text(encoding="utf-8"))
    assert actual == recorded
