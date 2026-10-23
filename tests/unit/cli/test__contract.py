"""The interaction contract: confirm, emit_json, next_step."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import typer

from docket.cli import _contract
from docket.cli._target import TargetError

SUBJECT = "docket.cli._contract"


@pytest.fixture
def no_tty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_contract, "_is_tty", lambda: False)


def test_confirm_off_tty_refuses_naming_yes(
    no_tty: None, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(typer.Exit) as exc:
        _contract.confirm("delete pod x", yes=False)
    assert exc.value.exit_code == 1
    assert "--yes" in capsys.readouterr().err


def test_confirm_off_tty_with_typed_name_names_the_confirm_flag(
    no_tty: None, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(typer.Exit) as exc:
        _contract.confirm("delete pod x", yes=False, typed="x")
    assert exc.value.exit_code == 1
    assert "--confirm x" in capsys.readouterr().err


def test_confirm_with_yes_returns_without_prompting(no_tty: None) -> None:
    assert _contract.confirm("delete pod x", yes=True) is True


def test_confirm_on_tty_reads_the_typed_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_contract, "_is_tty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _prompt="": "x")
    assert _contract.confirm("delete pod x", yes=False, typed="x") is True
    monkeypatch.setattr("builtins.input", lambda _prompt="": "y")
    assert _contract.confirm("delete pod x", yes=False, typed="x") is False


def test_emit_json_is_plain_json(capsys: pytest.CaptureFixture[str]) -> None:
    _contract.emit_json({"a": [1, 2], "b": "x"})
    assert json.loads(capsys.readouterr().out) == {"a": [1, 2], "b": "x"}


def test_next_step_prints_one_line_on_stderr_unless_silenced(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("DOCKET_NO_HINTS", raising=False)
    _contract.next_step("docket status")
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.strip().endswith("Next: docket status")
    assert len(captured.err.strip().splitlines()) == 1
    monkeypatch.setenv("DOCKET_NO_HINTS", "1")
    _contract.next_step("docket status")
    assert capsys.readouterr().err == ""


def test_resolve_pod_here_reads_the_process_environment_and_cwd(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DOCKET_POD", raising=False)
    assert _contract.resolve_pod_here("explicit") == "explicit"
    monkeypatch.setenv("DOCKET_POD", " from-env ")
    assert _contract.resolve_pod_here(None) == "from-env"
    monkeypatch.delenv("DOCKET_POD")
    with pytest.raises(TargetError):
        _contract.resolve_pod_here(None)
