"""`docket setup sandbox` -- the bare verb and `status` are reads; a bad network word is usage."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.conftest import repoint_docket_home
from typer.testing import CliRunner

from docket.cli import _setup_sandbox, app
from docket.kernel.home import current_home

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
    fleet_before, audit_before = _bytes(current_home().fleet_file), _bytes(current_home().audit_log)

    result = _runner.invoke(app, ["setup", "sandbox"])

    assert result.exit_code == 0
    assert "always active" in result.stdout
    assert _bytes(current_home().fleet_file) == fleet_before
    assert _bytes(current_home().audit_log) == audit_before


def test_a_bad_network_word_is_a_usage_error_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fresh_home(tmp_path, monkeypatch)
    fleet_before = _bytes(current_home().fleet_file)

    result = _runner.invoke(app, ["setup", "sandbox", "network", "sideways"])

    assert result.exit_code == 2
    assert _bytes(current_home().fleet_file) == fleet_before


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
    fleet_before = _bytes(current_home().fleet_file)

    assert _setup_sandbox.isolate("on") == 1
    assert _bytes(current_home().fleet_file) == fleet_before


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

    def test_a_chosen_docker_says_it_was_chosen(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _fresh_home(tmp_path, monkeypatch)
        _probe(monkeypatch, "linux", landlock=True, docker=True)
        assert _runner.invoke(app, ["setup", "sandbox", "backend", "docker"]).exit_code == 0

        out = _runner.invoke(app, ["setup", "sandbox"]).stdout

        assert "Backend: docker (chosen; docket setup sandbox backend auto to go back)" in out

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


def test_a_fresh_home_does_not_claim_the_network_is_cut(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fresh_home(tmp_path, monkeypatch)

    out = _runner.invoke(app, ["setup", "sandbox"]).stdout
    line = next(ln for ln in out.splitlines() if "Network:" in ln)

    assert "not enforced: isolation off" in line
    assert "no network" not in line
    assert not line.startswith("ok")
    body = json.loads(_runner.invoke(app, ["setup", "sandbox", "status", "--json"]).stdout)
    assert body["networkEnforced"] is False


def test_isolation_on_keeps_the_network_line_and_marks_it_enforced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from docket.core import fleet as _fleet

    _fresh_home(tmp_path, monkeypatch)
    _fleet.set_sandbox_isolation()

    out = _runner.invoke(app, ["setup", "sandbox"]).stdout
    line = next(ln for ln in out.splitlines() if "Network:" in ln)

    assert line == "ok Network: none (default); jailed tool calls have no network"
    body = json.loads(_runner.invoke(app, ["setup", "sandbox", "status", "--json"]).stdout)
    assert body["networkEnforced"] is True


def test_recording_none_with_isolation_off_does_not_say_ok_for_a_cut_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fresh_home(tmp_path, monkeypatch)

    out = _runner.invoke(app, ["setup", "sandbox", "network", "none"]).stdout

    assert "jailed tool calls have no network" not in out
    assert "not enforced: isolation off" in out


class TestReadOnlyGrants:
    """`setup sandbox read add|remove` records the jail's read-only toolchain grants."""

    def test_add_records_the_resolved_path_audits_it_and_status_lists_it(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _fresh_home(tmp_path, monkeypatch)
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        tool = tmp_path / "opt" / "node"
        tool.mkdir(parents=True)

        result = _runner.invoke(app, ["setup", "sandbox", "read", "add", str(tool)])

        assert result.exit_code == 0, result.output
        status = _runner.invoke(app, ["setup", "sandbox", "status", "--json"])
        assert json.loads(status.stdout)["readOnly"] == [str(tool.resolve())]
        assert "gates.read" in current_home().audit_log.read_text()

    def test_remove_drops_the_grant(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _fresh_home(tmp_path, monkeypatch)
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        tool = tmp_path / "opt" / "node"
        tool.mkdir(parents=True)
        _runner.invoke(app, ["setup", "sandbox", "read", "add", str(tool)])

        result = _runner.invoke(app, ["setup", "sandbox", "read", "remove", str(tool)])

        assert result.exit_code == 0, result.output
        status = _runner.invoke(app, ["setup", "sandbox", "status", "--json"])
        assert json.loads(status.stdout)["readOnly"] == []

    @pytest.mark.parametrize(
        "kind", ["relative", "missing", "docket-home", "inside-home-dir", "home", "root"]
    )
    def test_a_path_that_would_expose_the_home_or_cannot_be_placed_is_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
    ) -> None:
        _fresh_home(tmp_path, monkeypatch)
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setenv("HOME", str(home))
        target = {
            "relative": "opt/node",
            "missing": str(tmp_path / "nope"),
            "docket-home": str(current_home().root),
            "inside-home-dir": str(current_home().root / "workspaces"),
            "home": str(home),
            "root": "/",
        }[kind]
        if kind == "inside-home-dir":
            (current_home().root / "workspaces").mkdir(exist_ok=True)
        fleet_before = _bytes(current_home().fleet_file)

        result = _runner.invoke(app, ["setup", "sandbox", "read", "add", target])

        assert result.exit_code == 1, result.output
        assert _bytes(current_home().fleet_file) == fleet_before
