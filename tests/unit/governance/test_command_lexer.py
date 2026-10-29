"""The shell lexer under the classifier: invocations, redirects, heredocs and wrappers."""

from __future__ import annotations

import pytest

from docket.governance.command_lexer import (
    cut_quoted_heredocs,
    split_segments,
    starts_background,
    unwrap,
)

SUBJECT = "docket.governance.command_lexer"


def test_a_separator_starts_a_new_invocation_and_a_pipe_marks_a_subshell() -> None:
    first, second, third = split_segments("ls -l | wc && echo done")

    assert [first.tokens, second.tokens, third.tokens] == [
        ["ls", "-l"],
        ["wc"],
        ["echo", "done"],
    ]
    assert (first.subshell, second.subshell, third.subshell) == (True, True, False)


def test_a_redirect_is_recorded_beside_the_invocation_it_belongs_to() -> None:
    (segment,) = split_segments("echo hi > out.txt")

    assert segment.redirected
    assert segment.targets == ("out.txt",)


def test_a_descriptor_copy_opens_no_file() -> None:
    (segment,) = split_segments("make 2>&1")

    assert not segment.redirected


def test_leading_assignments_are_not_the_program() -> None:
    (segment,) = split_segments("A=1 B=2 make test")

    assert segment.tokens == ["make", "test"]


def test_a_newline_outside_quotes_separates_commands() -> None:
    first, second = split_segments("ls\nrm x")

    assert (first.tokens, second.tokens) == (["ls"], ["rm", "x"])


def test_unbalanced_quotes_raise() -> None:
    with pytest.raises(ValueError):
        split_segments("echo 'oops")


def test_a_quoted_heredoc_fed_to_a_non_shell_is_cut_and_one_fed_to_a_shell_is_kept() -> None:
    cut, error = cut_quoted_heredocs("cat <<'EOF'\nrm -rf /\nEOF")
    kept, _ = cut_quoted_heredocs("sh <<'EOF'\nrm -rf /\nEOF")

    assert error is None
    assert "rm -rf" not in cut
    assert "rm -rf" in kept


def test_a_quoted_heredoc_with_no_closing_line_is_reported() -> None:
    _text, error = cut_quoted_heredocs("cat <<'EOF'\nbody")

    assert error is not None and "EOF" in error


@pytest.mark.parametrize(
    ("tokens", "inner"),
    [
        (["env", "FOO=1", "rm", "x"], ["rm", "x"]),
        (["timeout", "5", "rm", "x"], ["rm", "x"]),
        (["nice", "-n", "5", "xargs", "-0", "rm"], ["rm"]),
        (["rm", "x"], ["rm", "x"]),
    ],
)
def test_wrappers_are_peeled(tokens: list[str], inner: list[str]) -> None:
    assert unwrap(tokens) == inner


def test_wrappers_nested_too_deep_cannot_be_read() -> None:
    assert unwrap(["env"] * 12 + ["rm"]) is None


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("sleep 30 &", True),
        ("sleep 30 &\n\n", True),
        ("sleep 30 & echo hi", True),
        ("a && b", False),
        ("ls 2>&1", False),
        ("ls &> f", False),
        ("echo 'a &'", False),
        ("(sleep 3 &)", True),
    ],
)
def test_only_a_lone_ampersand_starts_a_background_child(command: str, expected: bool) -> None:
    """A lone `&` anywhere starts one; `&&`, `2>&1`, `&>` and a quoted `&` do not."""
    assert starts_background(command) is expected
