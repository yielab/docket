"""GET /tasks/<project> — the pod queue as JSON over HTTP.

Exposes `TaskRepository.list` -- the records `docket pod <p> tasks` renders from, as their alias
dump -- behind the same Bearer auth as `/runs`. No new behaviour: adds no filtering, no reshaping,
no 404 that the repository itself does not express (a project with no pod is `[]`, not an error).
Covers auth rejection, a missing project segment (400), a project with no pod (200, `{"tasks":
[]}`), and a seeded pod's queue coming back with the same fields the records dump.
"""

from __future__ import annotations

import dataclasses
import json
import subprocess
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import pytest
from tests.support.fakes import FakeDriver
from tests.support.http import get as _get
from tests.support.pods import bind_one_step_pipeline, seed_pod_at_codebase, seed_pod_isolation_off
from tests.support.pods import seed_pod as _seed_pod

from docket.hops.application import compose as _compose
from docket.hops.application import sweep as _sweep
from docket.interfaces.http.server import _DocketHandler
from docket.kernel.home import current_home, use_home
from docket.kernel.threads import ContextHTTPServer
from docket.observability import trace as _trace
from docket.pipeline.domain import spec as _pipeline
from docket.pipeline.domain import step as _step
from docket.tasks.application import queue as _application_queue
from docket.tasks.application.repository import TaskRepository
from docket.tasks.domain.task import HopResult, TaskRecord
from docket.teams import prompts as _prompts

SUBJECT = "docket.interfaces.http.server"

_TEST_TOKEN = "test-serve-token-tasks-p22-2"


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


class TestQueueShapeMatchesTheRecordDump:
    def test_http_response_matches_the_record_dump_directly(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path, project="demo"):
            _application_queue.enqueue_task_once("demo", "Ship the read API", channel="cli")
            _application_queue.enqueue_task_once("demo", "Add a second task", channel="cli")

            expected = TaskRepository.for_pod("demo").list()
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
                ] == [r.model_dump(by_alias=True, mode="json") for r in expected]
                for task in body["tasks"]:
                    assert task["status"] == "pending"
                    assert task["priority"] == "normal"
                    assert "id" in task and "created" in task


class TestTaskCursor:
    def _poll(self, url: str, token: str, cursor: str, extra: str = "") -> tuple[int, dict]:  # type: ignore[type-arg]
        return _get(f"{url}/tasks/demo?updatedSince={cursor}{extra}", token)

    def test_a_cursor_walks_every_task_once_and_a_status_move_reappears_one(
        self, tmp_path: Path
    ) -> None:
        with _seed_pod(tmp_path, project="demo"), _live_server() as (url, token):
            routine, _ = _application_queue.enqueue_task_once(
                "demo", "From a routine", channel="routine", idempotency_key="r:1"
            )
            cli, _ = _application_queue.enqueue_task_once("demo", "From the CLI", channel="cli")

            status, body = self._poll(url, token, "0")
            assert status == 200
            assert [(t["id"], t["channel"]) for t in body["tasks"]] == [
                (routine.id, "routine"),
                (cli.id, "cli"),
            ]
            assert [t["rev"] for t in body["tasks"]] == [1, 2]
            assert body["next"] == "2"

            status, again = self._poll(url, token, body["next"])
            assert (status, again) == (200, {"tasks": [], "next": "2"})

            status, _ = _post(f"{url}/tasks/demo/{cli.id}/cancel", {}, token)
            assert status == 200
            _, moved = self._poll(url, token, body["next"])
            assert [(t["id"], t["status"]) for t in moved["tasks"]] == [(cli.id, "cancelled")]
            assert moved["next"] == "3"

    def test_status_and_external_ref_filter_the_changed_set(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path, project="demo"), _live_server() as (url, token):
            _application_queue.enqueue_task_once("demo", "one", channel="cli", external_ref="A")
            two, _ = _application_queue.enqueue_task_once(
                "demo", "two", channel="cli", external_ref="B"
            )

            _, by_ref = self._poll(url, token, "0", "&externalRef=B")
            assert [t["id"] for t in by_ref["tasks"]] == [two.id]
            assert by_ref["next"] == "2"
            _, none = self._poll(url, token, "0", "&status=done")
            assert none == {"tasks": [], "next": "0"}

    def test_a_cursor_that_is_not_an_integer_is_400_bad_cursor(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path, project="demo"), _live_server() as (url, token):
            for bad in ("abc", "-1", "1.5"):
                status, body = self._poll(url, token, bad)
                assert status == 400
                assert body["code"] == "bad_cursor"

    def test_without_the_cursor_the_body_has_no_next(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path, project="demo"), _live_server() as (url, token):
            _application_queue.enqueue_task_once("demo", "one", channel="cli")
            _, body = _get(f"{url}/tasks/demo", token)
            assert set(body) == {"tasks"}


