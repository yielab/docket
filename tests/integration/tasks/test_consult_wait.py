"""``consult`` in pod dispatch under ``approvalMode: wait``: the hop blocks for the person at the
terminal, who resolves the escalation, and the same turn goes on with their answer
(operator-loop.spec.md "Consult" item 3).

Real dispatch over a scripted chat backend on a worker thread, and the real `resolve` called from
the test as the progress prompt, `docket task answer` or any other surface would.
"""

from __future__ import annotations

import dataclasses
import json
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from tests.support.approvals import answer_question
from tests.support.home import record_isolation_off
from tests.support.llm import final as _final
from tests.support.loop_harness import unframed
from tests.support.pods import build_pod

from docket.agent.ports import ChatMessage, ChatResponse, TokenUsage, ToolCall, assistant
from docket.hops.application import driver as _dr
from docket.hops.application import sweep as _sweep
from docket.hops.application.driver import DocketDriver
from docket.interfaces.cli.commands import pod as _pod
from docket.kernel import threads as _threads
from docket.kernel.home import Home, current_home, use_home
from docket.kernel.operator_contract import Escalation
from docket.platform import list_escalations, read_escalation
from docket.tasks.application import escalations as _esc
from docket.tasks.application import queue as _queue
from docket.tasks.application.repository import TaskRepository
from docket.tasks.domain.task import TaskRecord
from docket.teams import fleet as _fleet
from docket.teams import pod_settings as _pod_settings

SUBJECT = "docket.tasks.application.consult"

