"""A hop resumed after a granted approval is told to issue the approved call again.

The park, the grant and the re-run go through the real `DocketDriver`, the real tool gate, the real
approval store and the real sweep; only the model is a double. The double issues the call again
only when the last message it is sent says so, as a model that read the refusal in its session
would otherwise stop.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from tests.support.approvals import pending_token, resolve_token
from tests.support.llm import final_response
from tests.support.pods import seed_pod_isolation_off as _seed_pod
from typer.testing import CliRunner

from docket.agent.ports import ChatMessage, ChatResponse, TokenUsage, ToolCall, assistant
from docket.governance import approval as _approval
from docket.governance import approval_pregrant as _pregrants
from docket.governance.policy import install_policies
from docket.hops.application import driver as _dr
from docket.hops.application import sweep as _sweep
from docket.hops.application.driver import DocketDriver
from docket.interfaces.cli.app import app
from docket.kernel.home import current_home, use_home
from docket.tasks.application import actions as _actions
from docket.tasks.application import lifecycle as _lifecycle
from docket.tasks.application import queue as _queue
from docket.tasks.application.repository import TaskRepository
from docket.teams import fleet as _fleet

SUBJECT = "docket.hops.application.compose"

CUE = "issue the same call again"
CALL = ToolCall(id="c1", name="bash", arguments=json.dumps({"command": "rm -rf build"}))


def _tool_call_response() -> ChatResponse:
    return ChatResponse(
        ok=True,
        message=assistant("", tool_calls=[CALL]),
        finish_reason="tool_calls",
        usage=TokenUsage(10, 5),
    )


class _CueBackend:
    """Issues the call when the message it was just sent says to; otherwise finishes in text."""

    def __init__(self) -> None:
        self.calls: list[list[ChatMessage]] = []

    def complete(self, messages: list[ChatMessage], **_: Any) -> ChatResponse:
        self.calls.append(list(messages))
        last = messages[-1]
        if last.role == "user" and CUE in last.content.lower():
            return _tool_call_response()
        return final_response("implementer done")


class _ParkBackend:
    """The lead plans, then the implementer issues the gated call, which parks."""

    def __init__(self) -> None:
        self._script = [final_response("lead plan"), _tool_call_response()]

    def complete(self, messages: list[ChatMessage], **_: Any) -> ChatResponse:
        return self._script.pop(0)


@pytest.fixture()
def parked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[Path, str]]:
    """A task parked on the implementer's gated `bash` call: the trace dir and the approval token."""
    with (
        _seed_pod(tmp_path) as home,
        use_home(dataclasses.replace(current_home(), tool_approval_timeout=2)),
    ):
        install_policies()
        _fleet.meta_set("demo-lead", "approvalMode", "park")
        park = _ParkBackend()
        driver = DocketDriver(backend_factory=lambda model: park)
        monkeypatch.setattr(_dr, "default_driver", lambda: driver)
        _queue.enqueue_task_once("demo", "clean the build dir", channel="cli")
        _sweep.dispatch_pod("demo")
        token = pending_token("demo")
        assert token
        yield home, token


def _resume(monkeypatch: pytest.MonkeyPatch) -> tuple[_CueBackend, str]:
    backend = _CueBackend()
    driver = DocketDriver(backend_factory=lambda model: backend)
    monkeypatch.setattr(_dr, "default_driver", lambda: driver)
    (result,) = _sweep.dispatch_pod("demo")
    return backend, result.status


def _events(home: Path, event_type: str) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for path in (home / "state" / "traces" / "demo").glob("*.jsonl"):
        for line in path.read_text().splitlines():
            record = json.loads(line)
            if record["event_type"] == event_type:
                found.append(record)
    return found


class TestAGrantedCallIsToldToTheResumedHop:
    def test_a_model_that_reissues_only_when_told_runs_the_approved_call(
        self, parked: tuple[Path, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home, token = parked
        resolve_token(token, "approve_once", channel="cli", actor="")

        backend, status = _resume(monkeypatch)

        assert status == "done"
        assert len(backend.calls) == 2  # the call was issued, then the hop ended
        told = backend.calls[0][-1].content
        assert "bash" in told and "rm -rf build" in told
        assert _pregrants.pending_pregrants(_only_task()) == []
        assert _events(home, "approval_unused") == []

    def test_a_model_that_ignores_the_cue_leaves_an_unused_event_and_the_task_status(
        self, parked: tuple[Path, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home, token = parked
        resolve_token(token, "approve_once", channel="cli", actor="")

        def _deaf(messages: list[ChatMessage], **_: Any) -> ChatResponse:
            return final_response("Stopping: the send was refused.")

        backend = _CueBackend()
        monkeypatch.setattr(backend, "complete", _deaf)
        driver = DocketDriver(backend_factory=lambda model: backend)
        monkeypatch.setattr(_dr, "default_driver", lambda: driver)

        (result,) = _sweep.dispatch_pod("demo")

        assert result.status == "done"
        (event,) = _events(home, "approval_unused")
        assert event["payload"]["task"] == _only_task()
        assert event["payload"]["tool"] == "bash"
        assert event["payload"]["role"] == "implementer"
        assert event["payload"]["escalation"].startswith("esc-")
        assert token not in json.dumps(event)
        assert [p.token for p in _pregrants.pending_pregrants(_only_task())] == [token]
        shown = CliRunner().invoke(app, ["task", "show", _only_task(), "--pod", "demo"])
        assert "Approved, not used" in shown.output and "approved bash call again" in shown.output


class TestADeniedCallIsNotReissued:
    def test_a_denial_still_fails_the_task_and_a_retried_hop_is_told_it_was_refused(
        self, parked: tuple[Path, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home, token = parked
        _approval.approval_deny(token, channel="cli")
        assert _actions.resolve_waiting_approval(token, "denied") is True
        task = TaskRepository.for_pod("demo").list()[0]
        assert (task.status, task.failure_kind) == ("failed", "approval_denied")

        assert _lifecycle.retry_task("demo", task.id)
        backend, status = _resume(monkeypatch)

        assert status == "done"
        assert len(backend.calls) == 1  # the model was not told to issue it again
        told = backend.calls[0][-1].content
        assert "refused" in told and "rm -rf build" in told
        assert CUE not in told.lower()
        assert _events(home, "approval_unused") == []


def _only_task() -> str:
    return TaskRepository.for_pod("demo").list()[0].id
