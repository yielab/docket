"""`docket setup sandbox` -- the bare verb and `status` are reads; a bad network word is usage."""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.conftest import repoint_docket_home
from typer.testing import CliRunner

import docket.config as _cfg
from docket.cli import _setup_sandbox, app

SUBJECT = "docket.cli._setup_sandbox"

_runner = CliRunner()


def _bytes(path: Path) -> bytes | None:
    return path.read_bytes() if path.exists() else None


def _fresh_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / ".docket"
    home.mkdir()
    repoint_docket_home(monkeypatch, home)


def test_bare_sandbox_is_a_read_that_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fresh_home(tmp_path, monkeypatch)
    fleet_before, audit_before = _bytes(_cfg.FLEET_FILE), _bytes(_cfg.AUDIT_LOG)

    result = _runner.invoke(app, ["setup", "sandbox"])

    assert result.exit_code == 0
    assert "always active" in result.stdout
    assert _bytes(_cfg.FLEET_FILE) == fleet_before
    assert _bytes(_cfg.AUDIT_LOG) == audit_before


def test_a_bad_network_word_is_a_usage_error_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fresh_home(tmp_path, monkeypatch)
    fleet_before = _bytes(_cfg.FLEET_FILE)

    result = _runner.invoke(app, ["setup", "sandbox", "network", "sideways"])

    assert result.exit_code == 2
    assert _bytes(_cfg.FLEET_FILE) == fleet_before


def test_json_status_reports_the_backend(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _fresh_home(tmp_path, monkeypatch)
    monkeypatch.setenv("DOCKET_SANDBOX_BACKEND", "none")

    result = _runner.invoke(app, ["setup", "sandbox", "status", "--json"])

    assert result.exit_code == 0
    assert '"backend": "none"' in result.stdout


def test_isolate_on_without_a_backend_fails_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fresh_home(tmp_path, monkeypatch)
    monkeypatch.setenv("DOCKET_SANDBOX_BACKEND", "none")
    fleet_before = _bytes(_cfg.FLEET_FILE)

    assert _setup_sandbox.isolate("on") == 1
    assert _bytes(_cfg.FLEET_FILE) == fleet_before
