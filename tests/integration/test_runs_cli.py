"""Run cancellation and run-record pruning through the CLI."""

from __future__ import annotations

from pathlib import Path

import pytest

import docket.config as _cfg
from docket.core import runs as _runs

SUBJECT = "docket.cli"


@pytest.fixture()
def runs_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    f = tmp_path / "docket-runs.json"
    monkeypatch.setattr(_cfg, "RUNS_FILE", f, raising=True)
    return f


class TestRunsPruneCli:
    """`docket task prune --traces` also removes terminal run records."""

    def _prune(self, *extra: str) -> int:
        from typer.testing import CliRunner

        from docket.cli import app

        args = ["task", "prune", "--traces", "--days", "0", "--pod", "demo", *extra]
        return CliRunner().invoke(app, args).exit_code

    def test_prune_removes_old_terminal_runs(self, runs_file: Path) -> None:
        rec = _runs.create_run("cli", "demo")
        _runs.finish_run(rec["id"], state="succeeded", task_ids=[])
        assert self._prune() == 0
        assert _runs.get_run(rec["id"]) is None

    def test_prune_dry_run_does_not_delete(self, runs_file: Path) -> None:
        rec = _runs.create_run("cli", "demo")
        _runs.finish_run(rec["id"], state="succeeded", task_ids=[])
        assert self._prune("--dry-run") == 0
        assert _runs.get_run(rec["id"]) is not None
