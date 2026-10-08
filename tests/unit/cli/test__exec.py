"""`docket exec` -- pure-logic unit coverage for the parts that do not
need a real subprocess. The wire protocol, SIGTERM handling and home
isolation are process-boundary properties, covered end to end in
`tests/integration/test_harness_cli.py` instead.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.conftest import repoint_docket_home
from typer.testing import CliRunner

from docket.cli import _exec, app

SUBJECT = "docket.cli._exec"

runner = CliRunner()


class TestCommand:
    def test_exec_is_a_command_with_its_options_in_help(self) -> None:
        result = runner.invoke(app, ["exec", "--help"])
        assert result.exit_code == 0
        for option in ("--workspace", "--task", "--model", "--contract", "--recipe"):
            assert option in result.output
        assert "Example: docket exec" in result.output

    def test_harness_is_not_a_command(self) -> None:
        assert runner.invoke(app, ["harness", "run"]).exit_code == 2

    def test_an_unknown_option_is_a_usage_error(self) -> None:
        assert runner.invoke(app, ["exec", "--bogus"]).exit_code == 2


# ── _usage_error ──────────────────────────────────────────────────────────────


class TestUsageError:
    def test_missing_workspace_is_an_error(self) -> None:
        problem = _exec._usage_error(None, "hi", None, "local/x", None)
        assert problem == "--workspace is required"

    def test_missing_task_and_task_file_is_an_error(self) -> None:
        problem = _exec._usage_error("/ws", None, None, "local/x", None)
        assert problem is not None and "one of --task or --task-file" in problem

    def test_both_task_and_task_file_is_an_error(self) -> None:
        problem = _exec._usage_error("/ws", "hi", "/path", "local/x", None)
        assert problem is not None and "mutually exclusive" in problem

    def test_missing_model_is_an_error(self) -> None:
        problem = _exec._usage_error("/ws", "hi", None, None, None)
        assert problem == "--model is required"

    def test_a_non_integer_timeout_is_an_error(self) -> None:
        problem = _exec._usage_error("/ws", "hi", None, "local/x", "soon")
        assert problem is not None and "--timeout must be an integer" in problem

    def test_a_fully_specified_call_has_no_problem(self) -> None:
        assert _exec._usage_error("/ws", "hi", None, "local/x", "60") is None
        assert _exec._usage_error("/ws", None, "/path", "local/x", None) is None

    def test_an_unknown_contract_is_an_error(self) -> None:
        problem = _exec._usage_error("/ws", "hi", None, "local/x", None, "2.0")
        assert problem is not None and "--contract" in problem

    def test_contract_1_0_and_1_1_have_no_problem(self) -> None:
        assert _exec._usage_error("/ws", "hi", None, "local/x", None, "1.0") is None
        assert _exec._usage_error("/ws", "hi", None, "local/x", None, "1.1") is None

    def test_an_unknown_contract_is_reported_before_a_missing_workspace(self) -> None:
        problem = _exec._usage_error(None, "hi", None, "local/x", None, "2.0")
        assert problem is not None and "--contract" in problem


# ── run_exec ──────────────────────────────────────────────────────


class TestDispatch:
    def test_a_missing_workspace_refuses_before_touching_the_filesystem(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        home = tmp_path / "home"
        repoint_docket_home(monkeypatch, home)
        monkeypatch.setenv("DOCKET_LLM_BASE_URL", "http://127.0.0.1:1/v1")

        rc = _exec.run_exec(_exec.ExecOptions(task="x", model="local/x"))

        captured = capsys.readouterr()
        assert rc == 2
        lines = [line for line in captured.out.splitlines() if line.strip()]
        assert len(lines) == 1
        result = json.loads(lines[0])
        assert result["status"] == "refused"
        assert result["error"] == "--workspace is required"
        assert not home.exists()

    def test_an_unknown_contract_refuses_with_the_default_version_stamped(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        home = tmp_path / "home"
        repoint_docket_home(monkeypatch, home)
        monkeypatch.setenv("DOCKET_LLM_BASE_URL", "http://127.0.0.1:1/v1")

        rc = _exec.run_exec(
            _exec.ExecOptions(workspace=str(tmp_path), task="x", model="local/x", contract="2.0")
        )

        captured = capsys.readouterr()
        assert rc == 2
        lines = [line for line in captured.out.splitlines() if line.strip()]
        assert len(lines) == 1
        result = json.loads(lines[0])
        assert result["status"] == "refused"
        assert result["v"] == "1.0.0"
        assert "--contract" in result["error"]
        assert not home.exists()


def test_v10_event_line_omits_the_approval_pack_and_v11_keeps_it() -> None:
    from docket.core.harness import HARNESS_CONTRACT_V11

    record = {
        "ts": "t",
        "event_type": "approval_requested",
        "payload": {"token": "a", "tool": "bash", "rationale": "r", "options": [], "x": 1},
    }
    v10 = _exec._event_line("1.0", "run", 0, record).model_dump()
    assert v10["event"]["payload"] == {"token": "a", "tool": "bash", "x": 1}
    v11 = _exec._event_line(HARNESS_CONTRACT_V11, "run", 0, record).model_dump()
    assert v11["event"]["payload"]["rationale"] == "r"
