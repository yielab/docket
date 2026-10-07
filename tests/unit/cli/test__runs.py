"""``docket runs show`` exit code follows the recorded run state."""

from __future__ import annotations

from pathlib import Path

import pytest

import docket.config as _cfg
from docket.cli import _runs as _runs_cli
from docket.core import runs as _runs

SUBJECT = "docket.cli._runs"


@pytest.fixture(autouse=True)
def _runs_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_cfg, "RUNS_FILE", tmp_path / "docket-runs.json", raising=True)


class _Result:
    def __init__(self, task_id: str, status: str, reason: str = "") -> None:
        self.task_id = task_id
        self.status = status
        self.reason = reason


def _run_with(*results: _Result) -> str:
    rec = _runs.create_run("cli", "demo")
    _runs.execute(rec["id"], lambda: list(results))
    return str(rec["id"])


class TestShowExitCode:
    def test_a_failed_run_exits_one(self) -> None:
        run_id = _run_with(_Result("task-1", "failed", "verifyCmd exited 1"))
        assert _runs_cli._show([run_id]) == 1

    def test_a_succeeded_run_exits_zero(self) -> None:
        run_id = _run_with(_Result("task-1", "done"))
        assert _runs_cli._show([run_id]) == 0

    def test_a_parked_run_exits_zero(self) -> None:
        run_id = _run_with(_Result("task-1", "waiting_input"))
        assert _runs_cli._show([run_id]) == 0

    def test_an_unknown_run_exits_one(self) -> None:
        assert _runs_cli._show(["run-nope"]) == 1
