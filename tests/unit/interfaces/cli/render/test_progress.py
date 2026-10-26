"""`docket.interfaces.cli.render.progress` -- rendering, answer parsing and the thread
orchestration behind `docket run`'s foreground progress view.
Behind a real TTY on a real dispatch, see `tests/unit/cli/test_pod.py`.
"""

from __future__ import annotations

import dataclasses
import io
import json
import queue
from pathlib import Path
from typing import Any

import pytest
from tests.support.home import home as _home
from tests.support.tasks import put_task, task

from docket.governance import approval as _ap
from docket.interfaces.cli.render import progress as _progress
from docket.kernel import clock as _clock
from docket.kernel import escalation_events as _events
from docket.kernel.home import current_home, use_home
from docket.kernel.operator_contract import (
    Escalation,
    Option,
    Question,
    QuestionV11,
    Recommendation,
    new_question_id,
)
from docket.operator import escalation_view
from docket.platform import read_escalation
from docket.tasks.application import escalations as _escalations

SUBJECT = "docket.interfaces.cli.render.progress"


_TASK_ID = "task-04ff1a2b-3c4d-4e5f-8a9b-0c1d2e3f4a5b"
_TASK_SESSION = f"agent:demo:{_TASK_ID}"
_TASK_SHORT = "task-04ff1a2b-3c4d"


def _record(
    event_type: str,
    payload: dict[str, Any],
    *,
    role: str = "implementer",
    session_id: str = "s1",
) -> dict[str, Any]:
    return {
        "ts": "2026-09-28T00:00:00Z",
        "session_id": session_id,
        "agent_role": role,
        "event_type": event_type,
        "payload": payload,
    }


# ── should_render / should_prompt ────────────────────────────────────────────


class TestShouldRender:
    def test_progress_flag_forces_rendering_without_a_tty(self) -> None:
        assert _progress.should_render(progress_flag=True, stderr_isatty=lambda: False) is True

    def test_a_real_tty_renders_without_the_flag(self) -> None:
        assert _progress.should_render(progress_flag=False, stderr_isatty=lambda: True) is True

    def test_neither_renders(self) -> None:
        assert _progress.should_render(progress_flag=False, stderr_isatty=lambda: False) is False


class TestShouldPrompt:
    def test_prompts_on_a_rendering_tty_stdin(self) -> None:
        assert (
            _progress.should_prompt(no_prompt_flag=False, render=True, stdin_isatty=lambda: True)
            is True
        )

    def test_no_prompt_flag_disables_it(self) -> None:
        assert (
            _progress.should_prompt(no_prompt_flag=True, render=True, stdin_isatty=lambda: True)
            is False
        )

    def test_no_rendering_means_no_prompt_even_on_a_tty_stdin(self) -> None:
        assert (
            _progress.should_prompt(no_prompt_flag=False, render=False, stdin_isatty=lambda: True)
            is False
        )

    def test_a_tty_stderr_never_implies_a_tty_stdin(self) -> None:
        assert (
            _progress.should_prompt(no_prompt_flag=False, render=True, stdin_isatty=lambda: False)
            is False
        )


# ── render_event ──────────────────────────────────────────────────────────────