# One generous bound for every wait on the dispatch thread. A wait ends when the thing it names
# happens or the thread ends, so the bound is only ever reached by a hang, never by a slow host;
# the product's own timeouts sit far above it so they cannot fire first.
_WAIT_S = 120.0
_PRODUCT_TIMEOUT_S = 600

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
def _hermetic(tmp_path: Path) -> Iterator[None]:
    home = tmp_path / ".docket"
    (home / "state" / "workspaces" / "projects").mkdir(parents=True)
    (home / "state" / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    with use_home(Home(home)):
        record_isolation_off(home)
        with use_home(
            dataclasses.replace(
                current_home(),
                tool_approval_poll_interval_s=0.02,
                tool_approval_timeout=_PRODUCT_TIMEOUT_S,
            )
        ):
            yield


class _Backend:
    def __init__(self, responses: list[ChatResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[list[ChatMessage]] = []

    def complete(
        self,
        messages: list[ChatMessage],
        *,
        tools: Any = (),
        max_tokens: int | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
        tool_choice: str | None = None,
        timeout: int = 120,
    ) -> ChatResponse:
        self.calls.append(list(messages))
        return self._responses.pop(0)


def _consult_call(count: int = 1) -> ChatResponse:
    questions = [{**_CONSULT, "message": f"Question {n}?"} for n in range(1, count + 1)]
    call = ToolCall(id="c1", name="consult", arguments=json.dumps({"questions": questions}))
    return ChatResponse(
        ok=True,
        message=assistant("", [call]),
        finish_reason="tool_calls",
        usage=TokenUsage(5, 5),
    )


def _begin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, backend: _Backend
) -> tuple[threading.Thread, str]:
    """A pod in ``wait`` mode with one queued task, dispatched on a worker thread."""
    workspace = tmp_path / "codebase"
    workspace.mkdir()
    build_pod("demo", _pod.pod.DEFAULT_POD_ROLES, codebase=str(workspace))
    _fleet.meta_set("demo-implementer", "codebase", str(workspace))
    _fleet.meta_set("demo-implementer", "verifyCmd", "true")
    _fleet.meta_set(
        "demo-lead", "approvalMode", _pod_settings.PodSettings.coerce("approvalMode", "wait")
    )
    _fleet.meta_set(
        "demo-lead", "requireVerify", _pod_settings.PodSettings.coerce("requireVerify", "true")
    )
    driver = DocketDriver(backend_factory=lambda model_name: backend)
    monkeypatch.setattr(_dr, "default_driver", lambda: driver)
    queued = _queue.enqueue_task_once("demo", "in-place task", channel="cli")[0]
    worker = _threads.new_thread(
        lambda: _sweep.dispatch_pod("demo", turn_timeout=_PRODUCT_TIMEOUT_S, max_tasks=1)
    )
    worker.start()
    return worker, str(queued.id)


def _wait_until(worker: threading.Thread, what: str, ready: Callable[[], bool]) -> None:
    """Return once *ready* holds. Fails naming *what* if the dispatch thread ends first or
    ``_WAIT_S`` passes; ``worker.join`` is the wait, so the thread ending wakes it at once."""
    end = time.monotonic() + _WAIT_S
    while not ready():
        assert worker.is_alive(), f"the dispatch thread ended before {what}"
        assert time.monotonic() < end, f"{what} did not happen within {_WAIT_S:.0f}s"
        worker.join(0.01)


def _the_waiting_consult(worker: threading.Thread) -> Escalation:
    """The consult escalation the blocked turn opened, once it is pending."""

    def pending() -> list[Escalation]:
        return [e for e in list_escalations(state="pending") if e.kind == "consult"]

    _wait_until(worker, "the turn opened a consult escalation", lambda: bool(pending()))
    return pending()[0]


def _finished(worker: threading.Thread, after: str) -> None:
    """The dispatch thread ends on its own once the turn has what it waited for."""
    worker.join(_WAIT_S)
    assert not worker.is_alive(), f"the dispatch thread did not finish after {after}"


def _task(task_id: str) -> TaskRecord:
    record = TaskRepository.for_pod("demo").get(task_id)
    assert record is not None
    return record


def _tool_results(backend: _Backend) -> list[str]:
    return [unframed(m.content) for m in backend.calls[-1] if m.role == "tool"]


class TestAnsweredInPlace:
    def test_an_option_answer_goes_back_to_the_model_in_the_same_turn(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        backend = _Backend([_final("plan"), _consult_call(), _final("built with redis")])
        worker, task_id = _begin(tmp_path, monkeypatch, backend)

        waiting = _the_waiting_consult(worker)
        assert _task(task_id).status == "running"
        _esc.resolve(waiting.id, "redis", {"note": "hot path"}, by="alice", channel="cli")
        _finished(worker, "the option answer")

        task = _task(task_id)
        assert task.status == "done"
        (answer,) = _tool_results(backend)
        assert f"Operator answered your consultation {waiting.id}:" in answer
        assert "option redis (Redis)" in answer and "hot path" in answer
        stored = read_escalation(waiting.id)
        assert stored is not None and stored.state == "resolved"
        assert stored.resolution is not None and stored.resolution.applied_at is not None
        assert not any(current_home().consult_parked_dir.glob("*.json"))

    def test_a_decline_tells_the_model_to_decide_itself(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        backend = _Backend([_final("plan"), _consult_call(), _final("decided alone")])
        worker, task_id = _begin(tmp_path, monkeypatch, backend)

        _esc.resolve(_the_waiting_consult(worker).id, "decline", None, by="alice", channel="cli")
        _finished(worker, "the decline")

        assert _task(task_id).status == "done"
        (answer,) = _tool_results(backend)
        assert answer.endswith("declined. Decide yourself.")

    def test_an_answer_by_the_task_goes_through_the_same_record(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        backend = _Backend([_final("plan"), _consult_call(), _final("built with sqlite")])
        worker, task_id = _begin(tmp_path, monkeypatch, backend)
        _the_waiting_consult(worker)

        answer_question("demo", task_id, "accept", {"optionId": "sqlite"})
        _finished(worker, "the answer by the task")

        (answer,) = _tool_results(backend)
        assert "option sqlite (SQLite)" in answer
        assert _task(task_id).status == "done"

    def test_the_wait_offers_the_question_options_not_a_grant(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        backend = _Backend([_final("plan"), _consult_call(), _final("built")])
        worker, task_id = _begin(tmp_path, monkeypatch, backend)
        waiting = _the_waiting_consult(worker)

        with pytest.raises(_esc.EscalationInvalid, match="redis, sqlite, decline"):
            _esc.resolve(waiting.id, "approve_once", None, by="alice", channel="cli")
        _esc.resolve(waiting.id, "redis", None, by="alice", channel="cli")
        _finished(worker, "the option answer")

        assert _task(task_id).status == "done"


class TestSeveralQuestions:
    def test_every_part_is_open_while_the_turn_waits_and_the_answers_return_in_order(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        backend = _Backend([_final("plan"), _consult_call(2), _final("built")])
        worker, task_id = _begin(tmp_path, monkeypatch, backend)
        _the_waiting_consult(worker)
        _wait_until(
            worker,
            "both parts of the consultation were open",
            lambda: len(list_escalations(state="pending")) >= 2,
        )

        first, second = sorted(
            list_escalations(state="pending"), key=lambda e: e.part.index if e.part else 0
        )
        assert [(e.part.index, e.part.count) for e in (first, second) if e.part] == [(1, 2), (2, 2)]
        _esc.resolve(second.id, "sqlite", None, by="alice", channel="cli")
        assert _task(task_id).status == "running"
        _esc.resolve(first.id, "redis", None, by="alice", channel="cli")
        _finished(worker, "the last part was answered")

        assert _task(task_id).status == "done"
        (answer,) = _tool_results(backend)
        lines = answer.splitlines()
        assert f"{first.id} (question 1 of 2): option redis (Redis)" in lines[0]
        assert f"{second.id} (question 2 of 2): option sqlite (SQLite)" in lines[1]


class TestNobodyAnswers:
    def test_a_timeout_returns_no_answer_and_the_turn_goes_on(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        with use_home(dataclasses.replace(current_home(), tool_approval_timeout=1)):
            backend = _Backend([_final("plan"), _consult_call(), _final("decided alone")])
            worker, task_id = _begin(tmp_path, monkeypatch, backend)

            _finished(worker, "the consultation expired unanswered")

        assert _task(task_id).status == "done"
        assert _tool_results(backend) == ["no answer; decide yourself"]
