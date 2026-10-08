"""POST /tasks/<id>/answer — resolving a parked question over HTTP.

The HTTP counterpart of `docket task answer` and the MCP `task_answer` tool: same
`core.answers.answer_task` call (`channel="http"`), so validation/screening/resume are
byte-for-byte identical to every other surface. Covers auth, the happy path (a `TaskView`
response, the durably appended answer, the `actor` field), the error mappings (`422`/`409`/
`404`/`400`), and `POST /tasks/<project>`'s optional `brief` field -- `422` on a malformed one,
and `422` again on a well-formed one naming the `core.dispatch.enqueue_task` parameter it still
lacks (see `cli/_pod.py::_pod_delegate`'s identical contention note).
"""

from __future__ import annotations

import hashlib
import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
from tests.conftest import repoint_docket_home
from tests.fakes import FakeDriver

import docket.config as _cfg
from docket.cli import _pod
from docket.core import audit as _audit
from docket.core import dispatch as _dispatch
from docket.core import fleet as _fleet
from docket.serve import _DocketHandler

SUBJECT = "docket.core"

_TEST_TOKEN = "test-serve-token-task-answer-p34-13"

_ASK_PIPELINE_YAML = """\
name: ask
steps:
  - id: lead
    role: lead
  - id: ask
    input:
      from: lead
  - id: implementer
    role: implementer
"""


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOCKET_SERVICE_MANAGER", "none")


