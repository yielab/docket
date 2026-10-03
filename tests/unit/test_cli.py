"""The Typer application's root callback: bare `docket` and `--version`."""

from typer.testing import CliRunner

from docket.cli import app

SUBJECT = "docket.cli"


def test_bare_invocation_prints_the_quick_reference() -> None:
    result = CliRunner().invoke(app, [])
    assert result.exit_code == 0
    assert "docket init" in result.stdout
    assert "docket help" in result.stdout


def test_version_flag_prints_the_version_and_exits_0() -> None:
    result = CliRunner().invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.stdout.startswith("docket ")


def test_an_unknown_global_flag_is_a_usage_error() -> None:
    result = CliRunner().invoke(app, ["--debug"])
    assert result.exit_code == 2
