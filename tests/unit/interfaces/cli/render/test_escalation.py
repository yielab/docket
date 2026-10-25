"""The terminal's lines for an escalation's options and the command that answers it."""

from __future__ import annotations

from docket.interfaces.cli.render import escalation as _escalation
from docket.operator import RenderedOption

SUBJECT = "docket.interfaces.cli.render.escalation"

_OPTIONS = (
    RenderedOption("redis", "Redis", False),
    RenderedOption("sqlite", "SQLite", True),
)


def test_options_line_names_each_option_and_marks_the_recommended_one() -> None:
    assert _escalation.options_line(_OPTIONS) == "redis (Redis), sqlite (SQLite) (recommended)"


def test_the_answer_command_names_the_recommended_option() -> None:
    assert (
        _escalation.answer_command("task-1", _OPTIONS)
        == "docket task answer task-1 --option sqlite"
    )


def test_without_a_recommendation_it_names_the_first_option() -> None:
    plain = (RenderedOption("a", "", False), RenderedOption("b", "", False))

    assert _escalation.answer_command("task-1", plain) == "docket task answer task-1 --option a"


def test_a_pause_with_no_options_is_answered_by_text() -> None:
    assert _escalation.answer_command("task-1", ()) == "docket task answer task-1"
