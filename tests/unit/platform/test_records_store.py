"""Value checks and Markdown rendering of the records store (`platform/records_store.py`)."""

from __future__ import annotations

import pytest

from docket.platform.records_store import Column, RecordsError, check_value, render_markdown

SUBJECT = "docket.platform.records_store"


@pytest.mark.parametrize(
    ("kind", "value"),
    [
        ("string", "x"),
        ("integer", 3),
        ("number", 3),
        ("number", 2.5),
        ("boolean", False),
        ("date", "2026-10-30"),
    ],
)
def test_a_value_of_the_column_type_is_accepted(kind: str, value: object) -> None:
    assert check_value(Column("c", kind), value) == value


@pytest.mark.parametrize(
    ("kind", "value"),
    [
        ("string", 3),
        ("integer", "abc"),
        ("integer", 2.5),
        ("integer", True),
        ("number", True),
        ("number", "1"),
        ("boolean", 1),
        ("date", "2026-13-01"),
        ("date", "30/10/2026"),
        ("date", 20261030),
    ],
)
def test_a_value_of_another_type_is_refused_naming_the_column(kind: str, value: object) -> None:
    with pytest.raises(RecordsError, match="'c'"):
        check_value(Column("c", kind), value)


def test_null_is_accepted_for_every_type() -> None:
    assert check_value(Column("c", "integer"), None) is None


def test_markdown_escapes_pipes_and_newlines_and_shows_null_as_empty() -> None:
    out = render_markdown(["a", "b"], [("x|y", "l1\nl2"), (None, 3)])
    assert out == "| a | b |\n| --- | --- |\n| x\\|y | l1 l2 |\n|  | 3 |\n"
