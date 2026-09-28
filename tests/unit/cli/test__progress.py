"""`docket.cli._progress` -- rendering, answer parsing and the thread
orchestration behind `docket pod <p> dispatch`'s foreground progress view.
Behind a real TTY on a real dispatch, see `tests/unit/cli/test_pod.py`.
"""

from __future__ import annotations

import io
import json
import queue
import time
from pathlib import Path
from typing import Any

import pytest
from tests.conftest import repoint_docket_home

import docket.config as _cfg
from docket.cli import _progress
from docket.core import approval as _ap

SUBJECT = "docket.cli._progress"


def _home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / ".docket"
    repoint_docket_home(monkeypatch, home)
    return home


def _record(
    event_type: str, payload: dict[str, Any], *, role: str = "implementer"
) -> dict[str, Any]:
    return {
        "ts": "2026-09-28T00:00:00Z",
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
    def test_session_start(self) -> None:
        line = _progress.render_event(_record("session_start", {}, role="lead"))
        assert line == "▶ lead …"

    def test_session_end_carries_the_status(self) -> None:
        line = _progress.render_event(_record("session_end", {"status": "done"}, role="lead"))
        assert line == "■ lead finished — status=done"

    def test_approval_required_names_the_token_and_the_approve_command(self) -> None:
        line = _progress.render_event(
            _record("approval_required", {"token": "apr-1", "role": "lead"}, role="lead")
        )
        assert line == "⏸ lead hop needs approval · token apr-1 · docket approve apr-1"

    def test_approval_requested_counts_down_from_the_configured_timeout(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(_cfg, "TOOL_APPROVAL_TIMEOUT", 120, raising=True)
        record = _record(
            "approval_requested",
            {"token": "apr-2", "action": "bash('rm -rf x')"},
        )
        now = _progress._epoch(record["ts"]) + 20  # 20s have elapsed since the event
        line = _progress.render_event(record, now=now)
        assert line == (
            "⏸ implementer wants: bash('rm -rf x') · token apr-2 · denies in 100s · "
            "docket approve apr-2"
        )

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

    @pytest.mark.parametrize("line", ["\n", "", "x\n", "approve\n"])
    def test_anything_else_keeps_waiting(self, line: str) -> None:
        assert _progress.parse_answer(line) == ""


# ── handle_approval_prompt ────────────────────────────────────────────────────


class TestHandleApprovalPrompt:
    def test_a_grants_through_the_same_pair_docket_approve_uses(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _home(tmp_path, monkeypatch)
        token = _ap.approval_create("demo", "implementer", "bash: git push origin main")

        outcome = _progress.handle_approval_prompt(token, "a")

        assert outcome.action == "granted"
        assert _ap.approval_get(token)["state"] == "granted"

    def test_d_denies_through_the_same_pair_docket_deny_uses(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _home(tmp_path, monkeypatch)
        token = _ap.approval_create("demo", "implementer", "bash: git push origin main")

        outcome = _progress.handle_approval_prompt(token, "d")

        assert outcome.action == "denied"
        assert _ap.approval_get(token)["state"] == "denied"

    def test_an_empty_answer_keeps_waiting_and_touches_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _home(tmp_path, monkeypatch)
        token = _ap.approval_create("demo", "implementer", "bash: git push origin main")

        outcome = _progress.handle_approval_prompt(token, "")

        assert outcome.action == "waiting"
        assert _ap.approval_get(token)["state"] == "pending"

    def test_a_token_already_resolved_elsewhere_is_reported_not_raised(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _home(tmp_path, monkeypatch)
        token = _ap.approval_create("demo", "implementer", "bash: git push origin main")
        _ap.approval_grant(token, channel="mcp")

        outcome = _progress.handle_approval_prompt(token, "a")

        assert outcome.action == "noop"
        assert outcome.message


# ── stdin_reader_loop ─────────────────────────────────────────────────────────


class TestStdinReaderLoop:
    def test_reads_every_recognised_line_until_eof(self) -> None:
        answers: queue.Queue[str] = queue.Queue()
        _progress.stdin_reader_loop(io.StringIO("a\n\nd\nbogus\n"), answers)

        assert list(answers.queue) == ["a", "d"]

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
        _home(tmp_path, monkeypatch)
        from docket.core import trace as _trace

        monkeypatch.setattr(_cfg, "TOOL_APPROVAL_POLL_INTERVAL_S", 0.02, raising=True)
        granted_token: dict[str, str] = {}

        def fake_execute(run_id: str, fn: Any) -> list[Any]:
            _trace.trace_event("demo", "s1", "lead", "session_start", json.dumps({}))
            token = _ap.approval_create("demo", "implementer", "bash: git push origin main")
            granted_token["token"] = token
            deadline = time.monotonic() + 1.5
            while time.monotonic() < deadline:
                if _ap.approval_get(token)["state"] != "pending":
                    break
                time.sleep(0.02)
            _trace.trace_event("demo", "s1", "lead", "session_end", json.dumps({"status": "done"}))
            return []

        monkeypatch.setattr(_progress._runs, "execute", fake_execute)
        lines: list[str] = []

        result = _progress.dispatch_with_progress(
            "run-1", lambda: [], prompt=True, stdin=io.StringIO("a\n"), println=lines.append
        )

        assert result == []
        assert _ap.approval_get(granted_token["token"])["state"] == "granted"
        assert any(line.startswith("▶ lead") for line in lines)
        assert any("wants: bash: git push origin main" in line for line in lines)
        assert any(line.startswith("■ lead finished") for line in lines)

    def test_without_prompt_it_only_renders(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _home(tmp_path, monkeypatch)
        from docket.core import trace as _trace

        def fake_execute(run_id: str, fn: Any) -> list[Any]:
            _trace.trace_event("demo", "s1", "lead", "session_start", json.dumps({}))
            _trace.trace_event("demo", "s1", "lead", "session_end", json.dumps({"status": "done"}))
            return []

        monkeypatch.setattr(_progress._runs, "execute", fake_execute)
        lines: list[str] = []

        result = _progress.dispatch_with_progress(
            "run-2", lambda: [], prompt=False, stdin=io.StringIO(""), println=lines.append
        )

        assert result == []
        assert lines == ["▶ lead …", "■ lead finished — status=done"]
