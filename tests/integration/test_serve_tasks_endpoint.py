"""GET /tasks/<project> — the pod queue as JSON over HTTP.

Exposes `core.dispatch.read_tasks` -- the exact normalized shape `docket pod <p> tasks` renders
from -- behind the same Bearer auth as `/runs`. No new behaviour: adds no filtering, no reshaping,
no 404 that `read_tasks` itself does not express (a project with no pod is `[]`, not an error).
Covers auth rejection, a missing project segment (400), a project with no pod (200, `{"tasks":
[]}`), and a seeded pod's queue coming back with the same fields `read_tasks` returns.
"""

from __future__ import annotations

import dataclasses
import json
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from tests.pods import build_pod

from docket.interfaces.cli.commands import pod as _pod
from docket.interfaces.http.server import _DocketHandler
from docket.kernel.home import Home, current_home, use_home
from docket.kernel.threads import ContextHTTPServer
from docket.platform import store as _store
from docket.tasks.application import queue as _application_queue
from docket.teams import settings as _settings

SUBJECT = "docket.serve"

_TEST_TOKEN = "test-serve-token-tasks-p22-2"


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOCKET_SERVICE_MANAGER", "none")


@contextmanager
def _seed_pod(tmp_path: Path, project: str = "demo") -> Iterator[Path]:
    home = tmp_path / ".docket"
    (home / "workspaces" / "projects").mkdir(parents=True)
    (home / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    with use_home(Home(home)):
        build_pod(project, _pod.pod.DEFAULT_POD_ROLES, codebase=f"/src/{project}")
        yield home


def _get(url: str, token: str | None = None) -> tuple[int, dict]:  # type: ignore[type-arg]
    req = urllib.request.Request(url)
    if token is not None:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


@contextmanager
def _live_server(dispatch_on: bool = False) -> Iterator[tuple[str, str]]:
    """Built inside the seeded home: the server serves the home it was built in."""

    class _Handler(_DocketHandler):
        serve_token = _TEST_TOKEN

    _Handler.dispatch_on = dispatch_on
    srv = ContextHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}", _TEST_TOKEN
    finally:
        srv.shutdown()


class TestAuth:
    def test_no_token_rejected(self) -> None:
        with _live_server() as (url, _token):
            status, body = _get(f"{url}/tasks/demo")
            assert status == 401
            assert body["ok"] is False

    def test_wrong_token_rejected(self) -> None:
        with _live_server() as (url, _token):
            status, _body = _get(f"{url}/tasks/demo", token="not-the-real-token")
            assert status == 401

    def test_correct_token_accepted(self) -> None:
        with _live_server() as (url, token):
            status, body = _get(f"{url}/tasks/demo", token=token)
            assert status == 200
            assert body == {"tasks": []}


class TestMissingProject:
    def test_bare_path_is_400(self) -> None:
        with _live_server() as (url, token):
            status, body = _get(f"{url}/tasks", token=token)
            assert status == 400
            assert body["ok"] is False

    def test_trailing_slash_is_400(self) -> None:
        with _live_server() as (url, token):
            status, body = _get(f"{url}/tasks/", token=token)
            assert status == 400
            assert body["ok"] is False

    def test_missing_project_checked_before_needing_auth_bypass(self) -> None:
        """Even the empty-project 400 stays behind auth -- no unauthenticated
        request should be able to distinguish a missing project from any
        other route without a valid token."""
        with _live_server() as (url, _token):
            status, _body = _get(f"{url}/tasks")
            assert status == 401


class TestNoPodIsEmptyList:
    def test_unknown_project_returns_empty_list_not_404(self) -> None:
        with _live_server() as (url, token):
            status, body = _get(f"{url}/tasks/no-such-pod", token=token)
            assert status == 200
            assert body == {"tasks": []}


class TestQueueShapeMatchesReadTasks:
    def test_http_response_matches_read_tasks_directly(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path, project="demo"):
            _application_queue.enqueue_task_once("demo", "Ship the read API", channel="cli")
            _application_queue.enqueue_task_once("demo", "Add a second task", channel="cli")

            expected = _application_queue.read_tasks("demo")
            assert len(expected) == 2

            approvals_dir = tmp_path / "approvals"
            approvals_dir.mkdir(exist_ok=True)
            with use_home(
                dataclasses.replace(current_home(), approvals_dir_override=approvals_dir)
            ):

                class _Handler(_DocketHandler):
                    serve_token = _TEST_TOKEN

                srv = ContextHTTPServer(("127.0.0.1", 0), _Handler)
                port = srv.server_address[1]
                t = threading.Thread(target=srv.serve_forever, daemon=True)
                t.start()
                try:
                    status, body = _get(f"http://127.0.0.1:{port}/tasks/demo", token=_TEST_TOKEN)
                finally:
                    srv.shutdown()

                assert status == 200
                assert all("tokenBudget" in task for task in body["tasks"])
                assert [
                    {k: v for k, v in t.items() if k != "tokenBudget"} for t in body["tasks"]
                ] == expected
                for task in body["tasks"]:
                    assert task["status"] == "pending"
                    assert task["priority"] == "normal"
                    assert "id" in task and "created" in task


