"""`docket start` and `docket stop` -- the pid file, the already-running refusal and the stop."""

from __future__ import annotations

import os
import signal
from pathlib import Path

import pytest
from tests.conftest import repoint_docket_home
from typer.testing import CliRunner

import docket.config as _cfg
from docket.cli import _service, app

SUBJECT = "docket.cli._service"

runner = CliRunner()


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    repoint_docket_home(monkeypatch, tmp_path / "home")
    (tmp_path / "home").mkdir()
    return tmp_path / "home"


class _FakeProcess:
    """A pid that stays alive until it has received ``dies_after`` SIGTERMs."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, dies_after: int) -> None:
        self.pid = 424242
        self.signals: list[int] = []
        self.dies_after = dies_after

        def _kill(pid: int, sig: int) -> None:
            if sig == 0:
                if self.dead:
                    raise ProcessLookupError
                return
            assert pid == self.pid
            self.signals.append(sig)

        monkeypatch.setattr(_service.os, "kill", _kill)

    @property
    def dead(self) -> bool:
        return len(self.signals) >= self.dies_after


def test_is_running_follows_the_pid_file(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeProcess(monkeypatch, dies_after=1)
    assert not _service.is_running()
    _cfg.SERVE_PID_FILE.write_text(f"{fake.pid}\n")
    assert _service.is_running()
    fake.signals.append(signal.SIGTERM)
    assert not _service.is_running()


def test_stop_with_nothing_running_exits_zero(home: Path) -> None:
    assert runner.invoke(app, ["stop"]).exit_code == 0


def test_stop_sends_one_signal_when_the_service_exits(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _FakeProcess(monkeypatch, dies_after=1)
    _cfg.SERVE_PID_FILE.write_text(f"{fake.pid}\n")
    assert runner.invoke(app, ["stop", "--wait", "1"]).exit_code == 0
    assert fake.signals == [signal.SIGTERM]
    assert not _cfg.SERVE_PID_FILE.exists()


def test_stop_sends_a_second_signal_when_sweeps_hang(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _FakeProcess(monkeypatch, dies_after=2)
    _cfg.SERVE_PID_FILE.write_text(f"{fake.pid}\n")
    assert runner.invoke(app, ["stop", "--wait", "0"]).exit_code == 0
    assert fake.signals == [signal.SIGTERM, signal.SIGTERM]
    assert not _cfg.SERVE_PID_FILE.exists()


def test_start_refuses_when_already_running(home: Path) -> None:
    _cfg.SERVE_PID_FILE.write_text(f"{os.getpid()}\n")
    assert runner.invoke(app, ["start"]).exit_code == 1


def test_start_removes_its_pid_file_when_the_service_returns(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[str] = []

    def _fake_run_serve(**_kw: object) -> None:
        seen.append(_cfg.SERVE_PID_FILE.read_text().strip())

    monkeypatch.setattr("docket.serve.run_serve", _fake_run_serve)
    assert runner.invoke(app, ["start"]).exit_code == 0
    assert seen == [str(os.getpid())]
    assert not _cfg.SERVE_PID_FILE.exists()


def test_mcp_refuses_the_flags_that_print_to_stdout(home: Path) -> None:
    assert runner.invoke(app, ["start", "--mcp", "--dispatch"]).exit_code == 2


def test_serve_is_not_a_command(home: Path) -> None:
    assert runner.invoke(app, ["serve"]).exit_code == 2
