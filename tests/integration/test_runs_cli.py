"""Run cancellation and run-record pruning through the CLI."""

from __future__ import annotations

from pathlib import Path

import pytest

import docket.config as _cfg
from docket.cli._runs import _cancel
from docket.core import audit as _audit
from docket.core import runs as _runs

SUBJECT = "docket.cli"


@pytest.fixture()
def runs_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    f = tmp_path / "docket-runs.json"
    monkeypatch.setattr(_cfg, "RUNS_FILE", f, raising=True)
    return f


class TestRunsCancelCli:
    """`docket runs cancel <id>`."""

    def test_cancel_missing_arg_is_an_error(self, runs_file: Path) -> None:
        assert _cancel([]) == 1

    def test_cancel_unknown_id_is_an_error(self, runs_file: Path) -> None:
        assert _cancel(["run-nope"]) == 1

    def test_cancel_already_terminal_run_is_an_error(self, runs_file: Path) -> None:
        rec = _runs.create_run("cli", "demo")
        _runs.finish_run(rec["id"], state="succeeded", task_ids=[])
        assert _cancel([rec["id"]]) == 1
        assert _runs.get_run(rec["id"])["state"] == "succeeded"

    def test_cancel_a_running_run_with_no_pids_persists_the_request(self, runs_file: Path) -> None:
        rec = _runs.create_run("cli", "demo")
        _runs.mark_running(rec["id"])
        assert _cancel([rec["id"]]) == 0
        requested = _runs.get_run(rec["id"])
        assert requested is not None
        assert requested["state"] == "running"
        assert requested["cancellation"]["requestedAt"] is not None
        assert requested["cancellation"]["stoppedAt"] is None


class TestRunsCancelAuditEntry:
    """`docket runs cancel` writes an audit entry like every other privileged action (see
    ``core/audit.py``). ``_isolate_audit_log`` (conftest.py, autouse) repoints ``_cfg.AUDIT_LOG``
    at a per-test tmp file, so ``_audit.read_audit()`` reads exactly what this test wrote."""

    def test_successful_cancel_writes_a_runs_cancel_entry(self, runs_file: Path) -> None:
        rec = _runs.create_run("cli", "demo-project")
        _runs.mark_running(rec["id"])
        assert _cancel([rec["id"]]) == 0

        entries = [e for e in _audit.read_audit() if e["action"] == "runs.cancel"]
        assert len(entries) == 1
        assert rec["id"] in entries[0]["detail"]
        assert "demo-project" in entries[0]["detail"]

    def test_unknown_id_writes_no_audit_entry(self, runs_file: Path) -> None:
        assert _cancel(["run-nope"]) == 1
        assert [e for e in _audit.read_audit() if e["action"] == "runs.cancel"] == []

    def test_already_terminal_run_writes_no_audit_entry(self, runs_file: Path) -> None:
        rec = _runs.create_run("cli", "demo")
        _runs.finish_run(rec["id"], state="succeeded", task_ids=[])
        assert _cancel([rec["id"]]) == 1
        assert [e for e in _audit.read_audit() if e["action"] == "runs.cancel"] == []

    def test_cancel_entry_is_chained_like_every_other_action(self, runs_file: Path) -> None:
        rec = _runs.create_run("cli", "demo")
        _runs.mark_running(rec["id"])
        _cancel([rec["id"]])

        result = _audit.verify_chain()
        assert result.break_at is None
        assert result.chained >= 1


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
