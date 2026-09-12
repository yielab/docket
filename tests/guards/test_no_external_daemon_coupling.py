"""Acceptance guard: product code contains no retired-daemon coupling.

Phase 19 was a clean break, not a compatibility layer. Keeping even prose references under
``src/docket`` makes later contributors infer that the old runtime still owns a boundary. The
durable migration history belongs in ROADMAP/CHANGELOG/spec changelogs instead.
"""

from __future__ import annotations

from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "docket"
_RETIRED_BRAND = "open" + "claw"


def test_product_code_has_no_retired_daemon_reference() -> None:
    offenders = [
        str(path.relative_to(SRC))
        for path in sorted(SRC.rglob("*.py"))
        if _RETIRED_BRAND in path.read_text(encoding="utf-8").lower()
    ]
    assert offenders == [], (
        "Retired-daemon reference(s) found in product code; keep migration history in durable "
        "planning/changelog documents instead:\n" + "\n".join(offenders)
    )
