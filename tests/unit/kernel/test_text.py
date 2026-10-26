"""``kernel.text`` -- each cut equals the inline expression it replaces, at and around the limit."""

from __future__ import annotations

from docket.kernel.text import cut_chars, cut_output, ellipsize, one_line

SUBJECT = "docket.kernel.text"


def test_one_line_collapses_every_kind_of_whitespace() -> None:
    assert one_line("  a\n\n b\t c  ") == "a b c"
    assert one_line("") == ""


def test_ellipsize_keeps_text_that_fits() -> None:
    assert ellipsize("abc", 3) == "abc"


def test_ellipsize_result_is_exactly_the_limit() -> None:
    cut = ellipsize("abcdef", 4)
    assert cut == "abc…"
    assert len(cut) == 4


def test_ellipsize_with_an_ascii_marker() -> None:
    assert ellipsize("abcdefgh", 6, "...") == "abc..."


def test_ellipsize_never_slices_from_the_end_on_a_tiny_limit() -> None:
    assert ellipsize("abcdef", 0) == "…"
    assert ellipsize("abcdef", 1) == "…"


def test_cut_chars_names_how_many_chars_were_cut() -> None:
    assert cut_chars("abcdef", 4) == "abcd…[truncated 2 chars]"


def test_cut_chars_at_the_limit_is_untouched() -> None:
    assert cut_chars("abcd", 4) == "abcd"


def test_cut_chars_with_a_limit_of_zero_or_less_is_unbounded() -> None:
    assert cut_chars("abcdef", 0) == "abcdef"
    assert cut_chars("abcdef", -1) == "abcdef"


def test_cut_output_adds_a_paragraph_naming_what_was_dropped() -> None:
    assert cut_output("abcdef", 4) == "abcd\n\n[truncated: 2 more characters]"


def test_cut_output_at_the_limit_is_untouched() -> None:
    assert cut_output("abcd", 4) == "abcd"


def test_cuts_count_characters_not_bytes() -> None:
    assert cut_chars("ñññññ", 3) == "ñññ…[truncated 2 chars]"
