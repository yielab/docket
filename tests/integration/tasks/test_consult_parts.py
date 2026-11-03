"""One ``consult`` call that asks several questions opens one escalation per question, and the
step stays parked until every part is settled (operator-loop.spec.md "Escalations" item 18).

Real dispatch over a scripted chat backend; nothing touches the real DOCKET_HOME.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from tests.support.home import record_isolation_off
from tests.support.llm import final as _final
from tests.support.pods import build_pod

from docket.agent.ports import ChatMessage, ChatResponse, TokenUsage, ToolCall, assistant
from docket.hops.application import driver as _dr
from docket.hops.application import sweep as _sweep
from docket.hops.application.driver import DocketDriver
from docket.interfaces.cli.commands import pod as _pod
from docket.kernel.home import Home, use_home
from docket.kernel.operator_contract import Escalation
from docket.operator import inbox as _inbox
from docket.platform import list_escalations
from docket.tasks.application import escalations as _esc
from docket.tasks.application import queue as _queue
from docket.tasks.application.answers import consult_note
from docket.tasks.application.repository import TaskRepository
from docket.tasks.domain.task import TaskRecord
from docket.teams import fleet as _fleet
from docket.teams import pod_settings as _pod_settings

SUBJECT = "docket.tasks.application.consult"


def _question(n: int) -> dict[str, Any]:
    return {
        "kind": "decision",
        "message": f"Question {n}: which store?",
        "options": [
            {"id": "redis", "label": "Redis", "description": "use Redis"},
            {"id": "sqlite", "label": "SQLite", "description": "use SQLite"},
        ],
        "recommendation": {"optionId": "sqlite", "rationale": "no new service"},
    }


@pytest.fixture(autouse=True)
def _fresh_home(tmp_path: Path) -> Iterator[None]:
    home = tmp_path / ".docket"
    (home / "state" / "workspaces" / "projects").mkdir(parents=True)
    (home / "state" / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    with use_home(Home(home)):
        record_isolation_off(home)
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


def _consult(count: int) -> ChatResponse:
    arguments = json.dumps({"questions": [_question(n) for n in range(1, count + 1)]})
    call = ToolCall(id="c1", name="consult", arguments=arguments)
    return ChatResponse(
        ok=True,
        message=assistant("", [call]),
        finish_reason="tool_calls",
        usage=TokenUsage(5, 5),
    )


@dataclass(frozen=True)
class _Run:
    project: str
    task_id: str


def _start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, backend: _Backend, consult_mode: str = "park"
) -> _Run:
    workspace = tmp_path / "codebase"
    workspace.mkdir()
    build_pod("demo", _pod.pod.DEFAULT_POD_ROLES, codebase=str(workspace))
    _fleet.meta_set("demo-implementer", "codebase", str(workspace))
    _fleet.meta_set("demo-implementer", "verifyCmd", "true")
    _fleet.meta_set(
        "demo-lead", "approvalMode", _pod_settings.PodSettings.coerce("approvalMode", "park")
    )
    _fleet.meta_set(
        "demo-lead", "consultMode", _pod_settings.PodSettings.coerce("consultMode", consult_mode)
    )
    _fleet.meta_set(
        "demo-lead", "requireVerify", _pod_settings.PodSettings.coerce("requireVerify", "true")
    )
    driver = DocketDriver(backend_factory=lambda model_name: backend)
    monkeypatch.setattr(_dr, "default_driver", lambda: driver)
    queued = _queue.enqueue_task_once("demo", "in-place task", channel="cli")[0]
    _sweep.dispatch_pod("demo", turn_timeout=60, max_tasks=1)
    return _Run("demo", str(queued.id))


def _stored(run: _Run) -> TaskRecord:
    record = TaskRepository.for_pod(run.project).get(run.task_id)
    assert record is not None
    return record


def _parts(run: _Run) -> list[Escalation]:
    """The task's consult escalations in part order."""
    found = [
        e
        for e in list_escalations()
        if (e.pod, e.task, e.kind) == (run.project, run.task_id, "consult")
    ]
    return sorted(found, key=lambda e: e.part.index if e.part else 0)


def _answer(escalation: Escalation, option: str) -> None:
    _esc.resolve(escalation.id, option, None, by="op", channel="cli")


