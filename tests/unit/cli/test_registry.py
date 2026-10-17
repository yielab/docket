"""The command registry: a retired command is an ordinary unknown command."""

from __future__ import annotations

from typer.testing import CliRunner

from docket.cli import app

SUBJECT = "docket.cli"

_runner = CliRunner()


def test_exec_is_an_unknown_command() -> None:
    """The retired `exec` word exits 2 as an unknown command and the error carries no suggestion."""
    result = _runner.invoke(app, ["exec"])
    text = " ".join(result.output.replace("│", " ").split())

    assert result.exit_code == 2
    assert "No such command" in text
    assert "Did you mean" not in text
    assert "docket task" not in text
    assert "docket run" not in text
