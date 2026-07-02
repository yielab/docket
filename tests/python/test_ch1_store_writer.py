"""CH-1: Enforce the store.py single-writer rule (D-12).

store.py's docstring claims ALL docket-owned JSON writes go through
``edges.store.write_json``. This is a machine-checked guard against
regression: any hand-rolled ``path.write_text(json.dumps(...))`` atomic-write
dance outside the chokepoint (and its two documented JSONL-append exemptions,
``core/trace.py`` / ``core/audit.py``) reintroduces the bug D-12 fixed —
writers that skip the filelock and ``.bak`` rotation and can corrupt a
docket-owned JSON file under concurrent access.

``core/drift.py`` is a temporary, narrowly-scoped exclusion: CH-5 deletes the
whole module, so migrating its one write site would be wasted work. Remove
the exclusion when CH-5 lands (or sooner, if this test starts failing because
the file is already gone).
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
    _SRC / "core" / "drift.py",  # TEMP: whole module deleted by CH-5
}

# A write_text( call whose argument (within a generous window, to tolerate a
# multi-line call) contains json.dumps — the hand-rolled atomic-write pattern
# CH-1 replaced with store.write_json.
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


def test_exempt_modules_still_exist_or_are_expected_gone() -> None:
    """Sanity check the exclusion list doesn't silently rot.

    core/drift.py is expected to disappear once CH-5 lands — when it does,
    remove it from _EXEMPT here rather than leaving a dead entry.
    """
    always_present = {
        _SRC / "edges" / "store.py",
        _SRC / "core" / "trace.py",
        _SRC / "core" / "audit.py",
    }
    for path in always_present:
        assert path.is_file(), f"expected exempt module missing: {path}"
