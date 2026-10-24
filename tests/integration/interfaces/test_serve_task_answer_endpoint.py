"""POST /tasks/<id>/answer — resolving a parked question over HTTP.

The HTTP counterpart of `docket task answer` and the MCP `task_answer` tool: same
`hops.application.answers.answer_task` call (`channel="http"`), so validation/screening/resume are
byte-for-byte identical to every other surface. Covers auth, the happy path (a `TaskView`
response, the durably appended answer, the `actor` field), the error mappings (`422`/`409`/
`404`/`400`), and `POST /tasks/<project>`'s optional `brief` field -- `422` on a malformed one,
and `422` again on a well-formed one naming the `tasks.application.queue.enqueue_task_once` parameter it still
lacks (see `interfaces/cli/commands/pod.py::_pod_delegate`'s identical contention note).
"""

from __future__ import annotations

import dataclasses
import threading
from pathlib import Path

import pytest
from tests.support import http as _support_http
from tests.support import pods as _support_pods
from tests.support.http import post as _post
from tests.support.pods import build_pod
from tests.support.pods import seed_parked_task as _seed_parked_task

from docket.governance import audit as _audit
from docket.interfaces.cli.commands import pod as _pod
from docket.interfaces.http.server import _DocketHandler
from docket.kernel.home import current_home, use_home
from docket.kernel.threads import ContextHTTPServer
from docket.tasks.application import queue as _queue
from docket.tasks.application.repository import TaskRepository

live_server = _support_http.live_server

pod_home = _support_pods.pod_home

SUBJECT = "docket.interfaces.http.server"

_TEST_TOKEN = "test-serve-token"

_ASK_PIPELINE_YAML = """\
name: ask
steps:
  - lead: lead
  - ask:
      input:
        from: lead
  - implementer: implementer
"""


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
        self, tmp_path: Path, pod_home: Path
    ) -> None:
        parked = _seed_parked_task("demo")

        approvals_dir = pod_home / "approvals"
        approvals_dir.mkdir(exist_ok=True)
        with use_home(dataclasses.replace(current_home(), approvals_dir_override=approvals_dir)):

            class _Handler(_DocketHandler):
                serve_token = _TEST_TOKEN

            srv = ContextHTTPServer(("127.0.0.1", 0), _Handler)
            port = srv.server_address[1]
            t = threading.Thread(target=srv.serve_forever, daemon=True)
            t.start()
            try:
                status, body = _post(
                    f"http://127.0.0.1:{port}/tasks/{parked.id}/answer",
                    {"pod": "demo", "action": "accept", "content": {"answer": "ship it"}},
                    token=_TEST_TOKEN,
                )
            finally:
                srv.shutdown()

            assert status == 200
            assert body["id"] == parked.id
            assert body["pod"] == "demo"

            after = TaskRepository.for_pod("demo").list()[0]
            assert after.answers[0].content == {"answer": "ship it"}
            assert after.answers[0].channel == "http"
            assert after.answers[0].actor == "http"

    def test_actor_field_labels_the_audit_entry(self, pod_home: Path) -> None:
        parked = _seed_parked_task("demo")
        with use_home(
            dataclasses.replace(current_home(), approvals_dir_override=pod_home / "approvals")
        ):
            (pod_home / "approvals").mkdir(exist_ok=True)

            class _Handler(_DocketHandler):
                serve_token = _TEST_TOKEN

            srv = ContextHTTPServer(("127.0.0.1", 0), _Handler)
            port = srv.server_address[1]
            t = threading.Thread(target=srv.serve_forever, daemon=True)
            t.start()
            try:
                status, _body = _post(
                    f"http://127.0.0.1:{port}/tasks/{parked.id}/answer",
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
        build_pod("demo", _pod.pod.DEFAULT_POD_ROLES, codebase="/src/demo")
        status, body = _post(
            f"{url}/tasks/no-such-task/answer",
            {"pod": "demo", "action": "accept", "content": {"answer": "x"}},
            token=token,
        )
        assert status == 404
        assert "not found" in body["error"]

    def test_not_waiting_input_is_409(self, live_server: tuple[str, str]) -> None:
        url, token = live_server
        build_pod("demo", _pod.pod.DEFAULT_POD_ROLES, codebase="/src/demo")
        plain_task = _queue.enqueue_task_once("demo", "plain task", channel="cli")[0]
        status, body = _post(
            f"{url}/tasks/{plain_task.id}/answer",
            {"pod": "demo", "action": "accept", "content": {"answer": "x"}},
            token=token,
        )
        assert status == 409
        assert "waiting_input" in body["error"]

    def test_schema_violation_is_422(self, live_server: tuple[str, str]) -> None:
        url, token = live_server
        parked = _seed_parked_task("demo")
        status, body = _post(
            f"{url}/tasks/{parked.id}/answer",
            {"pod": "demo", "action": "accept", "content": {}},
            token=token,
        )
        assert status == 422
        assert "answer" in body["error"]

    def test_policy_rejection_is_422_naming_the_policy(
        self, live_server: tuple[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        url, token = live_server
        parked = _seed_parked_task("demo")
        from docket.governance import policy as _policy

        monkeypatch.setattr(
            _policy,
            "policy_eval_detail",
            lambda *a, **k: _policy.PolicyHit(action="block", policy_id="test-block"),
        )
        status, body = _post(
            f"{url}/tasks/{parked.id}/answer",
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
        build_pod("demo", _pod.pod.DEFAULT_POD_ROLES, codebase="/src/demo")
        status, _body = _post(
            f"{url}/tasks/demo",
            {"description": "fix it", "brief": {"acceptance": ["not an objective"]}},
            token=token,
        )
        assert status == 422
        assert TaskRepository.for_pod("demo").list() == []

    def test_a_valid_brief_is_enqueued_and_stored_on_the_task(
        self, live_server: tuple[str, str]
    ) -> None:
        url, token = live_server
        build_pod("demo", _pod.pod.DEFAULT_POD_ROLES, codebase="/src/demo")
        status, body = _post(
            f"{url}/tasks/demo",
            {"description": "fix it", "brief": {"objective": "fix the flaky test"}},
            token=token,
        )
        assert status == 201
        tasks = TaskRepository.for_pod("demo").list()
        assert len(tasks) == 1
        assert tasks[0].id == body["task"]
        assert tasks[0].brief is not None
        assert tasks[0].brief.objective == "fix the flaky test"

    def test_brief_must_be_an_object(self, live_server: tuple[str, str]) -> None:
        url, token = live_server
        build_pod("demo", _pod.pod.DEFAULT_POD_ROLES, codebase="/src/demo")
        status, _body = _post(
            f"{url}/tasks/demo", {"description": "fix it", "brief": "not an object"}, token=token
        )
        assert status == 400
        assert TaskRepository.for_pod("demo").list() == []

    def test_no_brief_is_unaffected(self, live_server: tuple[str, str]) -> None:
        url, token = live_server
        build_pod("demo", _pod.pod.DEFAULT_POD_ROLES, codebase="/src/demo")
        status, body = _post(f"{url}/tasks/demo", {"description": "fix it"}, token=token)
        assert status == 201
        assert body["status"] == "pending"