class TestRenderEvent:
    def test_session_start_names_the_task_short_id(self) -> None:
        record = _record("session_start", {}, role="lead", session_id=_TASK_SESSION)
        assert _progress.render_event(record) == f"▶ {_TASK_SHORT} …"

    def test_session_end_names_the_task_and_carries_the_status(self) -> None:
        record = _record("session_end", {"status": "done"}, role="lead", session_id=_TASK_SESSION)
        assert _progress.render_event(record) == f"■ {_TASK_SHORT} finished — status=done"

    def test_a_session_naming_no_task_falls_back_to_the_role(self) -> None:
        assert _progress.render_event(_record("session_start", {}, role="lead")) == "▶ lead …"

    def test_the_hop_marker_names_the_hop_indented(self) -> None:
        payload = {"hop": "implementer", "agent": "demo-implementer"}
        record = _record("tool_call", payload, role="implementer", session_id=_TASK_SESSION)
        assert _progress.render_event(record) == "  ▶ implementer …"

    @pytest.mark.parametrize(
        "payload",
        [
            {"name": "bash", "callId": "c1"},
            {"hop": "implementer"},
            {"hop": "implementer", "agent": "demo-implementer", "name": "bash"},
        ],
    )
    def test_any_other_tool_call_returns_none(self, payload: dict[str, Any]) -> None:
        assert _progress.render_event(_record("tool_call", payload)) is None

    def test_an_asked_approval_names_the_escalation_and_the_command_that_answers_it(self) -> None:
        record = _record(
            "escalation_asked",
            {"escalation": "esc-1", "kind": "gate", "prompt": "hop lead needs approval"},
            role="lead",
        )
        assert _progress.render_event(record) == (
            "⏸ lead needs approval: hop lead needs approval · esc-1 · "
            "docket task answer esc-1 --option approve_once"
        )

    def test_an_asked_approval_counts_down_to_its_deadline(self) -> None:
        record = _record(
            "escalation_asked",
            {
                "escalation": "esc-2",
                "kind": "approval",
                "prompt": "bash('rm -rf x')",
                "expiresAt": "2026-09-28T00:02:00Z",
            },
        )
        now = _clock.parse_epoch(record["ts"]) + 20  # 20s have elapsed since the event
        line = _progress.render_event(record, now=now)
        assert line == (
            "⏸ implementer wants: bash('rm -rf x') · esc-2 · denies in 100s · "
            "docket task answer esc-2 --option approve_once"
        )

    def test_a_question_is_not_rendered_here_and_the_retired_events_are_not_at_all(self) -> None:
        asked = {"escalation": "esc-3", "kind": "consult", "prompt": "Which store?"}
        assert _progress.render_event(_record("escalation_asked", asked)) is None
        for retired in ("approval_required", "approval_requested", "question_asked"):
            assert _progress.render_event(_record(retired, {"token": "t", "action": "x"})) is None

    def test_an_unrenderable_event_type_returns_none(self) -> None:
        assert _progress.render_event(_record("llm_call", {})) is None


# ── parse_answer ──────────────────────────────────────────────────────────────


class TestParseAnswer:
    @pytest.mark.parametrize(
        "line,expected",
        [("a\n", "a"), ("A\n", "a"), ("d\n", "d"), ("D\n", "d"), ("  a  \n", "a")],
    )
    def test_recognised_answers(self, line: str, expected: str) -> None:
        assert _progress.parse_answer(line) == expected

    @pytest.mark.parametrize("line", ["\n", "", "x\n", "approve\n", "0\n", "-1\n", "1.5\n"])
    def test_anything_else_keeps_waiting(self, line: str) -> None:
        assert _progress.parse_answer(line) == ""

    @pytest.mark.parametrize(("line", "expected"), [("1\n", "1"), (" 12 \n", "12")])
    def test_an_option_number_is_kept_for_a_question(self, line: str, expected: str) -> None:
        assert _progress.parse_answer(line) == expected


# ── handle_approval_prompt ────────────────────────────────────────────────────


def _open_approval(action: str = "bash: git push origin main") -> tuple[str, str]:
    """The approval record of a call in a turn and the escalation opened on it."""
    token = _ap.approval_create("demo", "implementer", action)
    opened = _escalations.open_for_approval(
        token, kind="approval", task_id="in-turn", caused_by="c1"
    )
    return token, opened.id


class TestHandleApprovalPrompt:
    def test_a_grant_settles_the_record_and_the_approval_it_backs(self, tmp_path: Path) -> None:
        with _home(tmp_path):
            token, record_id = _open_approval()

            outcome = _progress.handle_approval_prompt(record_id, "a")

            stored = read_escalation(record_id)
            assert outcome.action == "granted"
            assert stored is not None and stored.state == "resolved"
            assert stored.resolution is not None
            assert (stored.resolution.option_id, stored.resolution.channel) == (
                "approve_once",
                "cli",
            )
            assert _ap.approval_get(token)["state"] == "granted"

    def test_a_denial_settles_the_record_and_the_approval_with_deny(self, tmp_path: Path) -> None:
        with _home(tmp_path):
            token, record_id = _open_approval()

            outcome = _progress.handle_approval_prompt(record_id, "d")

            stored = read_escalation(record_id)
            assert outcome.action == "denied"
            assert stored is not None and stored.resolution is not None
            assert stored.resolution.option_id == "deny"
            assert _ap.approval_get(token)["state"] == "denied"

    def test_an_empty_answer_keeps_waiting_and_touches_nothing(self, tmp_path: Path) -> None:
        with _home(tmp_path):
            token, record_id = _open_approval()

            outcome = _progress.handle_approval_prompt(record_id, "")

            stored = read_escalation(record_id)
            assert outcome.action == "waiting"
            assert stored is not None and stored.state == "pending"
            assert _ap.approval_get(token)["state"] == "pending"

    def test_an_escalation_already_resolved_elsewhere_is_reported_not_raised(
        self, tmp_path: Path
    ) -> None:
        with _home(tmp_path):
            _, record_id = _open_approval()
            _escalations.resolve(record_id, "approve_once", None, by="", channel="mcp")

            outcome = _progress.handle_approval_prompt(record_id, "a")

            assert outcome.action == "noop"
            assert outcome.message == "  (already resolved elsewhere)"

    @pytest.mark.parametrize(("first", "second"), [("d", "a"), ("a", "d")])
    def test_the_opposite_decision_having_won_is_reported_not_raised(
        self, tmp_path: Path, first: str, second: str
    ) -> None:
        with _home(tmp_path):
            token, record_id = _open_approval()
            _progress.handle_approval_prompt(record_id, first)
            state = _ap.approval_get(token)["state"]

            outcome = _progress.handle_approval_prompt(record_id, second)

            assert outcome.action == "noop"
            assert record_id in (outcome.message or "")
            assert _ap.approval_get(token)["state"] == state

    def test_an_escalation_with_no_record_is_reported_not_raised(self, tmp_path: Path) -> None:
        with _home(tmp_path):
            outcome = _progress.handle_approval_prompt("no-such-escalation", "a")

            assert outcome.action == "noop"
            assert outcome.message