def _post(url: str, body: dict, token: str | None = None) -> tuple[int, dict]:  # type: ignore[type-arg]
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST")
    req.add_header("Content-Type", "application/json")
    if token is not None:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def _queue(project: str = "demo") -> list[dict]:  # type: ignore[type-arg]
    return _application_queue.read_tasks(project)


def _enqueue_entries() -> list[dict]:  # type: ignore[type-arg]
    from docket.governance import audit as _audit

    return [e for e in _audit.read_audit() if e.get("action") == "task.enqueue"]


_FULL_BODY = {
    "description": "ship the thing",
    "externalRef": "TACK-412/attempt-2",
    "idempotencyKey": "TACK-412:2",
    "baseRef": "docket/demo/task-91aa",
    "pipeline": "tdd",
    "gate": {"command": "npm test -- --ci", "timeoutS": 600, "map": {"3": "needs_human"}},
    "maxTokens": 400000,
    "prepare": "pnpm install --frozen-lockfile",
    "restrictions": {"deniedTools": ["fetch"], "network": "none", "policies": []},
}


class TestAddressableTask:
    def test_same_idempotency_key_returns_the_existing_task(self, tmp_path: Path) -> None:
        with (
            _seed_pod(tmp_path),
            _live_server() as live_server,
        ):
            url, token = live_server
            body = {"description": "once only", "idempotencyKey": "k-1"}
            first_status, first = _post(f"{url}/tasks/demo", body, token)
            second_status, second = _post(f"{url}/tasks/demo", body, token)
            assert (first_status, second_status) == (201, 200)
            assert (first["created"], second["created"]) == (True, False)
            assert first["task"] == second["task"]
            assert len(_queue()) == 1
            assert len(_enqueue_entries()) == 1

    def test_a_new_task_answers_201_with_the_documented_keys(self, tmp_path: Path) -> None:
        with (
            _seed_pod(tmp_path),
            _live_server() as live_server,
        ):
            url, token = live_server
            status, body = _post(f"{url}/tasks/demo", {"description": "plain"}, token)
            assert status == 201
            assert set(body) == {"ok", "created", "task", "project", "status"}
            assert body["status"] == "pending"

    def test_the_record_carries_every_field_as_sent(self, tmp_path: Path) -> None:
        with (
            _seed_pod(tmp_path),
            _live_server() as live_server,
        ):
            url, token = live_server
            _status, created = _post(f"{url}/tasks/demo", _FULL_BODY, token)
            status, record = _get(f"{url}/tasks/demo/{created['task']}", token)
            assert status == 200
            for key in _FULL_BODY:
                if key != "description":
                    assert record[key] == _FULL_BODY[key], key

    def test_a_widening_restriction_is_422_and_enqueues_nothing(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path), _live_server() as (url, token):
            bodies = [
                {"restrictions": {"network": "open"}},
                {"restrictions": {"deniedTools": ["no_such_tool"]}},
                {
                    "restrictions": {
                        "policies": [
                            {
                                "kind": "policy",
                                "name": "p",
                                "appliesTo": ["*"],
                                "when": {"tool": "bash"},
                            }
                        ]
                    }
                },
                {
                    "restrictions": {
                        "policies": [
                            {
                                "kind": "policy",
                                "name": "p",
                                "appliesTo": ["*"],
                                "when": {"tool": "bash"},
                                "then": "allow",
                            }
                        ]
                    }
                },
            ]
            for extra in bodies:
                status, body = _post(f"{url}/tasks/demo", {"description": "x", **extra}, token)
                assert status == 422, extra
                assert "error" in body
            assert _queue() == []
            assert _enqueue_entries() == []

    def test_a_wrongly_shaped_field_is_400(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path), _live_server() as (url, token):
            for extra in (
                {"externalRef": ""},
                {"externalRef": "x" * 201},
                {"idempotencyKey": 7},
                {"baseRef": ["a"]},
                {"pipeline": ""},
                {"gate": "npm test"},
                {"gate": {"timeoutS": 5}},
                {"maxTokens": 0},
                {"maxTokens": "many"},
                {"prepare": 3},
                {"prepare": "a\nb"},
                {"restrictions": "none"},
            ):
                status, _body = _post(f"{url}/tasks/demo", {"description": "x", **extra}, token)
                assert status == 400, extra
            assert _queue() == []

    def test_get_one_task_is_404_when_unknown(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path), _live_server() as (url, token):
            status, body = _get(f"{url}/tasks/demo/task-nope", token)
            assert status == 404
            assert "error" in body

    def test_the_list_filters_by_external_ref_and_status(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path), _live_server() as (url, token):
            _post(f"{url}/tasks/demo", {"description": "a", "externalRef": "A"}, token)
            _post(f"{url}/tasks/demo", {"description": "b", "externalRef": "B"}, token)
            _status, only_a = _get(f"{url}/tasks/demo?externalRef=A", token)
            assert [t["externalRef"] for t in only_a["tasks"]] == ["A"]
            _status, pending = _get(f"{url}/tasks/demo?status=pending", token)
            assert len(pending["tasks"]) == 2
            _status, done = _get(f"{url}/tasks/demo?status=done", token)
            assert done["tasks"] == []
            _status, none = _get(f"{url}/tasks/demo?externalRef=A&status=done", token)
            assert none["tasks"] == []
            status, _body = _get(f"{url}/tasks/demo?status=bogus", token)
            assert status == 400

    def test_one_task_route_needs_the_token(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path), _live_server() as (url, _token):
            status, _body = _get(f"{url}/tasks/demo/task-x")
            assert status == 401