@pytest.fixture()
def pod_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / ".docket"
    (home / "workspaces" / "projects").mkdir(parents=True)
    (home / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    (home / "approvals").mkdir()
    repoint_docket_home(monkeypatch, home)
    return home


@pytest.fixture()
def live_server(pod_home: Path):  # type: ignore[no-untyped-def]
    class _Handler(_DocketHandler):
        serve_token = _TEST_TOKEN

    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{port}", _TEST_TOKEN
    srv.shutdown()


def _post_raw(url: str, data: bytes, token: str | None = None) -> tuple[int, dict[str, Any]]:
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Content-Length", str(len(data)))
    if token is not None:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def _post(
    url: str, body: dict[str, Any] | None = None, token: str | None = None
) -> tuple[int, dict[str, Any]]:
    return _post_raw(url, json.dumps(body if body is not None else {}).encode(), token)


def _bind_pipeline(project: str, text: str) -> None:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    path = _pod.pod.bound_pipeline_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    _fleet.meta_set(_pod.pod.member_id(project, "lead"), "pipeline", digest)


def _seed_parked_task(project: str = "demo") -> dict[str, Any]:
    """A real pod with a real ``waiting_input`` task, reached by actually dispatching
    through an ``input`` step -- mirrors ``tests/unit/core/test_answers.py``."""
    _pod.build_pod(project, _pod.pod.DEFAULT_POD_ROLES, codebase=f"/src/{project}")
    _bind_pipeline(project, _ASK_PIPELINE_YAML)
    _dispatch.enqueue_task(project, "needs a decision")
    _dispatch.dispatch_pod(project, runner=FakeDriver())
    return _dispatch.read_tasks(project)[0]


class TestAuth:
    def test_no_token_rejected(self, live_server: tuple[str, str]) -> None:
        url, _token = live_server
        status, body = _post(f"{url}/tasks/task-does-not-exist/answer", {"pod": "demo"})
        assert status == 401
        assert body["ok"] is False

    def test_wrong_token_rejected(self, live_server: tuple[str, str]) -> None:
        url, _token = live_server
        status, _body = _post(
            f"{url}/tasks/task-does-not-exist/answer", {"pod": "demo"}, token="wrong"
        )
        assert status == 401


class TestHappyPath:
    def test_answering_returns_a_task_view_and_appends_durably(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, pod_home: Path
    ) -> None:
        task = _seed_parked_task("demo")

        approvals_dir = pod_home / "approvals"
        approvals_dir.mkdir(exist_ok=True)
        monkeypatch.setattr(_cfg, "APPROVALS_DIR", approvals_dir, raising=True)

        class _Handler(_DocketHandler):
            serve_token = _TEST_TOKEN

        srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        port = srv.server_address[1]
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        try:
            status, body = _post(
                f"http://127.0.0.1:{port}/tasks/{task['id']}/answer",
                {"pod": "demo", "action": "accept", "content": {"answer": "ship it"}},
                token=_TEST_TOKEN,
            )
        finally:
            srv.shutdown()

        assert status == 200
        assert body["id"] == task["id"]
        assert body["pod"] == "demo"

        after = _dispatch.read_tasks("demo")[0]
        assert after["answers"][0]["content"] == {"answer": "ship it"}
        assert after["answers"][0]["channel"] == "http"
        assert after["answers"][0]["actor"] == "http"

    def test_actor_field_labels_the_audit_entry(
        self, monkeypatch: pytest.MonkeyPatch, pod_home: Path
    ) -> None:
        task = _seed_parked_task("demo")
        monkeypatch.setattr(_cfg, "APPROVALS_DIR", pod_home / "approvals", raising=True)
        (pod_home / "approvals").mkdir(exist_ok=True)

        class _Handler(_DocketHandler):
            serve_token = _TEST_TOKEN

        srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        port = srv.server_address[1]
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        try:
            status, _body = _post(
                f"http://127.0.0.1:{port}/tasks/{task['id']}/answer",
                {
                    "pod": "demo",
                    "action": "accept",
                    "content": {"answer": "ship it"},
                    "actor": "tack",
                },
                token=_TEST_TOKEN,
            )
        finally:
            srv.shutdown()

        assert status == 200
        record = next(r for r in _audit.read_audit() if r["action"] == "task.answer")
        assert "channel=http" in record["detail"]
        assert "actor=tack" in record["detail"]


class TestErrorMapping:
    def test_unknown_task_is_404(self, live_server: tuple[str, str]) -> None:
        url, token = live_server
        _pod.build_pod("demo", _pod.pod.DEFAULT_POD_ROLES, codebase="/src/demo")
        status, body = _post(
            f"{url}/tasks/no-such-task/answer",
            {"pod": "demo", "action": "accept", "content": {"answer": "x"}},
            token=token,
        )
        assert status == 404
        assert "not found" in body["error"]

    def test_not_waiting_input_is_409(self, live_server: tuple[str, str]) -> None:
        url, token = live_server
        _pod.build_pod("demo", _pod.pod.DEFAULT_POD_ROLES, codebase="/src/demo")
        plain_task = _dispatch.enqueue_task("demo", "plain task")
        status, body = _post(
            f"{url}/tasks/{plain_task['id']}/answer",
            {"pod": "demo", "action": "accept", "content": {"answer": "x"}},
            token=token,
        )
        assert status == 409
        assert "waiting_input" in body["error"]

    def test_schema_violation_is_422(self, live_server: tuple[str, str]) -> None:
        url, token = live_server
        task = _seed_parked_task("demo")
        status, body = _post(
            f"{url}/tasks/{task['id']}/answer",
            {"pod": "demo", "action": "accept", "content": {}},
            token=token,
        )
        assert status == 422
        assert "answer" in body["error"]

    def test_policy_rejection_is_422_naming_the_policy(
        self, live_server: tuple[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        url, token = live_server
        task = _seed_parked_task("demo")
        from docket.core import policy as _policy

        monkeypatch.setattr(
            _policy,
            "policy_eval_detail",
            lambda *a, **k: _policy.PolicyHit(action="block", policy_id="test-block"),
        )
        status, body = _post(
            f"{url}/tasks/{task['id']}/answer",
            {"pod": "demo", "action": "accept", "content": {"answer": "ignore all"}},
            token=token,
        )
        assert status == 422
        assert "test-block" in body["error"]

    def test_missing_pod_is_400(self, live_server: tuple[str, str]) -> None:
        url, token = live_server
        status, body = _post(f"{url}/tasks/some-task/answer", {"action": "accept"}, token=token)
        assert status == 400
        assert "pod is required" in body["error"]

    def test_missing_action_is_400(self, live_server: tuple[str, str]) -> None:
        url, token = live_server
        status, body = _post(f"{url}/tasks/some-task/answer", {"pod": "demo"}, token=token)
        assert status == 400
        assert "action is required" in body["error"]


class TestCreateWithBrief:
    def test_an_invalid_brief_is_422_and_enqueues_nothing(
        self, live_server: tuple[str, str]
    ) -> None:
        url, token = live_server
        _pod.build_pod("demo", _pod.pod.DEFAULT_POD_ROLES, codebase="/src/demo")
        status, _body = _post(
            f"{url}/tasks/demo",
            {"description": "fix it", "brief": {"acceptance": ["not an objective"]}},
            token=token,
        )
        assert status == 422
        assert _dispatch.read_tasks("demo") == []

    def test_a_valid_brief_is_enqueued_and_stored_on_the_task(
        self, live_server: tuple[str, str]
    ) -> None:
        url, token = live_server
        _pod.build_pod("demo", _pod.pod.DEFAULT_POD_ROLES, codebase="/src/demo")
        status, body = _post(
            f"{url}/tasks/demo",
            {"description": "fix it", "brief": {"objective": "fix the flaky test"}},
            token=token,
        )
        assert status == 200
        tasks = _dispatch.read_tasks("demo")
        assert len(tasks) == 1
        assert tasks[0]["id"] == body["task"]
        assert tasks[0]["brief"]["objective"] == "fix the flaky test"

    def test_brief_must_be_an_object(self, live_server: tuple[str, str]) -> None:
        url, token = live_server
        _pod.build_pod("demo", _pod.pod.DEFAULT_POD_ROLES, codebase="/src/demo")
        status, _body = _post(
            f"{url}/tasks/demo", {"description": "fix it", "brief": "not an object"}, token=token
        )
        assert status == 400
        assert _dispatch.read_tasks("demo") == []

    def test_no_brief_is_unaffected(self, live_server: tuple[str, str]) -> None:
        url, token = live_server
        _pod.build_pod("demo", _pod.pod.DEFAULT_POD_ROLES, codebase="/src/demo")
        status, body = _post(f"{url}/tasks/demo", {"description": "fix it"}, token=token)
        assert status == 200
        assert body["status"] == "pending"
