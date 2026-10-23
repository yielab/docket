"""`docket setup` -- the first-run report, then only what is missing.

Piped, the report names the model endpoint and the command that fixes it and exits 1 without
writing anything; on a scripted terminal the flow calls the same functions the verbs call.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from typer.testing import CliRunner

from docket.cli import _contract, _setup, app
from docket.edges.adapters import llm as _llm
from docket.edges.adapters import system as _system
from docket.kernel.home import Home, current_home, use_home

SUBJECT = "docket.cli._setup"

_runner = CliRunner()


@contextmanager
def _home(
    tmp_path: Path,
) -> Iterator[Path]:
    home = tmp_path / ".docket"
    with use_home(Home(home)):
        yield home


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


class TestResolveVersion:
    """`docket --version` names the commit when it runs from a git checkout, so a source tree
    ahead of the last tag is told apart from the wheel that prints the same version."""

    def test_a_wheel_install_prints_the_bare_version(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(_setup, "_source_root", lambda: tmp_path)
        monkeypatch.setattr(_setup, "_package_version", lambda: "0.2.0b4")
        assert _setup._resolve_version() == "0.2.0b4"

    def test_a_git_checkout_appends_the_commit(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / ".git").mkdir()
        monkeypatch.setattr(_setup, "_source_root", lambda: tmp_path)
        monkeypatch.setattr(_setup, "_package_version", lambda: "0.2.0b4")
        monkeypatch.setattr(_system, "git_head_sha", lambda cwd: "2359189412ab" + "0" * 28)
        monkeypatch.setattr(_system, "git_worktree_changes", lambda cwd: [])
        assert _setup._resolve_version() == "0.2.0b4 (git 23591894)"

    def test_uncommitted_changes_are_marked_dirty(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / ".git").mkdir()
        monkeypatch.setattr(_setup, "_source_root", lambda: tmp_path)
        monkeypatch.setattr(_setup, "_package_version", lambda: "0.2.0b4")
        monkeypatch.setattr(_system, "git_head_sha", lambda cwd: "2359189412ab" + "0" * 28)
        monkeypatch.setattr(_system, "git_worktree_changes", lambda cwd: [("M", "/x/a.py")])
        assert _setup._resolve_version() == "0.2.0b4 (git 23591894, dirty)"

    def test_a_checkout_without_git_on_the_path_prints_the_bare_version(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / ".git").mkdir()
        monkeypatch.setattr(_setup, "_source_root", lambda: tmp_path)
        monkeypatch.setattr(_setup, "_package_version", lambda: "0.2.0b4")
        monkeypatch.setattr(_system, "git_head_sha", lambda cwd: None)
        assert _setup._resolve_version() == "0.2.0b4"


class TestPipedReport:
    def test_fresh_home_names_the_provider_command_and_writes_nothing(self, tmp_path: Path) -> None:
        with _home(tmp_path) as home:
            before = _files(home)

            result = _runner.invoke(app, ["setup"])

            assert result.exit_code == 1
            assert "docket setup provider add" in result.stdout + result.stderr
            assert "missing" in result.stdout
            assert _files(home) == before

    def test_json_carries_the_report_and_the_same_exit_code(self, tmp_path: Path) -> None:
        with _home(tmp_path):
            result = _runner.invoke(app, ["setup", "--json"])

            payload = json.loads(result.stdout)
            assert result.exit_code == 1
            assert payload["ready"] is False
            assert payload["pieces"][0]["command"].startswith("docket setup provider add")

    def test_readiness_is_pure(self, tmp_path: Path) -> None:
        with _home(tmp_path) as home:
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
        with _home(tmp_path) as home:
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
        with _home(tmp_path):
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
        with _home(tmp_path) as home:
            monkeypatch.setattr(
                _llm,
                "probe_models",
                lambda *a, **k: _llm.ProbeResult(status=None, transport_error="refused"),
            )
            monkeypatch.setattr(_contract, "_is_tty", lambda: True)

            result = _runner.invoke(app, ["setup"], input="local\n")

            assert result.exit_code == 1
            assert not (home / "docket-providers.json").exists()


class TestTelegramStep:
    def test_the_wizard_calls_the_one_step_connect(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The seam between the flow and ``setup notify``: one function, called with the chat
        and token the operator typed, and told not to send."""
        import getpass

        from docket.cli import _setup_notify

        with _home(tmp_path):
            calls: list[tuple[list[str], str | None, bool]] = []

            def _record(
                chats: list[str], token: str | None, *, test: bool
            ) -> _setup_notify.Written:
                calls.append((chats, token, test))
                return _setup_notify.Written(
                    secret="TELEGRAM_BOT_TOKEN", actors=chats, bindings=["a"]
                )

            monkeypatch.setattr(_setup_notify, "enable_telegram", _record)
            monkeypatch.setattr(_setup, "_ask", lambda q: q == "Set up Telegram?")
            monkeypatch.setattr("builtins.input", lambda _p="": "42")
            monkeypatch.setattr(getpass, "getpass", lambda _p="": "t")
            report = _setup.Readiness(
                endpoint=_setup.Piece("model endpoint", True, "", ""),
                notify=_setup.Piece("notifications", False, "console only", "docket setup notify"),
            )

            _setup._ask_optional(report)

            assert calls == [(["42"], "t", False)]


class TestFix:
    def test_fix_runs_the_health_engine_with_repairs(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        with _home(tmp_path):
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
            assert (current_home().policies_dir).is_dir()

    def test_fix_json_keeps_stdout_a_single_json_document(self, tmp_path: Path) -> None:
        """The install line goes to stderr, so a fresh home's stdout parses as JSON."""
        with _home(tmp_path):
            result = _runner.invoke(app, ["setup", "--fix", "--json"])

            assert "healthy" in json.loads(result.stdout)
            assert "Installed" in result.stderr
            assert "Installed" not in result.stdout

    def test_fix_without_json_still_prints_the_install_line_on_stdout(self, tmp_path: Path) -> None:
        with _home(tmp_path):
            result = _runner.invoke(app, ["setup", "--fix"])

            assert "Installed" in result.stdout

    def test_the_fix_help_names_only_the_repairs_it_makes(self) -> None:
        output = _runner.invoke(app, ["setup", "--help"]).output
        text = " ".join(output.replace("│", " ").split())

        assert "baseline policies" in text and "dispatch ledger" in text
        assert "workspace files" not in text and "permissions" not in text