class TestPostEnqueueSweep:
    def test_a_posted_task_starts_its_pods_sweep_when_dispatch_is_on(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """POST /tasks/<pod> with dispatch on submits one sweep for that pod."""
        from docket.interfaces.http import server as _server

        with _seed_pod(tmp_path), _live_server(dispatch_on=True) as dispatching_server:
            submitted: list[str] = []
            monkeypatch.setattr(_server, "_submit_pod_sweep", lambda p: submitted.append(p) or True)
            url, token = dispatching_server

            status, _body = _post(f"{url}/tasks/demo", {"description": "go"}, token)

            assert status == 201
            assert submitted == ["demo"]

    def test_a_posted_task_starts_no_sweep_when_dispatch_is_off(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Without dispatch the enqueue never submits a sweep."""
        from docket.interfaces.http import server as _server

        with _seed_pod(tmp_path), _live_server() as live_server:
            submitted: list[str] = []
            monkeypatch.setattr(_server, "_submit_pod_sweep", lambda p: submitted.append(p) or True)
            url, token = live_server

            _post(f"{url}/tasks/demo", {"description": "go"}, token)

            assert submitted == []


class TestTokenBudget:
    def test_an_uncapped_task_reports_the_configured_turn_budget(self, tmp_path: Path) -> None:
        with (
            _seed_pod(tmp_path),
            use_home(dataclasses.replace(current_home(), agent_loop_token_budget=4321)),
            _live_server() as (url, token),
        ):
            _status, created = _post(f"{url}/tasks/demo", {"description": "x"}, token)
            status, record = _get(f"{url}/tasks/demo/{created['task']}", token)
            assert status == 200
            assert record["tokenBudget"] == 4321
            _status, listed = _get(f"{url}/tasks/demo", token)
            assert [t["tokenBudget"] for t in listed["tasks"]] == [4321]

    def test_a_capped_task_reports_what_its_cap_has_left(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path), _live_server() as (url, token):
            _status, created = _post(
                f"{url}/tasks/demo", {"description": "x", "maxTokens": 1000}, token
            )
            status, record = _get(f"{url}/tasks/demo/{created['task']}", token)
            assert status == 200
            assert record["tokenBudget"] == 1000

            def _spend(doc: dict) -> dict:  # type: ignore[type-arg]
                for task in doc["tasks"]:
                    if task["id"] == created["task"]:
                        task["hops"] = [{"role": "lead", "usage": {"input": 1500, "output": 10}}]
                return doc

            _store.read_modify_write(_settings.pod_task_list_path("demo"), _spend)
            _status, spent = _get(f"{url}/tasks/demo/{created['task']}", token)
            assert spent["tokenBudget"] == 0
