"""Architecture: no module under src/docket is longer than 700 lines (ADR 0030).

A module over the ceiling is a defect, not a style note: it is the shape ``core/dispatch.py``
had (4,727 lines, touched by one commit in five). The ceiling is the ADR's number and nothing is
exempt; split the module by context before it crosses, do not raise the number.
"""

from __future__ import annotations

from pathlib import Path

SUBJECT = "docket"

SRC = Path(__file__).resolve().parents[2] / "src" / "docket"
CEILING = 700


def _line_counts() -> dict[str, int]:
    return {
        path.relative_to(SRC.parent).as_posix(): len(path.read_text(encoding="utf-8").splitlines())
        for path in sorted(SRC.rglob("*.py"))
    }


def test_no_module_is_over_the_ceiling() -> None:
    over = {rel: n for rel, n in _line_counts().items() if n > CEILING}
    assert not over, f"modules over {CEILING} lines, split them by context: {over}"


def test_the_scan_sees_the_tree() -> None:
    # A path typo would make the ratchet vacuous.
    counts = _line_counts()
    assert len(counts) > 100
    assert "docket/kernel/home.py" in counts
