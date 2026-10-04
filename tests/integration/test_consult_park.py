"""``consult`` in pod dispatch: the hop parks the task ``waiting_input`` and an answer re-enters
the same role's step (operator-loop.spec.md "Consult").

Real dispatch over a scripted chat backend; nothing touches the real DOCKET_HOME.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

import pytest
from tests.conftest import repoint_docket_home

from docket.core import answers as _answers
from docket.core import corrections as _corrections
from docket.core import dispatch as _dispatch
from docket.core import harness_pipeline as hp
from docket.core import inbox as _inbox
from docket.core.harness import Answer
from docket.core.llm import ChatMessage, ChatResponse, TokenUsage, ToolCall, assistant
from docket.edges.adapters import docket_runtime as _dr
from docket.edges.adapters.docket_runtime import DocketDriver

SUBJECT = "docket.core.consult"

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
def _hermetic(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DOCKET_SERVICE_MANAGER", "none")
    home = tmp_path / ".docket"
    (home / "workspaces" / "projects").mkdir(parents=True)
    (home / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    repoint_docket_home(monkeypatch, home)


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
        timeout: int = 120,
    ) -> ChatResponse:
        self.calls.append(list(messages))
        return self._responses.pop(0)


def _final(text: str) -> ChatResponse:
    return ChatResponse(
        ok=True, message=assistant(text), finish_reason="stop", usage=TokenUsage(5, 5)
    )


def _consult(call_id: str = "c1") -> ChatResponse:
    call = ToolCall(id=call_id, name="consult", arguments=json.dumps(_CONSULT))
    return ChatResponse(
        ok=True,
        message=assistant("", [call]),
        finish_reason="tool_calls",
        usage=TokenUsage(5, 5),
    )


def _start(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    backend: _Backend,
    mode: Literal["wait", "park", "refuse"] = "park",
    next_answer: Any = None,
) -> hp.RecipeRun:
    recipe = tmp_path / "recipe"
    recipe.mkdir()
    (recipe / "pod.yaml").write_text("kind: pod\nname: x\n", encoding="utf-8")
    workspace = tmp_path / "codebase"
    workspace.mkdir()
    driver = DocketDriver(backend_factory=lambda model_name: backend)
    monkeypatch.setattr(_dr, "default_driver", lambda: driver)
    return hp.run_recipe_task(
        workspace,
        str(recipe),
        "in-place task",
        model="test-model",
        approval_mode=mode,
        timeout=60,
        verify_cmd="true",
        next_answer=next_answer,
    )


def _task(run: hp.RecipeRun) -> dict[str, Any]:
    return next(t for t in _dispatch.read_tasks(run.project) if t["id"] == run.task["id"])


def _resume(run: hp.RecipeRun) -> dict[str, Any]:
    _dispatch.dispatch_pod(run.project, turn_timeout=60, max_tasks=1)
    return _task(run)


def _answer(run: hp.RecipeRun, action: str, content: dict[str, Any] | None) -> None:
    _answers.answer_task(
        run.project, str(run.task["id"]), action, content, channel="cli", actor="op"
    )


class TestPark:
    def test_an_implementer_consult_parks_the_task_with_the_question(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        run = _start(tmp_path, monkeypatch, _Backend([_final("plan"), _consult()]))

        task = _task(run)
        assert task["status"] == "waiting_input"
        question = task["question"]
        assert question["kind"] == "decision"
        assert question["taskId"] == task["id"]
        assert question["step"] == "implementer"
        assert [o["id"] for o in question["options"]] == ["redis", "sqlite"]
        assert question["recommendation"]["optionId"] == "sqlite"
        assert task["consultations"] == 1

        view = _inbox.build_inbox(now=_dispatch._now())
        assert [v.id for v in view.needs_you if getattr(v, "pod", "") == run.project] == [
            task["id"]
        ]

    def test_refuse_still_fails_the_task_blocked(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        run = _start(tmp_path, monkeypatch, _Backend([_final("plan"), _consult()]), "refuse")

        task = _task(run)
        assert task["status"] != "waiting_input"
        assert "approval_unavailable" in json.dumps(task["hops"])


class TestAnswer:
    def test_an_option_answer_resumes_the_implementer_with_the_answer_in_its_message(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        backend = _Backend([_final("plan"), _consult(), _final("built with redis")])
        run = _start(tmp_path, monkeypatch, backend)

        _answer(run, "accept", {"optionId": "redis"})
        assert _task(run)["status"] == "pending"
        task = _resume(run)

        assert task["status"] == "done"
        resumed = backend.calls[-1][-1]
        assert resumed.role == "user"
        assert "Operator answered your consultation" in resumed.content
        assert "option redis (Redis)" in resumed.content
        assert task["answers"][0]["step"] == "implementer"
        assert "consultAnswer" not in task

    def test_a_declined_answer_resumes_with_declined_and_records_one_correction(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        backend = _Backend([_final("plan"), _consult(), _final("decided myself")])
        run = _start(tmp_path, monkeypatch, backend)

        _answer(run, "decline", None)
        task = _resume(run)

        assert task["status"] == "done"
        assert "declined" in backend.calls[-1][-1].content
        assert len(_corrections.read(run.project)) == 1

    def test_accept_without_an_option_id_is_refused_and_the_task_keeps_waiting(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        run = _start(tmp_path, monkeypatch, _Backend([_final("plan"), _consult()]))

        with pytest.raises(_answers.AnswerError):
            _answer(run, "accept", {"note": "whatever"})
        with pytest.raises(_answers.AnswerError):
            _answer(run, "accept", {"optionId": "mongo"})

        task = _task(run)
        assert task["status"] == "waiting_input"
        assert task.get("answers", []) == []


class TestTaskWideCap:
    def test_a_fourth_consult_across_hops_is_refused_as_budget_exhausted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        backend = _Backend(
            [
                _final("plan"),
                _consult("c1"),
                _consult("c2"),
                _consult("c3"),
                _consult("c4"),
                _final("deciding alone"),
            ]
        )
        run = _start(tmp_path, monkeypatch, backend)
        for expected in (1, 2):
            _answer(run, "accept", {"optionId": "redis"})
            task = _resume(run)
            assert task["status"] == "waiting_input"
            assert task["consultations"] == expected + 1
        _answer(run, "accept", {"optionId": "sqlite"})
        task = _resume(run)

        assert task["status"] == "done"
        assert task["consultations"] == 3
        tool_msgs = [m.content for m in backend.calls[-1] if m.role == "tool"]
        assert "consultation budget exhausted; decide yourself" in tool_msgs[-1]


class TestRecipeHarness:
    def test_a_question_id_answer_resumes_a_consult_end_to_end(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        backend = _Backend([_final("plan"), _consult(), _final("built")])
        seen: list[dict[str, Any]] = []

        def _next(question: dict[str, Any]) -> Answer:
            seen.append(question)
            return Answer(
                questionId=question["id"], action="accept", content={"optionId": "sqlite"}
            )

        run = _start(tmp_path, monkeypatch, backend, "wait", _next)

        assert len(seen) == 1 and seen[0]["kind"] == "decision"
        assert run.task["status"] == "done"
        assert "option sqlite (SQLite)" in backend.calls[-1][-1].content
