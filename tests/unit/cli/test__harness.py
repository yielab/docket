"""`docket harness` -- pure-logic unit coverage for the parts that do not
need a real subprocess. The wire protocol, SIGTERM handling and home
isolation are process-boundary properties, covered end to end in
`tests/integration/test_harness_cli.py` instead.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from tests.conftest import repoint_docket_home

from docket.cli import _harness
from docket.core.runtime_driver import UsageReport, UsageTotals

SUBJECT = "docket.cli._harness"


# ── _flag ─────────────────────────────────────────────────────────────────────


class TestFlag:
    def test_reads_a_space_separated_value(self) -> None:
        assert _harness._flag(["--model", "local/x"], "--model") == "local/x"

    def test_reads_an_equals_separated_value(self) -> None:
        assert _harness._flag(["--model=local/x"], "--model") == "local/x"

    def test_missing_flag_returns_none(self) -> None:
        assert _harness._flag(["--task", "hi"], "--model") is None

    def test_a_flag_with_no_following_value_returns_none(self) -> None:
        assert _harness._flag(["--model"], "--model") is None


# ── _usage_error ──────────────────────────────────────────────────────────────


class TestUsageError:
    def test_missing_workspace_is_an_error(self) -> None:
        problem = _harness._usage_error(None, "hi", None, "local/x", None)
        assert problem == "--workspace is required"

    def test_missing_task_and_task_file_is_an_error(self) -> None:
        problem = _harness._usage_error("/ws", None, None, "local/x", None)
        assert problem is not None and "one of --task or --task-file" in problem

    def test_both_task_and_task_file_is_an_error(self) -> None:
        problem = _harness._usage_error("/ws", "hi", "/path", "local/x", None)
        assert problem is not None and "mutually exclusive" in problem

    def test_missing_model_is_an_error(self) -> None:
        problem = _harness._usage_error("/ws", "hi", None, None, None)
        assert problem == "--model is required"

    def test_a_non_integer_timeout_is_an_error(self) -> None:
        problem = _harness._usage_error("/ws", "hi", None, "local/x", "soon")
        assert problem is not None and "--timeout must be an integer" in problem

    def test_a_fully_specified_call_has_no_problem(self) -> None:
        assert _harness._usage_error("/ws", "hi", None, "local/x", "60") is None
        assert _harness._usage_error("/ws", None, "/path", "local/x", None) is None


# ── run_harness dispatch ──────────────────────────────────────────────────────


class TestDispatch:
    def test_an_unknown_subcommand_prints_usage_to_stderr_and_fails(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rc = _harness.run_harness("bogus", [])
        captured = capsys.readouterr()
        assert rc == 1
        assert captured.out == ""
        assert "usage: docket harness" in captured.err

    def test_a_missing_workspace_refuses_before_touching_the_filesystem(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        home = tmp_path / "home"
        repoint_docket_home(monkeypatch, home)
        monkeypatch.setenv("DOCKET_LLM_BASE_URL", "http://127.0.0.1:1/v1")

        rc = _harness.run_harness("run", ["--task", "x", "--model", "local/x"])

        captured = capsys.readouterr()
        assert rc == 2
        lines = [line for line in captured.out.splitlines() if line.strip()]
        assert len(lines) == 1
        result = json.loads(lines[0])
        assert result["status"] == "refused"
        assert result["error"] == "--workspace is required"
        assert not home.exists()


# ── status: unknown / finished reconstruction ────────────────────────────────


class TestStatus:
    def test_status_with_no_token_is_a_usage_error(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rc = _harness._status([])
        captured = capsys.readouterr()
        assert rc == 1
        assert captured.out == ""
        assert "usage: docket harness status" in captured.err

    def test_unknown_token_reports_unknown(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        repoint_docket_home(monkeypatch, tmp_path / "home")

        rc = _harness._status(["not-a-real-token"])

        captured = capsys.readouterr()
        assert rc == 0
        body = json.loads(captured.out.strip())
        assert body == {"v": "1.0.0", "token": "not-a-real-token", "state": "unknown"}

    def test_finished_reconstructs_a_best_effort_result(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        home = tmp_path / "home"
        repoint_docket_home(monkeypatch, home)
        (home / "docket-runs.json").parent.mkdir(parents=True, exist_ok=True)
        (home / "docket-runs.json").write_text(
            json.dumps(
                {
                    "runs": [
                        {
                            "id": "run-1",
                            "state": "succeeded",
                            "project": "harness-agent",
                            "variables": {"model": "local/requested"},
                            "error": "",
                        }
                    ]
                }
            )
        )

        class _FakeDriver:
            def usage(self, agent_id: str) -> UsageReport:
                assert agent_id == "harness-agent"
                return UsageReport(
                    totals=UsageTotals(input_tokens=10, output_tokens=5, cache_read=1, turns=2)
                )

        monkeypatch.setattr(_harness._dr, "default_driver", lambda: _FakeDriver())

        rc = _harness._status(["run-1"])

        captured = capsys.readouterr()
        assert rc == 0
        body: dict[str, Any] = json.loads(captured.out.strip())
        assert body["state"] == "finished"
        assert body["result"]["status"] == "ok"
        assert body["result"]["run_state"] == "succeeded"
        assert body["result"]["model"]["requested"] == "local/requested"
        assert body["result"]["usage"] == {
            "input_tokens": 10,
            "output_tokens": 5,
            "cached_tokens": 1,
            "turns": 2,
        }
