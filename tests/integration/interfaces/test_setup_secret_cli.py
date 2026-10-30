"""`docket setup secret set|list|remove` -- a secret stored under any name through the one writer.

Pins: a value piped with `--stdin` is stored and `secret_value` resolves it; the value reaches
neither stdout, stderr, the audit log nor `list`; a value given as an argument exits 2 and writes
nothing; an unusable name, an empty value or a missing `--stdin` off a terminal exits 1 writing
nothing; `remove` deletes the value and its bookkeeping. See specs/functional/api-keys.spec.md,
"A secret stored under any name".
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from click.testing import Result
from typer.testing import CliRunner

from docket.governance import audit as _audit
from docket.governance import secrets as _secrets
from docket.interfaces.cli.app import app
from docket.interfaces.cli.commands import contract as _contract
from docket.kernel.home import current_home, use_home

SUBJECT = "docket.interfaces.cli.commands.setup_secret"

_VALUE = "tok-7f3a91c2e84b4d0aa51e"

_runner = CliRunner()


@pytest.fixture(autouse=True)
def _hermetic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.delenv("DOCKET_SECRETS_BACKEND", raising=False)
    home = tmp_path / "home"
    with use_home(dataclasses.replace(current_home(), root=home)):
        yield


def _secret(*args: str, stdin: str | None = None) -> Result:
    return _runner.invoke(app, ["setup", "secret", *args], input=stdin)


def _audit_text() -> str:
    return repr(_audit.read_audit())


def _everywhere(result: Result) -> str:
    return result.stdout + result.stderr + _audit_text()


class TestSet:
    def test_a_piped_value_is_stored_and_resolves(self) -> None:
        result = _secret("set", "svc-token", "--stdin", stdin=_VALUE + "\n")
        assert result.exit_code == 0, result.output
        assert _secrets.secret_value("svc-token") == _VALUE

    def test_the_value_reaches_no_output_and_no_audit_entry(self) -> None:
        result = _secret("set", "svc-token", "--stdin", stdin=_VALUE + "\n")
        assert result.exit_code == 0, result.output
        assert _VALUE not in _everywhere(result)
        actions = [e["action"] for e in _audit.read_audit()]
        assert "keys.add" in actions

    def test_a_second_set_of_the_same_name_is_audited_as_a_rotation(self) -> None:
        _secret("set", "svc-token", "--stdin", stdin="first-value-1234567890\n")
        result = _secret("set", "svc-token", "--stdin", stdin=_VALUE + "\n")
        assert result.exit_code == 0, result.output
        assert _secrets.secret_value("svc-token") == _VALUE
        assert "keys.rotate" in [e["action"] for e in _audit.read_audit()]

    def test_a_value_given_as_an_argument_exits_2_and_writes_nothing(self) -> None:
        result = _secret("set", "svc-token", _VALUE)
        assert result.exit_code == 2
        assert _VALUE not in _everywhere(result)
        assert _secrets.load_secrets() == {}
        assert not current_home().secrets_file.exists()

    def test_off_a_terminal_without_stdin_exits_1_naming_the_flag(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(_contract, "is_tty", lambda: False)
        result = _secret("set", "svc-token")
        assert result.exit_code == 1
        assert "--stdin" in result.stdout + result.stderr
        assert _secrets.load_secrets() == {}

    def test_an_empty_value_exits_1_and_writes_nothing(self) -> None:
        result = _secret("set", "svc-token", "--stdin", stdin="  \n")
        assert result.exit_code == 1
        assert _secrets.load_secrets() == {}

    def test_a_name_that_is_not_a_name_exits_1_without_repeating_it(self) -> None:
        result = _secret("set", _VALUE + " extra!", "--stdin", stdin="x\n")
        assert result.exit_code == 1
        assert _VALUE not in _everywhere(result)
        assert _secrets.load_secrets() == {}

    def test_a_terminal_gets_a_hidden_prompt(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_contract, "is_tty", lambda: True)
        result = _secret("set", "svc-token", stdin=_VALUE + "\n")
        assert result.exit_code == 0, result.output
        assert _secrets.secret_value("svc-token") == _VALUE
        assert _VALUE not in _everywhere(result)


class TestListAndRemove:
    def test_list_shows_the_name_and_not_the_value(self) -> None:
        _secret("set", "svc-token", "--stdin", stdin=_VALUE + "\n")
        result = _secret("list")
        assert result.exit_code == 0, result.output
        assert "svc-token" in result.stdout
        assert _VALUE not in result.stdout + result.stderr

    def test_list_json_is_names_and_dates_only(self) -> None:
        _secret("set", "svc-token", "--stdin", stdin=_VALUE + "\n")
        result = _secret("list", "--json")
        assert result.exit_code == 0, result.output
        rows = json.loads(result.stdout)
        assert [r["name"] for r in rows] == ["svc-token"]
        assert set(rows[0]) == {"name", "added_at", "rotated_at"}
        assert _VALUE not in result.stdout + result.stderr

    def test_list_with_nothing_stored_exits_0(self) -> None:
        result = _secret("list")
        assert result.exit_code == 0, result.output

    def test_remove_deletes_the_value_and_is_audited_by_name(self) -> None:
        _secret("set", "svc-token", "--stdin", stdin=_VALUE + "\n")
        result = _secret("remove", "svc-token")
        assert result.exit_code == 0, result.output
        assert _secrets.secret_value("svc-token") is None
        assert "svc-token" not in _secrets.load_secrets_meta()
        assert "keys.remove" in [e["action"] for e in _audit.read_audit()]
        assert _VALUE not in _everywhere(result)

    def test_remove_of_a_name_not_stored_exits_1(self) -> None:
        assert _secret("remove", "absent").exit_code == 1
