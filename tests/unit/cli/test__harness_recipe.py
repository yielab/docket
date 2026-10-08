"""`docket exec --recipe` -- argument refusals, answer routing and status mapping.

Pure-logic coverage of the recipe runner's helpers. The process-boundary behaviour (a recipe
run end to end over a real pipe) is covered in ``tests/integration/test_harness_cli.py``.
"""

from __future__ import annotations

import queue
from typing import Any

import pytest

from docket.cli import _harness_recipe
from docket.cli._exec import ExecOptions
from docket.core import harness

SUBJECT = "docket.cli._harness_recipe"


def _answer_line(question_id: str) -> harness.AnswerLine:
    return harness.AnswerLine(
        v="1.1.0",
        token="run-x",
        answer=harness.Answer(questionId=question_id, action="accept", content={"q1": "y"}),
    )


class TestUsageError:
    def test_no_recipe_and_no_verify_is_fine(self) -> None:
        assert _harness_recipe.usage_error(ExecOptions()) is None

    def test_verify_without_recipe_is_refused(self) -> None:
        problem = _harness_recipe.usage_error(ExecOptions(verify="true", contract="1.1"))
        assert problem == "--verify needs --recipe"

    def test_recipe_needs_contract_1_1(self) -> None:
        problem = _harness_recipe.usage_error(ExecOptions(recipe="tdd"))
        assert problem == "--recipe needs --contract 1.1"

    @pytest.mark.parametrize(
        ("extra", "fragment"),
        [
            ({"role": "reviewer"}, "--role"),
            ({"max_tokens": "10"}, "--max-tokens"),
            ({"agent_id": "x"}, "--agent-id"),
        ],
    )
    def test_flags_that_a_recipe_run_cannot_honour_are_refused(
        self, extra: dict[str, str], fragment: str
    ) -> None:
        problem = _harness_recipe.usage_error(ExecOptions(recipe="tdd", contract="1.1", **extra))
        assert problem is not None
        assert fragment in problem

    def test_an_unknown_recipe_is_refused_with_its_name(self) -> None:
        problem = _harness_recipe.usage_error(
            ExecOptions(recipe="no-such-recipe-x", contract="1.1")
        )
        assert problem is not None
        assert "no-such-recipe-x" in problem

    def test_a_shipped_recipe_is_accepted(self) -> None:
        assert _harness_recipe.usage_error(ExecOptions(recipe="tdd", contract="1.1")) is None


class TestAnswerSource:
    def test_returns_the_answer_for_the_open_question(self) -> None:
        questions: queue.Queue[harness.AnswerLine | None] = queue.Queue()
        questions.put(_answer_line("q-1"))

        answer = _harness_recipe._answer_source(questions, timeout=1)({"id": "q-1"})

        assert answer is not None
        assert answer.questionId == "q-1"

    def test_skips_a_line_for_another_question(self, capsys: pytest.CaptureFixture[str]) -> None:
        questions: queue.Queue[harness.AnswerLine | None] = queue.Queue()
        questions.put(_answer_line("q-old"))
        questions.put(_answer_line("q-new"))

        answer = _harness_recipe._answer_source(questions, timeout=1)({"id": "q-new"})

        assert answer is not None
        assert answer.questionId == "q-new"
        assert "not the open question" in capsys.readouterr().err

    def test_end_of_stdin_returns_none(self) -> None:
        questions: queue.Queue[harness.AnswerLine | None] = queue.Queue()
        questions.put(None)

        assert _harness_recipe._answer_source(questions, timeout=None)({"id": "q-1"}) is None

    def test_a_timeout_with_no_answer_returns_none(self) -> None:
        questions: queue.Queue[harness.AnswerLine | None] = queue.Queue()

        assert _harness_recipe._answer_source(questions, timeout=0)({"id": "q-1"}) is None


class TestTaskStatus:
    def test_done_is_ok(self) -> None:
        assert _harness_recipe._task_status({"status": "done"}, [], "") == ("ok", None, "")

    def test_failed_keeps_the_reason(self) -> None:
        status, blocked, reason = _harness_recipe._task_status(
            {"status": "failed", "reason": "verify failed"}, [], ""
        )
        assert (status, blocked, reason) == ("failed", None, "verify failed")

    def test_a_refused_approval_in_a_hop_is_blocked_with_its_rule(self) -> None:
        hop: dict[str, Any] = {
            "error": "approval_unavailable: tool='bash' call_id='c-1' policy_id='pol-7' reason='x'"
        }
        status, blocked, _reason = _harness_recipe._task_status({"status": "failed"}, [hop], "")
        assert status == "blocked"
        assert blocked is not None
        assert blocked.tool == "bash"
        assert blocked.policy_id == "pol-7"

    @pytest.mark.parametrize("state", ["waiting_input", "waiting_approval", "blocked"])
    def test_a_parked_task_is_blocked(self, state: str) -> None:
        status, blocked, _reason = _harness_recipe._task_status({"status": state}, [], "")
        assert status == "blocked"
        assert blocked is None

    def test_cancelled_maps_to_cancelled(self) -> None:
        assert _harness_recipe._task_status({"status": "cancelled"}, [], "")[0] == "cancelled"

    def test_a_run_with_no_task_record_is_failed_with_its_error(self) -> None:
        assert _harness_recipe._task_status({}, [], "RuntimeError: boom") == (
            "failed",
            None,
            "RuntimeError: boom",
        )


class TestHopView:
    def test_projects_the_result_fields_out_of_a_hop_record(self) -> None:
        hop: dict[str, Any] = {
            "role": "reviewer",
            "stepId": "review",
            "ok": True,
            "artifact": {"verdict": "approve"},
            "verify": None,
            "evidence": None,
            "output": "ignored",
        }
        assert _harness_recipe._hop_view(hop) == {
            "role": "reviewer",
            "stepId": "review",
            "ok": True,
            "verdict": "approve",
            "verify": None,
            "evidence": None,
        }

    def test_a_hop_without_an_artifact_has_no_verdict(self) -> None:
        assert _harness_recipe._hop_view({"role": "lead", "artifact": None})["verdict"] is None
