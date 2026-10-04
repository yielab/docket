"""`docket harness run --answers stdin` -- the one-line-at-a-time answer reader.

Pure-logic coverage: each fail-closed branch of ``handle_line`` against a real
approval record in an isolated home. The process-boundary behaviour (a paused
run resolved over a real pipe) is covered in
``tests/integration/test_harness_cli.py``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.conftest import repoint_docket_home

from docket.cli import _harness_answers
from docket.core import approval

SUBJECT = "docket.cli._harness_answers"

RUN = "run-abc"


@pytest.fixture()
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "home"
    repoint_docket_home(monkeypatch, path)
    return path


def _pending(home: Path) -> str:
    return approval.approval_create("pod", "implementer", "tool call 'bash'", context={})


def _state(token: str) -> str:
    return str(approval.approval_get(token)["state"])


def _line(answer: dict[str, object], token: str = RUN) -> str:
    return json.dumps({"v": "1.1.0", "token": token, "answer": answer})


class TestHandleLine:
    def test_an_accept_grants_the_pending_approval(
        self, home: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        token = _pending(home)

        _harness_answers.handle_line(_line({"approvalToken": token, "action": "accept"}), RUN)

        assert _state(token) == "granted"
        assert capsys.readouterr().err == ""

    def test_a_decline_denies_and_a_cancel_denies(self, home: Path) -> None:
        declined = _pending(home)
        cancelled = _pending(home)

        _harness_answers.handle_line(_line({"approvalToken": declined, "action": "decline"}), RUN)
        _harness_answers.handle_line(_line({"approvalToken": cancelled, "action": "cancel"}), RUN)

        assert _state(declined) == "denied"
        assert _state(cancelled) == "denied"

    def test_a_malformed_line_is_ignored_with_one_stderr_line_and_no_echo(
        self, home: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        token = _pending(home)

        _harness_answers.handle_line("not json MALFORMED-MARKER-7f3a", RUN)

        err = capsys.readouterr().err
        assert err.count("answer line ignored") == 1
        assert "MALFORMED-MARKER-7f3a" not in err
        assert _state(token) == "pending"

    def test_a_line_for_another_run_is_ignored(
        self, home: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        token = _pending(home)

        _harness_answers.handle_line(
            _line({"approvalToken": token, "action": "accept"}, token="run-other"), RUN
        )

        assert "does not match" in capsys.readouterr().err
        assert _state(token) == "pending"

    def test_a_token_that_is_not_an_approval_id_never_touches_the_disk(
        self, home: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        outside = home / "elsewhere.json"
        home.mkdir(parents=True, exist_ok=True)
        outside.write_text(json.dumps({"state": "pending"}), encoding="utf-8")

        _harness_answers.handle_line(
            _line({"approvalToken": "../elsewhere", "action": "accept"}), RUN
        )

        assert "unknown approval" in capsys.readouterr().err
        assert json.loads(outside.read_text(encoding="utf-8")) == {"state": "pending"}

    def test_a_second_answer_for_a_resolved_approval_is_reported_not_applied(
        self, home: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        token = _pending(home)
        _harness_answers.handle_line(_line({"approvalToken": token, "action": "accept"}), RUN)

        _harness_answers.handle_line(_line({"approvalToken": token, "action": "decline"}), RUN)

        assert "already resolved" in capsys.readouterr().err
        assert _state(token) == "granted"

    def test_content_that_a_pre_input_policy_blocks_leaves_the_approval_pending(
        self, home: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        token = _pending(home)
        monkeypatch.setattr(
            _harness_answers,
            "policy_eval_detail",
            lambda *args, **kwargs: _Hit(action="block", policy_id="p-block"),
        )

        _harness_answers.handle_line(
            _line({"approvalToken": token, "action": "accept", "content": {"a": "b"}}), RUN
        )

        assert "p-block" in capsys.readouterr().err
        assert _state(token) == "pending"

    def test_a_question_answer_is_refused_until_recipe_runs_exist(
        self, home: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _harness_answers.handle_line(_line({"questionId": "q-1", "action": "accept"}), RUN)

        assert "need --recipe" in capsys.readouterr().err


class _Hit:
    def __init__(self, action: str, policy_id: str) -> None:
        self.action = action
        self.policy_id = policy_id


class TestWaitBudget:
    def test_none_leaves_the_configured_wait_alone(self) -> None:
        import docket.config as cfg

        before = cfg.TOOL_APPROVAL_TIMEOUT
        with _harness_answers.wait_budget(None):
            assert before == cfg.TOOL_APPROVAL_TIMEOUT
        assert before == cfg.TOOL_APPROVAL_TIMEOUT

    def test_a_value_applies_inside_the_block_and_is_restored_after(self) -> None:
        import docket.config as cfg

        before = cfg.TOOL_APPROVAL_TIMEOUT
        with _harness_answers.wait_budget(7):
            inside = cfg.TOOL_APPROVAL_TIMEOUT
            assert inside == 7
        assert before == cfg.TOOL_APPROVAL_TIMEOUT


class TestOptionIds:
    @staticmethod
    def _answer(token: str, action: str, content: dict[str, str] | None) -> str:
        answer: dict[str, object] = {"approvalToken": token, "action": action}
        if content is not None:
            answer["content"] = content
        return _line(answer)

    def test_approve_task_records_the_option_and_grants(self, home: Path) -> None:
        t = approval.approval_create("p", "r", "act", rationale="")
        _harness_answers.handle_line(self._answer(t, "accept", {"optionId": "approve_task"}), RUN)
        rec = approval.approval_get(t)
        assert rec["state"] == "granted" and rec["context"]["optionId"] == "approve_task"

    def test_approve_once_and_bare_accept_grant_without_an_option_record(self, home: Path) -> None:
        a = approval.approval_create("p", "r", "act", rationale="")
        b = approval.approval_create("p", "r", "act", rationale="")
        _harness_answers.handle_line(self._answer(a, "accept", {"optionId": "approve_once"}), RUN)
        _harness_answers.handle_line(self._answer(b, "accept", None), RUN)
        for t in (a, b):
            rec = approval.approval_get(t)
            assert rec["state"] == "granted" and "optionId" not in rec["context"]

    def test_deny_option_declines_with_the_reason(self, home: Path) -> None:
        t = approval.approval_create("p", "r", "act", rationale="")
        content = {"optionId": "deny", "reason": "no"}
        _harness_answers.handle_line(self._answer(t, "decline", content), RUN)
        assert _state(t) == "denied"

    def test_unknown_option_is_ignored_and_stays_pending(
        self, home: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        t = approval.approval_create("p", "r", "act", rationale="")
        _harness_answers.handle_line(self._answer(t, "accept", {"optionId": "bogus"}), RUN)
        assert _state(t) == "pending"
        assert "unknown option" in capsys.readouterr().err

    def test_option_that_contradicts_the_action_is_ignored(self, home: Path) -> None:
        t = approval.approval_create("p", "r", "act", rationale="")
        _harness_answers.handle_line(self._answer(t, "decline", {"optionId": "approve_once"}), RUN)
        assert _state(t) == "pending"
