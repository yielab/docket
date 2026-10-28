"""``kernel.text`` -- each cut equals the inline expression it replaces, at and around the limit."""

from __future__ import annotations

from docket.kernel.text import cut_chars, cut_output, ellipsize, normalize_output, one_line

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


def test_cut_output_with_a_tail_keeps_the_end_after_the_marker() -> None:
    text = "".join(str(n % 10) for n in range(100))

    cut = cut_output(text, 10, tail=0.6)

    assert cut == f"{text[:4]}\n\n[truncated: 90 more characters]\n\n{text[-6:]}"


def test_cut_output_with_a_tail_that_rounds_to_nothing_keeps_the_head() -> None:
    assert cut_output("abcdef", 4, tail=0.1) == "abcd\n\n[truncated: 2 more characters]"


def test_normalize_strips_ansi_colour_and_cursor_sequences() -> None:
    raw = "\x1b[31mFAILED\x1b[0m test\n\x1b[2K\x1b]0;title\x07done"

    assert normalize_output(raw) == "FAILED test\ndone"


def test_normalize_keeps_the_last_state_of_a_carriage_return_line() -> None:
    assert normalize_output("10%\r50%\r100%\nok") == "100%\nok"


def test_normalize_treats_crlf_as_an_ordinary_newline() -> None:
    assert normalize_output("a\r\nb\r\n") == "a\nb\n"


def test_normalize_collapses_a_run_of_identical_lines() -> None:
    raw = "\n".join(["start", *["retrying"] * 50, "end"])

    assert normalize_output(raw) == "start\nretrying  [x 50]\nend"


def test_normalize_collapses_a_run_at_the_end_and_leaves_blank_lines_alone() -> None:
    assert normalize_output("a\na\n\n\nb\nb") == "a  [x 2]\n\n\nb  [x 2]"


def test_normalize_leaves_distinct_text_byte_for_byte() -> None:
    raw = "line one\n  indented\ttab\nlast without newline"

    assert normalize_output(raw) == raw
