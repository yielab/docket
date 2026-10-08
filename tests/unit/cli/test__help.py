"""The root group: panels, `-h`, the bare guide and the unknown-word usage error."""

from __future__ import annotations

from typer.testing import CliRunner

from docket import ui
from docket.cli import app

SUBJECT = "docket.cli._help"

_runner = CliRunner()


def _error_text(argv: list[str]) -> str:
    result = _runner.invoke(app, argv)
    assert result.exit_code == 2
    return " ".join(result.output.replace("│", " ").split())


def test_a_word_that_is_a_verb_of_two_groups_names_both() -> None:
    text = _error_text(["add", "x"])

    assert "docket task add" in text
    assert "docket pod add" in text


def test_a_group_verb_points_at_its_group() -> None:
    assert "docket task approve" in _error_text(["approve", "task-1"])
    assert "docket task list" in _error_text(["list"])
    show = _error_text(["show"])
    assert "docket pod show" in show and "docket task show" in show


def test_a_near_miss_offers_the_live_command() -> None:
    assert "docket status" in _error_text(["statu"])


def test_an_unrelated_word_is_a_plain_usage_error() -> None:
    for word in ("dispatch", "delegate"):
        text = _error_text([word, "x"])
        assert "No such command" in text
        assert "Did you mean" not in text
        assert "docket --help" in text


def test_short_help_matches_long_help_at_every_level() -> None:
    assert _runner.invoke(app, ["-h"]).output == _runner.invoke(app, ["--help"]).output
    short = _runner.invoke(app, ["task", "show", "-h"])
    assert short.exit_code == 0
    assert short.output.count("Example:") == 1


def test_help_shows_the_three_panels_and_the_tagline() -> None:
    out = _runner.invoke(app, ["--help"]).output

    assert ui.TAGLINE in out
    for panel in ("Daily", "The pod", "Machine"):
        assert panel in out
    assert out.index("Daily") < out.index("The pod") < out.index("Machine")


def test_the_bare_command_prints_the_tagline_the_daily_commands_and_the_setup_pointer() -> None:
    result = _runner.invoke(app, [])

    assert result.exit_code == 0
    lines = [line.strip() for line in result.output.splitlines() if line.strip()]
    assert lines[0] == ui.TAGLINE
    for command in ("docket init", 'docket task add "..."', "docket run", "docket status"):
        assert any(line.startswith(command) for line in lines)
    assert any(line.startswith("docket inbox") for line in lines)
    assert lines[-1] == "Not set up yet? docket setup"
