"""`docket setup` -- the first-run report, then only what is missing.

Piped, the report names the model endpoint and the command that fixes it and exits 1 without
writing anything; on a scripted terminal the flow calls the same functions the verbs call.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.conftest import repoint_docket_home
from typer.testing import CliRunner

import docket.config as _cfg
from docket.cli import _contract, _setup, app
from docket.edges.adapters import llm as _llm

SUBJECT = "docket.cli._setup"

_runner = CliRunner()


def _home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / ".docket"
    repoint_docket_home(monkeypatch, home)
    return home


def _files(home: Path) -> list[str]:
    return sorted(str(p.relative_to(home)) for p in home.rglob("*")) if home.exists() else []


def _reachable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_llm, "probe_models", lambda *a, **k: _llm.ProbeResult(status=200))


def _ready_optionals(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, label in (
        ("_notify_piece", "notifications"),
        ("_sandbox_piece", "sandbox"),
        ("_shell_piece", "shell completion"),
        ("_service_piece", "background service"),
    ):
        piece = _setup.Piece(label, True, "ok", "")
        monkeypatch.setattr(_setup, name, lambda piece=piece: piece)


class TestPipedReport:
    def test_fresh_home_names_the_provider_command_and_writes_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = _home(tmp_path, monkeypatch)
        before = _files(home)

        result = _runner.invoke(app, ["setup"])

        assert result.exit_code == 1
        assert "docket setup provider add" in result.stdout + result.stderr
        assert "missing" in result.stdout
        assert _files(home) == before

    def test_json_carries_the_report_and_the_same_exit_code(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _home(tmp_path, monkeypatch)

        result = _runner.invoke(app, ["setup", "--json"])

        payload = json.loads(result.stdout)
        assert result.exit_code == 1
        assert payload["ready"] is False
        assert payload["pieces"][0]["command"].startswith("docket setup provider add")

    def test_readiness_is_pure(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        home = _home(tmp_path, monkeypatch)
        before = _files(home)

        report = _setup.readiness()

        assert report.endpoint.ok is False
        assert report.endpoint.command
        assert _files(home) == before

    def test_a_removed_name_is_an_unknown_command(self) -> None:
        for name in ("doctor", "models", "keys", "gates", "completions"):
            assert _runner.invoke(app, [name]).exit_code == 2


class TestScriptedTerminal:
    def test_answering_local_registers_the_provider_and_applies_the_preset(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = _home(tmp_path, monkeypatch)
        _reachable(monkeypatch)
        _ready_optionals(monkeypatch)
        monkeypatch.setattr(_contract, "_is_tty", lambda: True)

        result = _runner.invoke(app, ["setup"], input="local\n")

        assert result.exit_code == 0, result.stdout + result.stderr
        assert "ran: docket setup provider add local" in result.stdout
        assert "local" in json.loads((home / "docket-providers.json").read_text())["providers"]
        assert (home / "docket-models.json").is_file()
        assert "Ready" in result.stdout
        assert _setup.readiness().endpoint.ok

    def test_a_second_run_asks_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _home(tmp_path, monkeypatch)
        _reachable(monkeypatch)
        _ready_optionals(monkeypatch)
        monkeypatch.setattr(_contract, "_is_tty", lambda: True)
        assert _runner.invoke(app, ["setup"], input="local\n").exit_code == 0

        def _no_prompt(*_a: object, **_k: object) -> str:
            raise AssertionError("the second run asked a question")

        monkeypatch.setattr("builtins.input", _no_prompt)
        result = _runner.invoke(app, ["setup"])

        assert result.exit_code == 0
        assert "Ready" in result.stdout

    def test_an_unreachable_endpoint_ends_the_flow_with_exit_1(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = _home(tmp_path, monkeypatch)
        monkeypatch.setattr(
            _llm,
            "probe_models",
            lambda *a, **k: _llm.ProbeResult(status=None, transport_error="refused"),
        )
        monkeypatch.setattr(_contract, "_is_tty", lambda: True)

        result = _runner.invoke(app, ["setup"], input="local\n")

        assert result.exit_code == 1
        assert not (home / "docket-providers.json").exists()


class TestFix:
    def test_fix_runs_the_health_engine_with_repairs(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _home(tmp_path, monkeypatch)
        from docket.cli import _setup_check

        calls: list[bool] = []
        monkeypatch.setattr(
            _setup_check,
            "run_check",
            lambda json_out=False, do_fix=False: calls.append(do_fix) or 0,
        )

        result = _runner.invoke(app, ["setup", "--fix"])

        assert result.exit_code == 0
        assert calls == [True]
        assert (_cfg.POLICIES_DIR).is_dir()
