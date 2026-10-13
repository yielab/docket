"""`docket exec --answers stdin` -- the one-line-at-a-time answer reader.

Pure-logic coverage: each fail-closed branch of ``handle_line`` against a real
approval record in an isolated home. The process-boundary behaviour (a paused
run resolved over a real pipe) is covered in
``tests/integration/test_harness_cli.py``.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from tests.conftest import repoint_docket_home

from docket.cli import _harness_answers
from docket.core import approval

SUBJECT = "docket.cli._harness_answers"


def _pipe_stdin(monkeypatch: pytest.MonkeyPatch, data: bytes | None) -> int:
    """Make ``sys.stdin`` a real pipe holding *data*; ``None`` leaves it open. Returns the write fd."""
    read_fd, write_fd = os.pipe()
    if data is not None:
        os.write(write_fd, data)
        os.close(write_fd)
        write_fd = -1
    monkeypatch.setattr("sys.stdin", os.fdopen(read_fd, "r"))
    return write_fd


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


class TestServeAtEndOfStdin:
    """End of stdin means no further answer can arrive: the reader marks the answer stream
    closed for the rest of the run, and the ledger learns the moment."""

    def test_eof_closes_the_stream_and_tells_the_ledger(
        self, home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import threading
        import time

        from docket.core import harness

        _pipe_stdin(monkeypatch, b"")
        ledger = harness.ApprovalLedger()
        closed_calls: list[bool] = []
        monkeypatch.setattr(ledger, "stream_closed", lambda: closed_calls.append(True))
        assert approval.answer_stream_closed() is False
        with _harness_answers.serve(RUN, threading.Event(), ledger=ledger):
            deadline = time.monotonic() + 5
            while not approval.answer_stream_closed() and time.monotonic() < deadline:
                time.sleep(0.01)
            assert approval.answer_stream_closed() is True
            assert closed_calls == [True]
        assert approval.answer_stream_closed() is False

    def test_a_stopped_reader_does_not_close_the_stream(
        self, home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import threading
        import time

        _pipe_stdin(monkeypatch, b"not an answer\n")
        stop = threading.Event()
        stop.set()
        with _harness_answers.serve(RUN, stop):
            time.sleep(0.05)
            assert approval.answer_stream_closed() is False


class TestReader:
    def test_a_run_ending_with_stdin_open_leaves_no_reader_thread(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import threading

        write_fd = _pipe_stdin(monkeypatch, None)
        try:
            with _harness_answers.serve(RUN, threading.Event()):
                assert any(t.name == "harness-answers" for t in threading.enumerate())
            assert not any(t.name == "harness-answers" for t in threading.enumerate())
        finally:
            os.close(write_fd)

    def test_a_line_arriving_while_the_run_is_live_is_applied(
        self, home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import threading
        import time

        token = _pending(home)
        write_fd = _pipe_stdin(monkeypatch, None)
        try:
            with _harness_answers.serve(RUN, threading.Event()):
                os.write(
                    write_fd, _line({"approvalToken": token, "action": "accept"}).encode() + b"\n"
                )
                deadline = time.monotonic() + 5
                while _state(token) != "granted" and time.monotonic() < deadline:
                    time.sleep(0.01)
        finally:
            os.close(write_fd)
        assert _state(token) == "granted"


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