# ── stdin_reader_loop ─────────────────────────────────────────────────────────


class TestStdinReaderLoop:
    def test_reads_every_recognised_line_until_eof(self) -> None:
        answers: queue.Queue[str] = queue.Queue()
        _progress.stdin_reader_loop(io.StringIO("a\n\nd\nbogus\n2\n"), answers)

        assert list(answers.queue) == ["a", "d", "2"]

    def test_an_immediate_eof_reads_nothing(self) -> None:
        answers: queue.Queue[str] = queue.Queue()
        _progress.stdin_reader_loop(io.StringIO(""), answers)

        assert answers.empty()


# ── dispatch_with_progress ────────────────────────────────────────────────────


class TestDispatchWithProgress:
    def test_renders_events_and_grants_through_the_prompt(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No real dispatch_pod/DocketDriver here -- this proves the thread wiring
        (render loop + stdin-answer loop + the trace subscription) alone, with a
        fake `_runs.execute` standing in for a hop that blocks on a real approval."""
        with _home(tmp_path):
            from docket.observability import trace as _trace

            with use_home(dataclasses.replace(current_home(), tool_approval_poll_interval_s=0.02)):
                opened: dict[str, str] = {}

                def fake_execute(run_id: str, fn: Any) -> list[Any]:
                    _trace.trace_event(
                        "demo", _TASK_SESSION, "lead", "session_start", json.dumps({})
                    )
                    hop = json.dumps({"hop": "implementer", "agent": "demo-implementer"})
                    _trace.trace_event("demo", _TASK_SESSION, "implementer", "tool_call", hop)
                    token = _ap.approval_create("demo", "implementer", "bash: git push origin main")
                    opened["token"] = token
                    opened["id"] = _escalations.open_for_approval(
                        token, kind="approval", task_id=_TASK_ID, caused_by="c1"
                    ).id
                    _ap.wait_for_approval(token, timeout=1.5, poll_interval=0.02)
                    end = json.dumps({"status": "done"})
                    _trace.trace_event("demo", _TASK_SESSION, "lead", "session_end", end)
                    return []

                monkeypatch.setattr(_progress._runs, "execute", fake_execute)
                lines: list[str] = []

                result = _progress.dispatch_with_progress(
                    "run-1", lambda: [], prompt=True, stdin=io.StringIO("a\n"), println=lines.append
                )

                assert result == []
                assert _ap.approval_get(opened["token"])["state"] == "granted"
                stored = read_escalation(opened["id"])
                assert stored is not None and stored.resolution is not None
                assert stored.resolution.option_id == "approve_once"
                task_line = lines.index(f"▶ {_TASK_SHORT} …")
                hop_line = lines.index("  ▶ implementer …")
                approval_line = next(
                    i for i, line in enumerate(lines) if "wants: bash: git push origin main" in line
                )
                assert task_line < hop_line < approval_line
                assert lines[-1] == f"■ {_TASK_SHORT} finished — status=done"

    def test_without_prompt_it_only_renders(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        with _home(tmp_path):
            from docket.observability import trace as _trace

            def fake_execute(run_id: str, fn: Any) -> list[Any]:
                _trace.trace_event("demo", "s1", "lead", "session_start", json.dumps({}))
                _trace.trace_event(
                    "demo", "s1", "lead", "session_end", json.dumps({"status": "done"})
                )
                return []

            monkeypatch.setattr(_progress._runs, "execute", fake_execute)
            lines: list[str] = []

            result = _progress.dispatch_with_progress(
                "run-2", lambda: [], prompt=False, stdin=io.StringIO(""), println=lines.append
            )

            assert result == []
            assert lines == ["▶ lead …", "■ lead finished — status=done"]


def _consult_question(task_id: str = _TASK_ID) -> QuestionV11:
    return QuestionV11(
        id=new_question_id(),
        task_id=task_id,
        pod="demo",
        step="implementer",
        message="Which store should the cache use?",
        requested_schema={"type": "object", "properties": {"note": {"type": "string"}}},
        created_at="2026-10-25T00:00:00+00:00",
        kind="decision",
        options=[
            Option(id="redis", label="Redis", description="fast"),
            Option(id="sqlite", label="SQLite", description="simple"),
        ],
        recommendation=Recommendation(option_id="sqlite", rationale="fewer services"),
    )


class TestParkedQuestion:
    def _run(self, monkeypatch: pytest.MonkeyPatch, execute: Any) -> list[str]:
        monkeypatch.setattr(_progress._runs, "execute", execute)
        lines: list[str] = []
        _progress.dispatch_with_progress(
            "run-q", lambda: [], prompt=False, stdin=io.StringIO(""), println=lines.append
        )
        return lines

    def test_the_question_is_a_line_with_its_options_and_the_command_that_answers_it(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        with _home(tmp_path):
            from docket.observability import trace as _trace

            def fake_execute(run_id: str, fn: Any) -> list[Any]:
                _trace.trace_event("demo", _TASK_SESSION, "lead", "session_start", json.dumps({}))
                question = _consult_question()
                put_task("demo", task(id=_TASK_ID, status="waiting_input"))
                _escalations.open_for_question(
                    question, kind="consult", role="implementer", caused_by="c1"
                )
                end = json.dumps({"status": "waiting_input"})
                _trace.trace_event("demo", _TASK_SESSION, "lead", "session_end", end)
                return []

            lines = self._run(monkeypatch, fake_execute)

            (asked,) = [line for line in lines if line.startswith("⏸")]
            assert asked == (
                "⏸ implementer asks: consultation: Which store should the cache use? · "
                f"options redis, sqlite (recommended sqlite) · docket task answer {_TASK_ID} "
                "--option sqlite"
            )

    def test_an_input_step_prints_the_same_line_without_an_option(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        with _home(tmp_path):

            def fake_execute(run_id: str, fn: Any) -> list[Any]:
                question = Question(
                    id=new_question_id(),
                    task_id=_TASK_ID,
                    pod="demo",
                    step="ask",
                    message="Name the branch.",
                    requested_schema={"type": "object", "properties": {"note": {"type": "string"}}},
                    created_at="2026-10-25T00:00:00+00:00",
                )
                put_task("demo", task(id=_TASK_ID, status="waiting_input"))
                _escalations.open_for_question(question, kind="input", role="", caused_by="ask")
                return []

            lines = self._run(monkeypatch, fake_execute)

            (asked,) = [line for line in lines if line.startswith("⏸")]
            assert asked == (
                f"⏸ ask asks: input requested: Name the branch. · docket task answer {_TASK_ID}"
            )

    def test_a_question_parked_before_the_run_is_not_announced_again(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        with _home(tmp_path):
            from docket.observability import trace as _trace

            old = _consult_question("task-old")
            put_task("demo", task(id="task-old", status="waiting_input"))
            _escalations.open_for_question(old, kind="consult", role="implementer", caused_by="c1")

            def fake_execute(run_id: str, fn: Any) -> list[Any]:
                _trace.trace_event("demo", _TASK_SESSION, "lead", "session_start", json.dumps({}))
                return []

            assert [line for line in self._run(monkeypatch, fake_execute) if "asks" in line] == []

    def test_a_consult_the_pod_decided_alone_prints_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        with _home(tmp_path):

            def fake_execute(run_id: str, fn: Any) -> list[Any]:
                _escalations.decided_consult(
                    _consult_question(), role="implementer", option_id="sqlite"
                )
                return []

            assert [line for line in self._run(monkeypatch, fake_execute) if "asks" in line] == []


def _waiting_consult(token_options: list[Option] | None = None) -> tuple[str, str, QuestionV11]:
    """The approval record and the escalation a consult waiting in the turn opens, as it does."""
    question = _consult_question()
    token = _ap.approval_create(
        "demo",
        "implementer",
        question.message,
        context={
            "kind": "consult",
            "questionId": question.id,
            "options": [{"id": o.id, "label": o.label} for o in question.options],
        },
    )
    opened = _escalations.open_for_question(
        question, kind="consult", role="implementer", caused_by="implementer", token=token
    )
    return token, opened.id, question


class TestConsultPrompt:
    def test_a_consult_waiting_in_the_turn_lists_its_options(self, tmp_path: Path) -> None:
        with _home(tmp_path):
            _, record_id, _ = _waiting_consult()
            stored = read_escalation(record_id)
            assert stored is not None

            lines = _progress.consult_lines(escalation_view(stored))

            assert lines == [
                "⏸ implementer asks: Which store should the cache use? · options redis, sqlite",
                "  [1] redis (Redis)  [2] sqlite (SQLite)  [d]ecline  [Enter] keep waiting",
            ]

    def test_only_an_approval_event_renders_as_an_approval(self, tmp_path: Path) -> None:
        with _home(tmp_path):
            _, consult_id, _ = _waiting_consult()
            _, approval_id = _open_approval()
            consult = read_escalation(consult_id)
            approval = read_escalation(approval_id)
            assert consult is not None and approval is not None

            def asked(escalation: Escalation) -> dict[str, Any]:
                return _record("escalation_asked", _events.payload(_events.ASKED, escalation))

            assert _progress.render_event(asked(consult)) is None
            line = _progress.render_event(asked(approval))
            assert line is not None and f"docket task answer {approval_id} --option" in line

    @pytest.mark.parametrize(
        ("answer", "option"), [("1", "redis"), ("2", "sqlite"), ("d", "decline")]
    )
    def test_a_number_picks_the_option_and_d_declines_through_resolve(
        self, tmp_path: Path, answer: str, option: str
    ) -> None:
        with _home(tmp_path):
            token, record_id, _ = _waiting_consult()

            outcome = _progress.handle_question_prompt(record_id, ["redis", "sqlite"], answer)

            stored = read_escalation(record_id)
            assert outcome.action == ("denied" if option == "decline" else "granted")
            assert stored is not None and stored.state == "resolved"
            assert stored.resolution is not None and stored.resolution.option_id == option
            assert _ap.approval_get(token)["state"] == (
                "denied" if option == "decline" else "granted"
            )

    def test_a_number_out_of_range_keeps_waiting_and_says_why(self, tmp_path: Path) -> None:
        with _home(tmp_path):
            _, record_id, _ = _waiting_consult()

            outcome = _progress.handle_question_prompt(record_id, ["redis", "sqlite"], "3")

            assert outcome.action == "waiting" and "1-2" in (outcome.message or "")
            stored = read_escalation(record_id)
            assert stored is not None and stored.state == "pending"

    def test_an_answer_that_lost_the_race_is_reported_not_raised(self, tmp_path: Path) -> None:
        with _home(tmp_path):
            _, record_id, _ = _waiting_consult()
            _progress.handle_question_prompt(record_id, ["redis", "sqlite"], "1")

            outcome = _progress.handle_question_prompt(record_id, ["redis", "sqlite"], "2")

            assert outcome.action == "noop" and outcome.message

    def test_the_loop_prints_the_choices_and_answers_the_waiting_consult(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A real `consult` blocks on its approval record; the prompt thread answers `2`."""
        with _home(tmp_path):
            from docket.agent.tools.registry import ToolContext
            from docket.tasks.application import consult as _consult

            with use_home(
                dataclasses.replace(
                    current_home(), tool_approval_poll_interval_s=0.02, tool_approval_timeout=10
                )
            ):
                outcome: dict[str, str] = {}

                def fake_execute(run_id: str, fn: Any) -> list[Any]:
                    ctx = ToolContext(
                        agent_id="demo-implementer",
                        session_key=_TASK_SESSION,
                        project="demo",
                        role="implementer",
                        approval_mode="wait",
                        consult_park=True,
                        task_id=_TASK_ID,
                    )
                    args = {
                        "kind": "decision",
                        "message": "Which store should the cache use?",
                        "options": [
                            {"id": "redis", "label": "Redis", "description": "fast"},
                            {"id": "sqlite", "label": "SQLite", "description": "simple"},
                        ],
                        "recommendation": {"optionId": "sqlite", "rationale": "no new service"},
                    }
                    outcome["content"] = _consult.run(args, ctx).content
                    return []

                monkeypatch.setattr(_progress._runs, "execute", fake_execute)
                lines: list[str] = []

                _progress.dispatch_with_progress(
                    "run-c", lambda: [], prompt=True, stdin=io.StringIO("2\n"), println=lines.append
                )

                assert (
                    "[1] redis (Redis)  [2] sqlite (SQLite)  [d]ecline  [Enter] keep waiting"
                    in "\n".join(f"  {line.strip()}" for line in lines)
                )
                assert not any("[a]pprove" in line for line in lines)
                assert "option sqlite (SQLite)" in outcome["content"]
