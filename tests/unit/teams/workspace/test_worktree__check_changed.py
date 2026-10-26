"""The pieces of the changed-check park: commands that count as checks, results, group failures."""

from __future__ import annotations

import pytest

from docket.teams.workspace import worktree as _worktree

SUBJECT = "docket.teams.workspace.worktree"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("short", "short"),
        ("x" * 72, "x" * 72),
        ("word " * 20, ("word " * 14).rstrip()),
        ("a" * 80, "a" * 72),
        (("b" * 71) + " tail words", "b" * 71),
        (("c" * 60) + " " + ("d" * 40), "c" * 60),
    ],
)
def test_a_commit_subject_is_cut_at_a_word_boundary(text: str, expected: str) -> None:
    assert _worktree._cut_at_word(text, 72) == expected