class TestPromptManifestOnTheTask:
    def test_a_hop_shows_the_shipped_prompts_hashes(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path, project="demo"), _live_server() as (url, token):
            task, _created = _application_queue.enqueue_task_once("demo", "Ship it", channel="cli")
            _sweep.dispatch_pod("demo", runner=FakeDriver())

            status, body = _get(f"{url}/tasks/demo/{task.id}", token)

            assert status == 200
            hops = body["task"]["hops"] if "task" in body else body["hops"]
            manifest = next(h for h in hops if h["role"] == "implementer")["promptManifest"]
            layers = {entry["layer"]: entry for entry in manifest["layers"]}
            hop = _prompts.shipped_prompt("hop", "implementer")
            assert layers["hop"]["sha256"] == hop.sha256
            assert (
                layers["identity"]["sha256"]
                == _prompts.shipped_prompt("identity", "implementer").sha256
            )
            assert manifest["profile"] == "hosted"


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


def _queue(project: str = "demo") -> list[TaskRecord]:
    return TaskRepository.for_pod(project).list()


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


class TestConversationTask:
    def test_a_one_step_pod_takes_a_conversation_and_answers_it_with_its_turns(
        self, tmp_path: Path
    ) -> None:
        with _seed_pod(tmp_path), _live_server() as (url, token):
            bind_one_step_pipeline("demo")
            status, created = _post(
                f"{url}/tasks/demo", {"description": "chat", "conversation": {"maxTurns": 3}}, token
            )
            assert status == 201
            _status, record = _get(f"{url}/tasks/demo/{created['task']}", token)
            assert record["conversation"] == {"maxTurns": 3, "turns": 0}
            _status, listed = _get(f"{url}/tasks/demo", token)
            assert listed["tasks"][0]["conversation"] == {"maxTurns": 3, "turns": 0}

    def test_the_turns_are_the_finished_hops_and_are_not_read_back(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path), _live_server() as (url, token):
            bind_one_step_pipeline("demo")
            _status, created = _post(
                f"{url}/tasks/demo", {"description": "chat", "conversation": {"maxTurns": 3}}, token
            )
            TaskRepository.for_pod("demo").update(
                created["task"], lambda r: r.hops.append(HopResult(role="lead", ok=True)) or True
            )
            _status, record = _get(f"{url}/tasks/demo/{created['task']}", token)
            assert record["conversation"] == {"maxTurns": 3, "turns": 1}
            stored = TaskRepository.for_pod("demo").get(created["task"])
            assert stored is not None and stored.conversation is not None
            assert stored.conversation.max_turns == 3

    def test_a_pipeline_of_more_than_one_step_is_refused_and_nothing_is_enqueued(
        self, tmp_path: Path
    ) -> None:
        with _seed_pod(tmp_path), _live_server() as (url, token):
            status, body = _post(
                f"{url}/tasks/demo", {"description": "chat", "conversation": {"maxTurns": 3}}, token
            )
            assert status == 400
            assert body["code"] == "conversation_needs_one_step"
            assert _queue() == []

    def test_a_wrongly_shaped_conversation_is_400(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path), _live_server() as (url, token):
            bind_one_step_pipeline("demo")
            for conversation in ({"maxTurns": 0}, {"maxTurns": 21}, {"maxTurns": "3"}, {}, 3):
                status, _body = _post(
                    f"{url}/tasks/demo",
                    {"description": "x", "conversation": conversation},
                    token,
                )
                assert status == 400, conversation
            assert _queue() == []

    def test_an_unknown_pod_is_still_404_and_an_unknown_pipeline_is_left_to_the_claim(
        self, tmp_path: Path
    ) -> None:
        with _seed_pod(tmp_path), _live_server() as (url, token):
            body = {"description": "x", "conversation": {"maxTurns": 2}}
            status, _body = _post(f"{url}/tasks/nopod", body, token)
            assert status == 404
            status, _body = _post(f"{url}/tasks/demo", {**body, "pipeline": "nope"}, token)
            assert status == 201

    def test_a_task_without_one_has_no_conversation_key(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path), _live_server() as (url, token):
            _status, created = _post(f"{url}/tasks/demo", {"description": "plain"}, token)
            _status, record = _get(f"{url}/tasks/demo/{created['task']}", token)
            assert "conversation" not in record


