"""A conversation task runs turn by turn: each turn is a hop, each reply the next turn's note.

Real pod, real dispatch and the real ``resolve``; only the chat endpoint is a double that records
every request. The oracle is the task a surface reads, its escalations, and what the model was sent.
"""

from __future__ import annotations

import pytest
from tests.support.llm import RecordingScriptedBackend
from tests.support.pods import bind_pipeline, build_pod
from tests.support.tasks import stored_task

from docket.agent.ports import ChatResponse, TokenUsage, assistant
from docket.hops.application import driver as _dr
from docket.hops.application import sweep as _sweep
from docket.hops.application.driver import DocketDriver
from docket.interfaces.cli.commands import pod as _pod
from docket.kernel.operator_contract import Escalation
from docket.platform import list_escalations, read_escalation
from docket.tasks.application import escalations as _esc
from docket.tasks.application import queue as _queue
from docket.tasks.domain.resolution import EscalationNotPending
from docket.tasks.domain.task import TaskRecord

SUBJECT = "docket.hops.application.executor"

PROJECT = "demo"
ONE_STEP = """\
name: talk
steps:
  - chat: lead
"""


def _start(
    monkeypatch: pytest.MonkeyPatch,
    *answers: str,
    usage: TokenUsage = TokenUsage(5, 5),
    conversation: dict[str, int] | None = None,
    max_tokens: int | None = None,
    pipeline: str = ONE_STEP,
) -> tuple[RecordingScriptedBackend, str]:
    """A pod bound to *pipeline*, a task queued on it and a chat double that answers each turn with
    the next of *answers*. Returns the double and the task id."""
    build_pod(PROJECT, _pod.pod.DEFAULT_POD_ROLES, codebase=f"/src/{PROJECT}")
    bind_pipeline(PROJECT, pipeline)
    backend = RecordingScriptedBackend([_answer(text, usage) for text in answers])
    driver = DocketDriver(backend_factory=lambda model: backend)
    monkeypatch.setattr(_dr, "default_driver", lambda: driver)
    options = {"conversation": conversation, "max_tokens": max_tokens}
    task, _ = _queue.enqueue_task_once(
        PROJECT, "talk about caches", channel="http", **{k: v for k, v in options.items() if v}
    )
    return backend, task.id


def _answer(text: str, usage: TokenUsage) -> ChatResponse:
    return ChatResponse(ok=True, message=assistant(text), finish_reason="stop", usage=usage)


def _turn() -> None:
    """One dispatch: the claim runs the next turn of the task."""
    _sweep.dispatch_pod(PROJECT, turn_timeout=60, max_tasks=1)


def _reply(escalation: Escalation, text: str) -> None:
    _esc.resolve(escalation.id, "reply", {"text": text}, by="alice", channel="http")


def _pending(task_id: str) -> Escalation:
    (found,) = [e for e in list_escalations(state="pending") if e.task == task_id]
    return found


def _the(task_id: str) -> TaskRecord:
    return stored_task(PROJECT, task_id)


def _said(call: list, role: str) -> list[str]:
    return [m.content for m in call if m.role == role]


class TestThreeTurns:
    def test_each_turn_parks_on_a_reply_until_the_last_one_ends_the_task(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _, task_id = _start(monkeypatch, "one", "two", "three", conversation={"maxTurns": 3})

        _turn()
        first = _pending(task_id)
        assert (_the(task_id).status, first.kind, first.prompt) == ("waiting_input", "turn", "one")
        assert [o.id for o in first.options] == ["reply", "close"]
        _reply(first, "and the second?")
        assert _the(task_id).status == "pending"

        _turn()
        second = _pending(task_id)
        assert (_the(task_id).status, second.prompt) == ("waiting_input", "two")
        _reply(second, "and the third?")

        _turn()

        task = _the(task_id)
        assert task.status == "done"
        assert list_escalations(state="pending") == []
        assert [e.kind for e in map(read_escalation, task.escalations)] == ["turn", "turn"]
        assert [(h.ok, h.parked, h.output) for h in task.hops] == [
            (True, True, "one"),
            (True, True, "two"),
            (True, False, "three"),
        ]
        assert all(h.usage for h in task.hops)
        assert task.conversation is not None and task.conversation.max_turns == 3

    def test_each_request_carries_the_turns_before_it_and_the_reply_as_its_note(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        backend, task_id = _start(monkeypatch, "one", "two", "three", conversation={"maxTurns": 3})
        _turn()
        _reply(_pending(task_id), "and the second?")
        _turn()
        _reply(_pending(task_id), "and the third?")
        _turn()

        first, second, third = backend.calls
        assert _said(first, "assistant") == []
        assert _said(second, "assistant") == ["one"]
        assert _said(third, "assistant") == ["one", "two"]
        assert len(_said(second, "user")) == 2 and len(_said(third, "user")) == 3
        assert "and the second?" in _said(second, "user")[-1]
        assert "and the third?" in _said(third, "user")[-1]
        assert "and the second?" not in _said(third, "user")[-1]

    def test_a_reply_after_the_task_moved_on_is_refused(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _, task_id = _start(monkeypatch, "one", "two", conversation={"maxTurns": 2})
        _turn()
        first = _pending(task_id)
        _reply(first, "go on")
        _turn()
        assert _the(task_id).status == "done"

        with pytest.raises(EscalationNotPending) as refused:
            _reply(first, "one more")

        assert refused.value.code == "escalation_not_pending"
        assert _the(task_id).status == "done"


class TestTheTokenLimit:
    @pytest.mark.parametrize(
        "spent", [TokenUsage(4000, 2100), TokenUsage(4000, 900)], ids=["spent", "too little left"]
    )
    def test_a_task_whose_tokens_ran_out_after_a_turn_is_done_not_failed(
        self, monkeypatch: pytest.MonkeyPatch, spent: TokenUsage
    ) -> None:
        _, task_id = _start(
            monkeypatch, "one", "two", usage=spent, conversation={"maxTurns": 3}, max_tokens=6000
        )
        _turn()
        _reply(_pending(task_id), "go on")

        _turn()

        task = _the(task_id)
        assert (task.status, task.failure_kind) == ("done", None)
        assert task.hops[0].output == "one" and task.hops[0].ok

    def test_a_task_that_never_answered_still_fails_on_budget(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _, task_id = _start(monkeypatch, "one", conversation={"maxTurns": 3}, max_tokens=10)

        _turn()

        task = _the(task_id)
        assert (task.status, task.failure_kind) == ("failed", "budget")


class TestAnOrdinaryTask:
    def test_an_ok_hop_of_a_task_without_conversation_advances(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _, task_id = _start(monkeypatch, "one")

        _turn()

        task = _the(task_id)
        assert (task.status, [h.parked for h in task.hops]) == ("done", [False])
        assert list_escalations(state="pending") == []
