"""Run cancellation and run-record pruning through the CLI."""

from __future__ import annotations

from pathlib import Path

from tests.support import home as _support_home

from docket.tasks.application import runs as _runs

runs_file = _support_home.runs_file

SUBJECT = "docket.interfaces.cli.commands.task"


class TestRunsPruneCli:
    """`docket task prune --traces` also removes terminal run records."""

    def _prune(self, *extra: str) -> int:
        from typer.testing import CliRunner

        from docket.interfaces.cli.app import app

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