def _app_repo(root: Path) -> Path:
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    for rel in ("src/app/main.py", "src/other/x.py", "README.md"):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text("x\n")
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    return root


class TestStructuredTask:
    def test_the_record_holds_it_and_the_first_hop_renders_it_over_a_bounded_map(
        self, tmp_path: Path
    ) -> None:
        codebase = _app_repo(tmp_path / "code")
        structured = {"doneWhen": "the app tests pass", "paths": ["src/app/"]}
        with seed_pod_at_codebase(tmp_path, codebase), _live_server() as (url, token):
            status, created = _post(
                f"{url}/tasks/demo", {"description": "Fix the app", "task": structured}, token
            )
            assert status == 201
            _status, record = _get(f"{url}/tasks/demo/{created['task']}", token)
            assert record["task"] == structured
            assert record["description"] == "Fix the app"

            stored = TaskRepository.for_pod("demo").get(created["task"])
            assert stored is not None
            message, _ = _compose._hop_message(stored, "implementer", [], project="demo")

        section = message.split("\n\n## Hop\n", 1)[0]
        assert section.startswith("## Task\nFix the app\n\nDone when: the app tests pass")
        assert "src/app/main.py" in section
        assert "src/other" not in section and "README.md" not in section

    def test_an_unknown_key_inside_task_is_400_naming_it(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path), _live_server() as (url, token):
            status, body = _post(
                f"{url}/tasks/demo",
                {"description": "x", "task": {"doneWhen": "ok", "bogusKey": 1}},
                token,
            )
            assert status == 400
            assert "bogusKey" in body["error"]
            assert _queue() == []

    def test_a_task_of_the_wrong_shape_is_400(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path), _live_server() as (url, token):
            for bad in ("text", ["a"], {"paths": "src/"}, {"acceptance": [1]}):
                status, _body = _post(f"{url}/tasks/demo", {"description": "x", "task": bad}, token)
                assert status == 400, bad
            assert _queue() == []

    def test_a_description_only_body_stores_no_task_key(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path), _live_server() as (url, token):
            _status, created = _post(f"{url}/tasks/demo", {"description": "plain"}, token)
            _status, record = _get(f"{url}/tasks/demo/{created['task']}", token)
            assert "task" not in record


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

            def _spend(record: TaskRecord) -> None:
                record.hops = [HopResult(role="lead", usage={"input": 1500, "output": 10})]

            TaskRepository.for_pod("demo").update(created["task"], _spend)
            _status, spent = _get(f"{url}/tasks/demo/{created['task']}", token)
            assert spent["tokenBudget"] == 0


