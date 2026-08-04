"""Enforce the store.py single-writer rule (D-12).

store.py's docstring claims ALL docket-owned JSON writes go through
``edges.store.write_json``. This is a machine-checked guard against
regression: any hand-rolled ``path.write_text(json.dumps(...))`` atomic-write
dance outside the chokepoint (and its two documented JSONL-append exemptions,
``core/trace.py`` / ``core/audit.py``) reintroduces the bug D-12 fixed —
writers that skip the filelock and ``.bak`` rotation and can corrupt a
docket-owned JSON file under concurrent access.
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO = Path(__file__).parent.parent.parent
_SRC = _REPO / "src" / "docket"

# Modules allowed to write JSON outside the edges/store.py chokepoint.
_EXEMPT = {
    _SRC / "edges" / "store.py",  # the chokepoint itself
    _SRC / "core" / "trace.py",  # append-only JSONL (D-12 exemption)
    _SRC / "core" / "audit.py",  # append-only JSONL (D-12 exemption)
}

# A write_text( call whose argument (within a generous window, to tolerate a
# multi-line call) contains json.dumps — the hand-rolled atomic-write pattern
# store.write_json replaced.
_WRITE_TEXT = re.compile(r"write_text\s*\(")
_WINDOW = 200


def _find_offenders() -> list[str]:
    offenders: list[str] = []
    for path in sorted(_SRC.rglob("*.py")):
        if path in _EXEMPT:
            continue
        text = path.read_text(encoding="utf-8")
        for m in _WRITE_TEXT.finditer(text):
            window = text[m.start() : m.start() + _WINDOW]
            if "json.dumps" in window:
                line_no = text.count("\n", 0, m.start()) + 1
                rel = path.relative_to(_REPO)
                offenders.append(f"{rel}:{line_no}")
    return offenders


def test_no_hand_rolled_json_writes_outside_store() -> None:
    offenders = _find_offenders()
    assert offenders == [], (
        "Docket-owned JSON writes must go through edges/store.py:write_json "
        "(D-12 single-writer rule). Hand-rolled write_text(json.dumps(...)) "
        "found outside the chokepoint and its append-only-JSONL exemptions "
        "(core/trace.py, core/audit.py):\n" + "\n".join(f"  {o}" for o in offenders)
    )


def test_exempt_modules_still_exist() -> None:
    """Sanity check the exclusion list doesn't silently rot: every module in
    _EXEMPT should still be a real file, not a dead entry left behind after
    the module it named was deleted."""
    always_present = {
        _SRC / "edges" / "store.py",
        _SRC / "core" / "trace.py",
        _SRC / "core" / "audit.py",
    }
    for path in always_present:
        assert path.is_file(), f"expected exempt module missing: {path}"