class TestOpen:
    def test_three_questions_open_three_escalations_numbered_one_to_three_of_three(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        run = _start(tmp_path, monkeypatch, _Backend([_final("plan"), _consult(3)]))

        task = _stored(run)
        parts = _parts(run)
        assert task.status == "waiting_input" and task.consultations == 3
        assert [(e.part.index, e.part.count) for e in parts if e.part] == [(1, 3), (2, 3), (3, 3)]
        assert [e.prompt for e in parts] == [f"Question {n}: which store?" for n in (1, 2, 3)]
        assert {(e.step, e.state) for e in parts} == {("implementer", "pending")}
        assert task.escalations[-3:] == [e.id for e in parts]
        view = _inbox.build_inbox(now="2026-11-03T10:00:00+00:00")
        assert {e.id for e in view.escalations if e.task == run.task_id} == {e.id for e in parts}

    def test_one_question_is_part_one_of_one(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        run = _start(tmp_path, monkeypatch, _Backend([_final("plan"), _consult(1)]))

        (only,) = _parts(run)
        assert only.part is not None and (only.part.index, only.part.count) == (1, 1)


class TestAnswer:
    def test_answering_one_leaves_the_task_parked_until_the_last_is_answered(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        run = _start(tmp_path, monkeypatch, _Backend([_final("plan"), _consult(3)]))
        first, second, third = _parts(run)

        _answer(first, "redis")
        assert _stored(run).status == "waiting_input"
        _answer(second, "sqlite")
        assert _stored(run).status == "waiting_input"
        assert consult_note(_stored(run), "implementer") == ""
        _answer(third, "redis")

        assert _stored(run).status == "pending"

    def test_the_answers_reach_the_turn_together_in_question_order(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        backend = _Backend([_final("plan"), _consult(3), _final("built")])
        run = _start(tmp_path, monkeypatch, backend)
        first, second, third = _parts(run)

        _answer(third, "redis")
        _answer(first, "sqlite")
        _answer(second, "redis")
        _sweep.dispatch_pod(run.project, turn_timeout=60, max_tasks=1)

        assert _stored(run).status == "done"
        resumed = backend.calls[-1][-1]
        assert resumed.role == "user"
        lines = [line for line in resumed.content.splitlines() if "Operator answered" in line]
        assert lines == [
            f"Operator answered your consultation {first.id} (question 1 of 3): "
            "option sqlite (SQLite)",
            f"Operator answered your consultation {second.id} (question 2 of 3): "
            "option redis (Redis)",
            f"Operator answered your consultation {third.id} (question 3 of 3): "
            "option redis (Redis)",
        ]
        assert consult_note(_stored(run), "implementer") == ""

    def test_a_declined_part_is_declined_and_the_others_keep_their_answers(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        backend = _Backend([_final("plan"), _consult(2), _final("built")])
        run = _start(tmp_path, monkeypatch, backend)
        first, second = _parts(run)

        _answer(first, "decline")
        _answer(second, "redis")
        _sweep.dispatch_pod(run.project, turn_timeout=60, max_tasks=1)

        text = backend.calls[-1][-1].content
        assert "(question 1 of 2): declined. Decide yourself." in text
        assert "(question 2 of 2): option redis (Redis)" in text

    def test_an_answered_part_cannot_be_answered_again(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        run = _start(tmp_path, monkeypatch, _Backend([_final("plan"), _consult(2)]))
        first, _ = _parts(run)
        _answer(first, "redis")

        with pytest.raises(_esc.EscalationNotPending):
            _answer(first, "sqlite")


class TestDecide:
    def test_under_consult_mode_decide_each_part_is_decided_by_its_recommendation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        backend = _Backend([_final("plan"), _consult(3), _final("built")])
        run = _start(tmp_path, monkeypatch, backend, consult_mode="decide")

        task = _stored(run)
        parts = _parts(run)
        assert task.status == "done" and task.consultations == 3
        assert [(e.state, e.policy) for e in parts] == [("decided", "recommendation")] * 3
        assert [(e.part.index, e.part.count) for e in parts if e.part] == [(1, 3), (2, 3), (3, 3)]
        (tool_result,) = [m.content for m in backend.calls[-1] if m.role == "tool"]
        assert [line.split(":")[0] for line in tool_result.splitlines()] == [
            "Question 1 of 3",
            "Question 2 of 3",
            "Question 3 of 3",
        ]