class _WatchingDriver(FakeDriver):
    """Reads the task over HTTP from inside each turn, as a client polling a running task would;
    the Reviewer sends the work back once."""

    def __init__(self, url: str, token: str, task_id: str) -> None:
        super().__init__()
        self._url, self._token, self._task_id = url, token, task_id
        self._reviews = 0
        self.seen: list[tuple[dict, dict]] = []  # type: ignore[type-arg]

    def run_turn(self, agent_id: str, *args, **kwargs):  # type: ignore[no-untyped-def]
        _status, one = _get(f"{self._url}/tasks/demo/{self._task_id}", self._token)
        _status, listed = _get(f"{self._url}/tasks/demo", self._token)
        self.seen.append((one, next(t for t in listed["tasks"] if t["id"] == self._task_id)))
        result = super().run_turn(agent_id, *args, **kwargs)
        if not agent_id.endswith("-reviewer"):
            return result
        self._reviews += 1
        verdict = "REQUEST-CHANGES\nrename it" if self._reviews == 1 else "APPROVE"
        return dataclasses.replace(result, output=verdict)


class TestCurrentHop:
    def test_a_running_task_names_its_hop_and_a_settled_one_does_not(self, tmp_path: Path) -> None:
        with (
            seed_pod_isolation_off(tmp_path, roles=("lead", "implementer", "reviewer")),
            _live_server() as (url, token),
        ):
            task, _created = _application_queue.enqueue_task_once("demo", "Ship it", channel="cli")
            _status, before = _get(f"{url}/tasks/demo/{task.id}", token)
            assert "current" not in before

            driver = _WatchingDriver(url, token, task.id)
            _sweep.dispatch_pod("demo", runner=driver)

            for one, listed in driver.seen:
                assert one["status"] == "running"
                assert listed["current"] == one["current"]
            hops = [one["current"] for one, _listed in driver.seen]
            first = hops[0]
            assert first["stepId"] and first["startedAt"] and first["model"]
            assert (first["role"], first["member"], first["cycle"]) == (
                "lead",
                "demo-lead",
                0,
            )
            implementer = [h for h in hops if h["role"] == "implementer"]
            assert [h["cycle"] for h in implementer] == [0, 1]
            assert implementer[0]["member"] == "demo-implementer"

            _status, after = _get(f"{url}/tasks/demo/{task.id}", token)
            assert after["status"] == "done"
            assert "current" not in after
            _status, listed_after = _get(f"{url}/tasks/demo", token)
            assert all("current" not in t for t in listed_after["tasks"])


def _hop_events(project: str, name: str) -> dict[tuple[str, int], datetime]:
    """The instant of each ``hop_started`` or ``hop_finished`` event, by (step, cycle)."""
    found: dict[tuple[str, int], datetime] = {}
    for tracefile in (current_home().traces_dir / project).glob("*.jsonl"):
        for event in _trace.read_trace(tracefile):
            if event["event_type"] == name:
                payload = event["payload"]
                found[(payload["step"], payload["cycle"])] = datetime.fromisoformat(event["ts_us"])
    return found


def _seen_at(stamp: str) -> datetime:
    return datetime.fromisoformat(stamp)


def _assert_times_match_the_trace(hops: list[dict], project: str = "demo") -> None:  # type: ignore[type-arg]
    started = _hop_events(project, "hop_started")
    finished = _hop_events(project, "hop_finished")
    assert len(started) == len(finished) == len(hops)
    for hop in hops:
        key = (hop["stepId"], hop["cycle"])
        # Each time is taken just before its event is stamped, so the event is never earlier.
        for field, event in (("startedAt", started[key]), ("finishedAt", finished[key])):
            lag = (event - _seen_at(hop[field])).total_seconds()
            assert 0 <= lag < 0.5, (key, field, lag)
        assert _seen_at(hop["startedAt"]) <= _seen_at(hop["finishedAt"])


