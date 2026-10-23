"""``consult`` in pod dispatch: the hop parks the task ``waiting_input`` and an answer re-enters
the same role's step (operator-loop.spec.md "Consult").

Real dispatch over a scripted chat backend; nothing touches the real DOCKET_HOME.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import pytest
from tests.conftest import record_isolation_off
from tests.pods import build_pod

from docket.agent import driver as _dr
from docket.agent.driver import DocketDriver
from docket.agent.llm import ChatMessage, ChatResponse, TokenUsage, ToolCall, assistant
from docket.interfaces.cli.commands import pod as _pod
from docket.kernel import clock as _clock
from docket.kernel.home import Home, current_home, use_home
from docket.operator import inbox as _inbox
from docket.operator import notify as _notify
from docket.tasks.application import answers as _answers
from docket.tasks.application import consult as _consult_mod
from docket.tasks.application import corrections as _corrections
from docket.tasks.application import lifecycle as _lifecycle
from docket.tasks.application import queue as _queue
from docket.tasks.application import sweep as _sweep
from docket.teams import fleet as _fleet
from docket.teams import pod_settings as _pod_settings

SUBJECT = "docket.tasks.application.consult"

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


@dataclass(frozen=True)
class _Run:
    project: str
    task_id: str


def _start(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    backend: _Backend,
    mode: Literal["wait", "park", "refuse"] = "park",
    expiry_hours: int | None = None,
    pipeline_yaml: str | None = None,
) -> _Run:
    workspace = tmp_path / "codebase"
    workspace.mkdir()
    build_pod("demo", _pod.pod.DEFAULT_POD_ROLES, codebase=str(workspace))
    _fleet.meta_set("demo-implementer", "codebase", str(workspace))
    _fleet.meta_set("demo-implementer", "verifyCmd", "true")
    _fleet.meta_set(
        "demo-lead", "approvalMode", _pod_settings.PodSettings.coerce("approvalMode", mode)
    )
    _fleet.meta_set(
        "demo-lead", "requireVerify", _pod_settings.PodSettings.coerce("requireVerify", "true")
    )
    if expiry_hours is not None:
        _fleet.meta_set(
            "demo-lead",
            "inputExpiryHours",
            _pod_settings.PodSettings.coerce("inputExpiryHours", str(expiry_hours)),
        )
    if pipeline_yaml is not None:
        digest = hashlib.sha256(pipeline_yaml.encode("utf-8")).hexdigest()
        bound = _pod.pod.bound_pipeline_path("demo")
        bound.parent.mkdir(parents=True, exist_ok=True)
        bound.write_text(pipeline_yaml, encoding="utf-8")
        _fleet.meta_set("demo-lead", "pipeline", digest)
    driver = DocketDriver(backend_factory=lambda model_name: backend)
    monkeypatch.setattr(_dr, "default_driver", lambda: driver)
    queued = _queue.enqueue_task_once("demo", "in-place task", channel="cli")[0]
    _sweep.dispatch_pod("demo", turn_timeout=60, max_tasks=1)
    return _Run("demo", str(queued["id"]))


def _task(run: _Run) -> dict[str, Any]:
    return next(t for t in _queue.read_tasks(run.project) if t["id"] == run.task_id)


def _resume(run: _Run) -> dict[str, Any]:
    _sweep.dispatch_pod(run.project, turn_timeout=60, max_tasks=1)
    return _task(run)


def _answer(run: _Run, action: str, content: dict[str, Any] | None) -> None:
    _answers.answer_task(run.project, run.task_id, action, content, channel="cli", actor="op")


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

        view = _inbox.build_inbox(now=_clock.iso())
        assert [v.id for v in view.needs_you if getattr(v, "pod", "") == run.project] == [
            task["id"]
        ]

    def test_the_parked_question_and_its_options_reach_a_conversation_notification(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        run = _start(tmp_path, monkeypatch, _Backend([_final("plan"), _consult()]))
        view = _inbox.build_inbox(now=_clock.iso())
        (item,) = [v for v in view.needs_you if getattr(v, "pod", "") == run.project]
        data = _notify.render_data(item, "conversation")
        assert data["question"]
        assert [o["id"] for o in data["options"]] == ["redis", "sqlite"]
        assert data["recommendation"] == {"optionId": "sqlite"}
        assert "options" not in _notify.render_data(item, "minimal")

    def test_a_consult_token_with_no_question_fails_the_task_with_a_named_reason(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(_consult_mod, "parked_question", lambda token: None)
        run = _start(tmp_path, monkeypatch, _Backend([_final("plan"), _consult()]))

        task = _task(run)
        assert task["status"] == "failed"
        assert "consult_question_missing" in json.dumps(task)

    def test_refuse_still_fails_the_task_blocked(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        run = _start(tmp_path, monkeypatch, _Backend([_final("plan"), _consult()]), "refuse")

        task = _task(run)
        assert task["status"] != "waiting_input"
        assert "approval_unavailable" in json.dumps(task["hops"])


_ASK_EXPIRES_YAML = """\
name: ask
steps:
  - id: lead
    role: lead
  - id: ask
    input:
      from: lead
      expiresHours: 2
  - id: implementer
    role: implementer
"""


def _hours_from_now(stamp: str) -> float:
    return (dt.datetime.fromisoformat(stamp) - dt.datetime.now(dt.UTC)).total_seconds() / 3600


class TestParkedQuestionExpiry:
    def test_a_parked_consultation_expires_after_the_pods_input_expiry_hours(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        backend = _Backend([_final("plan"), _consult()])
        run = _start(tmp_path, monkeypatch, backend, expiry_hours=1)

        assert _hours_from_now(_task(run)["question"]["expiresAt"]) == pytest.approx(1, abs=0.02)

    def test_an_input_step_keeps_its_own_expires_hours(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        backend = _Backend([_final("plan")])
        run = _start(
            tmp_path, monkeypatch, backend, expiry_hours=1, pipeline_yaml=_ASK_EXPIRES_YAML
        )

        task = _task(run)
        assert task["status"] == "waiting_input"
        assert _hours_from_now(task["question"]["expiresAt"]) == pytest.approx(2, abs=0.02)

    def test_the_sweep_blocks_an_expired_consultation_and_retry_reopens_it(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        run = _start(tmp_path, monkeypatch, _Backend([_final("plan"), _consult()]), expiry_hours=1)
        later = (dt.datetime.now(dt.UTC) + dt.timedelta(hours=2)).isoformat()

        assert _answers.sweep_expired_questions(later) == 1
        task = _task(run)
        assert (task["status"], task["blockedReason"]) == ("blocked", "input_expired")
        assert _lifecycle.retry_task(run.project, run.task_id)
        assert _task(run)["status"] == "pending"


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

    def test_defect_39_consult_answer_is_blocked_by_a_pod_only_policy(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        backend = _Backend([_final("plan"), _consult()])
        run = _start(tmp_path, monkeypatch, backend)
        policies = current_home().pod_config_dir("demo") / "policies"
        policies.mkdir(parents=True)
        (policies / "pod-block-input.yaml").write_text(
            "kind: policy\nname: pod-block-input\nappliesTo: ['*']\non: input\n"
            "when:\n  matches: 'CANARY-PHRASE'\nthen: block\nmessage: canary\n"
        )

        with pytest.raises(_answers.AnswerRejected):
            _answer(run, "accept", {"optionId": "redis", "note": "CANARY-PHRASE"})

        assert _task(run)["status"] == "waiting_input"

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
