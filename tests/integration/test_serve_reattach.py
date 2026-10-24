"""Re-attaching to parked and failed tasks across a server restart (operator-api.spec.md).

A restart is one `ContextHTTPServer` shut down and a second started over the same
`DOCKET_HOME`; the oracles are HTTP bodies and `TASK_LIST.json`. Nothing touches the real home.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from tests.support.fakes import FakeDriver
from tests.support.home import record_isolation_off
from tests.support.llm import final as _final
from tests.support.pods import build_pod

from docket.agent.ports import ChatMessage, ChatResponse, TokenUsage, ToolCall, assistant
from docket.governance import approval as _ap
from docket.hops.application import driver as _dr
from docket.hops.application.driver import DocketDriver
from docket.interfaces.cli.commands import pod as _pod
from docket.interfaces.http.server import _DocketHandler
from docket.kernel.home import Home, current_home, use_home
from docket.kernel.threads import ContextHTTPServer
from docket.pipeline.domain import gates as _gates
from docket.pipeline.domain import spec as _pipeline
from docket.tasks.application import answers as _answers
from docket.tasks.application import queue as _queue
from docket.tasks.application import sweep as _sweep
from docket.teams import fleet as _fleet
from docket.teams import pod_settings as _pod_settings
from docket.teams import settings as _settings

SUBJECT = "docket.agent"

_TOKEN = "test-serve-token-reattach"
_CONSULT = {
    "kind": "decision",
    "message": "Which store should the cache use?",
    "options": [
        {"id": "redis", "label": "Redis", "description": "fast"},
        {"id": "sqlite", "label": "SQLite", "description": "simple"},
    ],
    "recommendation": {"optionId": "sqlite", "rationale": "no new service"},
}


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    monkeypatch.setenv("DOCKET_SERVICE_MANAGER", "none")
    home = tmp_path / ".docket"
    (home / "workspaces" / "projects").mkdir(parents=True)
    (home / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    (home / "approvals").mkdir()
    with use_home(Home(home)):
        record_isolation_off(home)
        yield


@contextlib.contextmanager
def _server() -> Iterator[str]:
    class _Handler(_DocketHandler):
        serve_token = _TOKEN

    srv = ContextHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}"
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=5)


def _call(method: str, url: str, body: dict[str, Any] | None = None) -> tuple[int, Any]:
    data = json.dumps(body if body is not None else {}).encode() if method == "POST" else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {_TOKEN}")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def _task_list(project: str = "demo") -> list[dict[str, Any]]:
    path = _settings.pod_task_list_path(project)
    return list(json.loads(path.read_text())["tasks"])


def _gated_pod() -> None:
    """A full pod whose pipeline is the default one with an approval gate on the Implementer."""
    build_pod("demo", _pod.pod.DEFAULT_POD_ROLES, codebase="/src/demo")
    spec = _pipeline.default_pipeline()
    steps = [
        step.model_copy(update={"gate": _gates.ApprovalGate()})
        if step.role == "implementer"
        else step
        for step in spec.steps
    ]
    text = json.dumps(
        spec.model_copy(update={"steps": steps}).model_dump(mode="json", by_alias=True)
    )
    path = _pod.pod.bound_pipeline_path("demo")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    _fleet.meta_set("demo-lead", "pipeline", hashlib.sha256(text.encode()).hexdigest())


class _Backend:
    def __init__(self, responses: list[ChatResponse]) -> None:
        self._responses = list(responses)

    def complete(
        self,
        messages: list[ChatMessage],
        *,
        tools: Any = (),
        max_tokens: int | None = None,
        temperature: float | None = None,
        timeout: int = 120,
    ) -> ChatResponse:
        return self._responses.pop(0)


def _consult() -> ChatResponse:
    call = ToolCall(id="c1", name="consult", arguments=json.dumps(_CONSULT))
    return ChatResponse(
        ok=True,
        message=assistant("", [call]),
        finish_reason="tool_calls",
        usage=TokenUsage(5, 5),
    )


def _park_on_consult(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> str:
    workspace = tmp_path / "codebase"
    workspace.mkdir()
    build_pod("demo", _pod.pod.DEFAULT_POD_ROLES, codebase=str(workspace))
    _fleet.meta_set("demo-implementer", "codebase", str(workspace))
    _fleet.meta_set("demo-implementer", "verifyCmd", "true")
    _fleet.meta_set(
        "demo-lead", "approvalMode", _pod_settings.PodSettings.coerce("approvalMode", "park")
    )
    backend = _Backend([_final("plan"), _consult(), _final("built with redis")])
    driver = DocketDriver(backend_factory=lambda model_name: backend)
    monkeypatch.setattr(_dr, "default_driver", lambda: driver)
    queued = _queue.enqueue_task_once("demo", "in-place task", channel="cli")[0]
    _sweep.dispatch_pod("demo", turn_timeout=60, max_tasks=1)
    return str(queued["id"])


class TestServedFromDisk:
    def test_a_fresh_instance_serves_a_waiting_approval_task_with_its_token_and_expiry(
        self,
    ) -> None:
        _gated_pod()
        task = _queue.enqueue_task_once("demo", "Ship it", channel="cli")[0]
        _sweep.dispatch_pod("demo", runner=FakeDriver())
        token = _task_list()[0]["approvalToken"]

        with _server() as first:
            status, before = _call("GET", f"{first}/tasks/demo/{task['id']}")
        with _server() as second:
            status2, after = _call("GET", f"{second}/tasks/demo/{task['id']}")
            _, approvals = _call("GET", f"{second}/approvals")

        assert (status, status2) == (200, 200)
        assert before["status"] == after["status"] == "waiting_approval"
        assert before["approvalToken"] == after["approvalToken"] == token
        record = next(a for a in approvals["pending"] if a["token"] == token)
        assert record["expiresAt"]

    def test_a_consultation_serves_its_options_from_disk(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        task_id = _park_on_consult(monkeypatch, tmp_path)
        with _server() as url:
            status, body = _call("GET", f"{url}/tasks/demo/{task_id}")

        assert status == 200
        assert body["status"] == "waiting_input"
        assert [o["id"] for o in body["question"]["options"]] == ["redis", "sqlite"]


class TestAnswerAcrossRestart:
    def test_a_grant_through_a_fresh_instance_starts_nothing_and_the_next_sweep_resumes(
        self,
    ) -> None:
        _gated_pod()
        task = _queue.enqueue_task_once("demo", "Ship it", channel="cli")[0]
        runner = FakeDriver()
        _sweep.dispatch_pod("demo", runner=runner)
        token = _task_list()[0]["approvalToken"]
        hops_before = len(runner.calls)

        with _server():
            pass
        with _server() as second:
            status, body = _call("POST", f"{second}/approvals/{token}", {"action": "grant"})

        assert status == 200
        assert body["state"] == "granted"
        parked = _task_list()[0]
        assert parked["status"] == "pending"
        assert len(runner.calls) == hops_before

        results = _sweep.dispatch_pod("demo", runner=runner, resume=True)
        assert [r.status for r in results] == ["done"]
        final = next(t for t in _task_list() if t["id"] == task["id"])
        assert [h["role"] for h in final["hops"]][:2] == ["lead", "implementer"]
        assert runner.calls[hops_before][0].rsplit("-", 1)[-1] == "implementer"

    def test_an_answer_through_a_fresh_instance_resumes_at_the_next_sweep(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        task_id = _park_on_consult(monkeypatch, tmp_path)
        with _server():
            pass
        with _server() as second:
            status, _body = _call(
                "POST",
                f"{second}/tasks/{task_id}/answer",
                {"pod": "demo", "action": "accept", "content": {"optionId": "redis"}},
            )
        assert status == 200
        assert _task_list()[0]["status"] == "pending"

        _sweep.dispatch_pod("demo", turn_timeout=60, max_tasks=1, resume=True)
        assert _task_list()[0]["status"] == "done"


class TestIdempotencyKey:
    def test_a_retry_with_the_same_key_after_a_failure_returns_the_failed_task(self) -> None:
        build_pod("demo", _pod.pod.DEFAULT_POD_ROLES, codebase="/src/demo")
        with _server() as first:
            _, created = _call(
                "POST", f"{first}/tasks/demo", {"description": "x", "idempotencyKey": "K:1"}
            )
        _sweep.dispatch_pod("demo", runner=FakeDriver(ok=False))
        assert _task_list()[0]["status"] == "failed"

        with _server() as second:
            status, again = _call(
                "POST", f"{second}/tasks/demo", {"description": "x", "idempotencyKey": "K:1"}
            )

        assert status == 200
        assert again["created"] is False
        assert again["task"] == created["task"]
        assert again["status"] == "failed"
        assert len(_task_list()) == 1


class TestExpiryStates:
    def test_an_expired_approval_denies_and_an_expired_question_blocks_after_a_restart(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _gated_pod()
        gated = _queue.enqueue_task_once("demo", "Ship it", channel="cli")[0]
        _sweep.dispatch_pod("demo", runner=FakeDriver())
        token = _task_list()[0]["approvalToken"]
        record = _ap.approval_get(token)
        record["expiresAt"] = "2000-01-01T00:00:00Z"
        (current_home().approvals_dir / f"{token}.json").write_text(json.dumps(record))

        with _server():
            pass
        assert _ap.approval_sweep_expired() == 1
        with _server() as url:
            _, denied = _call("GET", f"{url}/tasks/demo/{gated['id']}")
        assert denied["status"] == "failed"
        assert denied["failureKind"] == "approval_denied"

        asked = _park_on_consult(monkeypatch, tmp_path)
        assert asked
        assert _answers.sweep_expired_questions(now="2999-01-01T00:00:00+00:00") == 1
        with _server() as url:
            _, blocked = _call("GET", f"{url}/tasks/demo/{asked}")
        assert blocked["status"] == "blocked"
        assert blocked["blockedReason"] == "input_expired"


class TestStaleClaim:
    def test_a_stale_claim_failure_is_resumed_by_the_next_sweep(self) -> None:
        build_pod("demo", _pod.pod.DEFAULT_POD_ROLES, codebase="/src/demo")
        task = _queue.enqueue_task_once("demo", "x", channel="cli")[0]
        path = _settings.pod_task_list_path("demo")
        doc = json.loads(path.read_text())
        doc["tasks"][0].update(
            status="running", claimedAt="2000-01-01T00:00:00+00:00", claimId="gone"
        )
        path.write_text(json.dumps(doc))

        _sweep.dispatch_pod("demo", runner=FakeDriver(), max_tasks=0)
        with _server() as first:
            _, failed = _call("GET", f"{first}/tasks/demo/{task['id']}")
        assert failed["status"] == "failed"
        assert failed["failureKind"] == "stale_claim"

        with _server() as second:
            _sweep.dispatch_pod("demo", runner=FakeDriver(), resume=True)
            _, resumed = _call("GET", f"{second}/tasks/demo/{task['id']}")
        assert resumed["status"] == "done"
