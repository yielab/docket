"""Every note's closing keyword appears, in order, in keywords.md: the turn read all forty files."""

import os
import re
from pathlib import Path

REPO = Path(os.environ["EVAL_REPO"])


def _expected() -> list[str]:
    lines = []
    for path in sorted((REPO / "docs").glob("note-*.md")):
        match = re.search(r"^Keyword: (\S+)$", path.read_text(encoding="utf-8"), re.MULTILINE)
        assert match, f"{path.name} lost its keyword line"
        lines.append(f"{path.name}: {match.group(1)}")
    return lines


def test_forty_notes_are_still_there() -> None:
    assert len(_expected()) == 40


def test_keywords_file_holds_one_line_per_note_in_order() -> None:
    written = (REPO / "keywords.md").read_text(encoding="utf-8")
    lines = [line.strip() for line in written.splitlines() if line.strip()]
    assert lines == _expected()