class _ReworkOnce(FakeDriver):
    """The Reviewer sends the work back once."""

    def __init__(self) -> None:
        super().__init__()
        self._reviews = 0

    def run_turn(self, agent_id: str, *args, **kwargs):  # type: ignore[no-untyped-def]
        result = super().run_turn(agent_id, *args, **kwargs)
        if not agent_id.endswith("-reviewer"):
            return result
        self._reviews += 1
        verdict = "REQUEST-CHANGES\nrename it" if self._reviews == 1 else "APPROVE"
        return dataclasses.replace(result, output=verdict)


class _SlowFirstChild(FakeDriver):
    """The first child of a parallel group takes longer than its sibling."""

    def run_turn(self, agent_id: str, session_key: str, *args, **kwargs):  # type: ignore[no-untyped-def]
        if session_key.endswith("implement-a"):
            time.sleep(0.15)
        return super().run_turn(agent_id, session_key, *args, **kwargs)


class TestHopTimes:
    def test_a_two_step_task_shows_each_hop_with_its_times_and_cycle_zero(
        self, tmp_path: Path
    ) -> None:
        with (
            seed_pod_isolation_off(tmp_path, roles=("lead", "implementer")),
            _live_server() as (url, token),
        ):
            task, _created = _application_queue.enqueue_task_once("demo", "Ship it", channel="cli")
            _sweep.dispatch_pod("demo", runner=FakeDriver())

            _status, body = _get(f"{url}/tasks/demo/{task.id}", token)

            hops = body["hops"]
            assert [h["role"] for h in hops] == ["lead", "implementer"]
            assert [h["cycle"] for h in hops] == [0, 0]
            _assert_times_match_the_trace(hops)

    def test_a_step_sent_back_once_shows_its_second_hop_in_cycle_one(self, tmp_path: Path) -> None:
        with (
            seed_pod_isolation_off(tmp_path, roles=("lead", "implementer", "reviewer")),
            _live_server() as (url, token),
        ):
            task, _created = _application_queue.enqueue_task_once("demo", "Ship it", channel="cli")
            _sweep.dispatch_pod("demo", runner=_ReworkOnce())

            _status, body = _get(f"{url}/tasks/demo/{task.id}", token)

            hops = body["hops"]
            implementer = [h for h in hops if h["role"] == "implementer"]
            assert [h["cycle"] for h in implementer] == [0, 1]
            assert implementer[0]["finishedAt"] <= implementer[1]["startedAt"]
            _assert_times_match_the_trace(hops)

    def test_each_child_of_a_parallel_group_has_its_own_times(self, tmp_path: Path) -> None:
        spec = _pipeline.PipelineSpec(
            name="fanout",
            steps=[
                _step.Step(
                    id="fanout",
                    parallel=[
                        _step.Step(id="implement-a", role="implementer"),
                        _step.Step(id="implement-b", role="implementer"),
                    ],
                )
            ],
        )
        with (
            seed_pod_isolation_off(tmp_path, roles=("lead", "implementer")),
            _live_server() as (url, token),
        ):
            task, _created = _application_queue.enqueue_task_once("demo", "Ship it", channel="cli")
            _sweep.dispatch_pod("demo", runner=_SlowFirstChild(), spec=spec)

            _status, body = _get(f"{url}/tasks/demo/{task.id}", token)

            hops = body["hops"]
            assert sorted(h["stepId"] for h in hops) == ["implement-a", "implement-b"]
            _assert_times_match_the_trace(hops)
            by_step = {h["stepId"]: h for h in hops}
            assert by_step["implement-b"]["finishedAt"] < by_step["implement-a"]["finishedAt"]


class TestOldHopsCarryNoTimes:
    def test_a_hop_recorded_without_times_dumps_without_the_keys(self) -> None:
        hop = HopResult.model_validate({"role": "implementer", "ok": True})

        dumped = hop.model_dump(by_alias=True, mode="json")

        assert not {"startedAt", "finishedAt", "cycle"} & dumped.keys()
