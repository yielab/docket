"""`docket setup sandbox` -- the bare verb and `status` are reads; a bad network word is usage."""

from __future__ import annotations

import json
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


def _probe(
    monkeypatch: pytest.MonkeyPatch,
    platform: str,
    *,
    landlock: bool = False,
    seatbelt: bool = False,
    docker: bool = False,
) -> None:
    monkeypatch.delenv("DOCKET_SANDBOX_BACKEND", raising=False)
    monkeypatch.setattr(_setup_sandbox.sys, "platform", platform)
    syst = _setup_sandbox._sys
    monkeypatch.setattr(syst, "landlock_available", lambda: landlock)
    monkeypatch.setattr(syst, "seatbelt_available", lambda: seatbelt)
    monkeypatch.setattr(syst, "docker_daemon_reachable", lambda: docker)
    monkeypatch.setattr(syst, "bwrap_available", lambda: False, raising=False)


class TestTheProbeReport:
    def test_landlock_on_linux_names_the_kernel(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _fresh_home(tmp_path, monkeypatch)
        _probe(monkeypatch, "linux", landlock=True)
        monkeypatch.setattr(_setup_sandbox.platform, "release", lambda: "6.14.0-37-generic")

        out = _runner.invoke(app, ["setup", "sandbox"]).stdout

        assert "Backend: landlock (kernel 6.14)" in out
        assert "Sandbox   off. The agent's commands run with your user's permissions." in out
        assert "Turn it on: docket setup sandbox on" in out

    def test_seatbelt_on_macos(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _fresh_home(tmp_path, monkeypatch)
        _probe(monkeypatch, "darwin", seatbelt=True)

        assert "Backend: seatbelt" in _runner.invoke(app, ["setup", "sandbox"]).stdout

    def test_linux_without_landlock_says_what_to_install(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _fresh_home(tmp_path, monkeypatch)
        _probe(monkeypatch, "linux")

        out = _runner.invoke(app, ["setup", "sandbox"]).stdout

        assert "Linux: a kernel with Landlock (>= 5.13)" in out
        assert "Sandbox   not available: Linux needs a kernel with Landlock (5.13 or newer)." in out

    def test_native_windows_gets_the_wsl2_line(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _fresh_home(tmp_path, monkeypatch)
        _probe(monkeypatch, "win32")

        out = _runner.invoke(app, ["setup", "sandbox"]).stdout

        assert "Windows: use WSL2; native runs without a sandbox" in out
        assert "Sandbox   not available on native Windows; use WSL2." in out

    def test_on_with_a_backend_reads_on_and_the_network(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _fresh_home(tmp_path, monkeypatch)
        _probe(monkeypatch, "linux", landlock=True)
        assert _setup_sandbox.isolate("on") == 0

        assert _setup_sandbox.sandbox_lines() == ["Sandbox   on (landlock, network none)"]

    def test_json_carries_the_platform_report(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _fresh_home(tmp_path, monkeypatch)
        _probe(monkeypatch, "linux")

        body = json.loads(_runner.invoke(app, ["setup", "sandbox", "--json"]).stdout)

        assert body["platform"] == "linux"
        assert body["available"] == []
        assert body["missing"] == "Linux: a kernel with Landlock (>= 5.13)"
        assert body["line"].startswith("Sandbox   not available: Linux needs")
        assert body["backend"] == "none"
