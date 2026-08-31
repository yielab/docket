"""`docket runs list` / `docket runs show <id>` CLI surface.

Exercises ``cli/_runs.py``'s ``run_runs`` dispatcher directly (the same layer
``cli/__init__.py``'s ``cmd_runs`` delegates to) — Rich table + ``--json``
output for ``list``, and detail + ``--json`` output for ``show``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import docket.config as _cfg
from docket.cli._runs import run_runs
from docket.core import audit as _audit
from docket.core import runs as _runs


@pytest.fixture()
def runs_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    f = tmp_path / "docket-runs.json"
    monkeypatch.setattr(_cfg, "RUNS_FILE", f, raising=True)
    return f


class TestRunsListCli:
    def test_list_empty_returns_zero(self, runs_file: Path) -> None:
        assert run_runs("list", []) == 0

    def test_list_json_emits_bare_runs_array(
        self, runs_file: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _runs.create_run("cli", "demo")
        rc = run_runs("list", ["--json"])
        assert rc == 0
        out = json.loads(capsys.readouterr().out)
        assert "runs" in out
        assert len(out["runs"]) == 1
        assert out["runs"][0]["project"] == "demo"

    def test_list_filters_by_project_flag(
        self, runs_file: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _runs.create_run("cli", "alpha")
        _runs.create_run("cli", "beta")
        rc = run_runs("list", ["--project", "alpha", "--json"])
        assert rc == 0
        out = json.loads(capsys.readouterr().out)
        assert len(out["runs"]) == 1
        assert out["runs"][0]["project"] == "alpha"

    def test_list_table_renders_without_error(self, runs_file: Path) -> None:
        _runs.create_run("webhook", "demo")
        rc = run_runs("list", [])
        assert rc == 0

    def test_list_marks_running_cancellation_as_requested(
        self, runs_file: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rec = _runs.create_run("cli", "demo")
        _runs.mark_running(rec["id"])
        _runs.cancel_run(rec["id"])

        assert run_runs("list", []) == 0

        assert "cancel requested" in capsys.readouterr().out

    def test_list_defaults_when_no_sub_given(self, runs_file: Path) -> None:
        assert run_runs(None, []) == 0


class TestRunsShowCli:
    def test_show_missing_arg_is_an_error(self, runs_file: Path) -> None:
        assert run_runs("show", []) == 1

    def test_show_unknown_id_is_an_error(self, runs_file: Path) -> None:
        assert run_runs("show", ["run-nope"]) == 1

    def test_show_json_emits_the_record(
        self, runs_file: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rec = _runs.create_run("sweep", "demo")
        _runs.finish_run(rec["id"], state="succeeded", task_ids=["task-1"])
        rc = run_runs("show", [rec["id"], "--json"])
        assert rc == 0
        out = json.loads(capsys.readouterr().out)
        assert out["id"] == rec["id"]
        assert out["state"] == "succeeded"
        assert out["taskIds"] == ["task-1"]

    def test_show_human_readable_includes_error(self, runs_file: Path) -> None:
        rec = _runs.create_run("schedule", "demo")
        _runs.finish_run(rec["id"], state="failed", error="boom")
        rc = run_runs("show", [rec["id"]])
        assert rc == 0

    def test_show_human_readable_includes_cancellation_lifecycle(
        self, runs_file: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rec = _runs.create_run("cli", "demo")
        _runs.mark_running(rec["id"])
        _runs.cancel_run(rec["id"])

        assert run_runs("show", [rec["id"]]) == 0

        output = capsys.readouterr().out
        assert "Cancel requested:" in output
        assert "Cancel observed:" in output
        assert "Cancel stopped:" in output


class TestRunsCancelCli:
    """`docket runs cancel <id>`."""

    def test_cancel_missing_arg_is_an_error(self, runs_file: Path) -> None:
        assert run_runs("cancel", []) == 1

    def test_cancel_unknown_id_is_an_error(self, runs_file: Path) -> None:
        assert run_runs("cancel", ["run-nope"]) == 1

    def test_cancel_already_terminal_run_is_an_error(self, runs_file: Path) -> None:
        rec = _runs.create_run("cli", "demo")
        _runs.finish_run(rec["id"], state="succeeded", task_ids=[])
        assert run_runs("cancel", [rec["id"]]) == 1
        assert _runs.get_run(rec["id"])["state"] == "succeeded"

    def test_cancel_a_running_run_with_no_pids_persists_the_request(self, runs_file: Path) -> None:
        rec = _runs.create_run("cli", "demo")
        _runs.mark_running(rec["id"])
        assert run_runs("cancel", [rec["id"]]) == 0
        requested = _runs.get_run(rec["id"])
        assert requested is not None
        assert requested["state"] == "running"
        assert requested["cancellation"]["requestedAt"] is not None
        assert requested["cancellation"]["stoppedAt"] is None


class TestRunsCancelAuditEntry:
    """`docket runs cancel` was the one carried-forward gap in an
    otherwise-audited surface -- every other privileged action writes an
    audit entry (see ``core/audit.py``); cancellation shipped without one.
    ``_isolate_audit_log`` (conftest.py, autouse) already repoints
    ``_cfg.AUDIT_LOG`` at a per-test tmp file, so ``_audit.read_audit()``
    here reads exactly (and only) what this test wrote.
    """

    def test_successful_cancel_writes_a_runs_cancel_entry(self, runs_file: Path) -> None:
        rec = _runs.create_run("cli", "demo-project")
        _runs.mark_running(rec["id"])
        assert run_runs("cancel", [rec["id"]]) == 0

        entries = [e for e in _audit.read_audit() if e["action"] == "runs.cancel"]
        assert len(entries) == 1
        assert rec["id"] in entries[0]["detail"]
        assert "demo-project" in entries[0]["detail"]

    def test_unknown_id_writes_no_audit_entry(self, runs_file: Path) -> None:
        assert run_runs("cancel", ["run-nope"]) == 1
        assert [e for e in _audit.read_audit() if e["action"] == "runs.cancel"] == []

    def test_already_terminal_run_writes_no_audit_entry(self, runs_file: Path) -> None:
        rec = _runs.create_run("cli", "demo")
        _runs.finish_run(rec["id"], state="succeeded", task_ids=[])
        assert run_runs("cancel", [rec["id"]]) == 1
        assert [e for e in _audit.read_audit() if e["action"] == "runs.cancel"] == []

    def test_cancel_entry_is_chained_like_every_other_action(self, runs_file: Path) -> None:
        rec = _runs.create_run("cli", "demo")
        _runs.mark_running(rec["id"])
        run_runs("cancel", [rec["id"]])

        result = _audit.verify_chain()
        assert result.break_at is None
        assert result.chained >= 1


class TestRunsUnknownSubcommand:
    def test_unknown_subcommand_errors(self, runs_file: Path) -> None:
        assert run_runs("bogus", []) == 1


class TestRunsCommandWiring:
    """Smoke-test `docket runs ...` is actually registered on the Typer app
    and delegates to cli/_runs.py, using the same CliRunner-driven wiring
    check every other Typer command in this suite uses."""

    def test_runs_list_wired_on_app(self, runs_file: Path) -> None:
        from typer.testing import CliRunner

        from docket.cli import app

        runner = CliRunner()
        result = runner.invoke(app, ["runs", "list"])
        assert result.exit_code == 0

    def test_runs_show_wired_on_app(self, runs_file: Path) -> None:
        from typer.testing import CliRunner

        from docket.cli import app

        rec = _runs.create_run("cli", "demo")
        runner = CliRunner()
        result = runner.invoke(app, ["runs", "show", rec["id"], "--json"])
        assert result.exit_code == 0
        out = json.loads(result.output)
        assert out["id"] == rec["id"]

    def test_runs_cancel_wired_on_app(self, runs_file: Path) -> None:
        from typer.testing import CliRunner

        from docket.cli import app

        rec = _runs.create_run("cli", "demo")
        _runs.mark_running(rec["id"])
        runner = CliRunner()
        result = runner.invoke(app, ["runs", "cancel", rec["id"]])
        assert result.exit_code == 0
        requested = _runs.get_run(rec["id"])
        assert requested is not None
        assert requested["state"] == "running"
        assert requested["cancellation"]["requestedAt"] is not None

    def test_runs_is_a_top_level_command(self) -> None:
        import typer.main

        from docket.cli import app

        click_command = typer.main.get_command(app)
        assert "runs" in click_command.commands
