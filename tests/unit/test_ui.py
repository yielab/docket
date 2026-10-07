"""The console voice: plain mode, error shape, tables that never cut a word."""

from __future__ import annotations

import io
import re

import pytest

from docket import ui

SUBJECT = "docket.ui"

_ESC = re.compile("\x1b")


def test_piped_success_is_plain_ascii_without_escape_codes(
    capsys: pytest.CaptureFixture[str],
) -> None:
    ui.success("pod created")
    out = capsys.readouterr().out
    assert out.strip() == "ok pod created"
    assert not _ESC.search(out)


def test_error_with_a_next_action_is_one_line_on_stderr(
    capsys: pytest.CaptureFixture[str],
) -> None:
    ui.error("pod x not found", "Run docket status")
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.strip() == "x pod x not found. Run docket status"


def test_no_color_forces_plain_even_on_a_tty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setattr("sys.stdout", type("T", (io.StringIO,), {"isatty": lambda s: True})())
    assert ui.is_plain()


def test_table_wraps_a_long_cell_and_every_word_survives(
    capsys: pytest.CaptureFixture[str],
) -> None:
    cell = "requires approval before every outbound network call"
    assert len(cell) > 40
    ui.table([["policy", cell]], ["name", "rule"], width=30)
    out = capsys.readouterr().out
    assert max(len(line) for line in out.splitlines()) <= 30
    assert set(cell.split()) <= set(out.split())
