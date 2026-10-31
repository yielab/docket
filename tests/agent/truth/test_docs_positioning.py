"""README honesty contract.

The README is descriptive: its structure, section order, vocabulary and voice are not pinned. What
stays pinned is only what would be a false statement about the product: "tamper-proof" audit,
docket as a dashboard, or a forward dollar-savings promise.
"""

from __future__ import annotations

import re
from pathlib import Path

LANE = "truth"
REASON = "Rejects README claims that would be false about the product (tamper-proof audit, a docket dashboard, forward dollar savings); structure, vocabulary and voice are not pinned."
RETIRE_WHEN = "the README is generated from a source that already enforces these claims."

_REPO = Path(__file__).parent.parent.parent.parent
README = _REPO / "README.md"


def _readme() -> str:
    return README.read_text(encoding="utf-8")


class TestNoFalseClaims:
    def test_tamper_proof_appears_only_negated(self) -> None:
        for match in re.finditer(r"tamper-proof", _readme(), flags=re.IGNORECASE):
            preceding = _readme()[max(0, match.start() - 4) : match.start()]
            assert preceding.endswith("not "), (
                "audit evidence is tamper-evident, never tamper-proof"
            )

    def test_docket_is_not_presented_as_a_dashboard(self) -> None:
        text = re.sub(r"\s+", " ", _readme().lower())
        for phrase in ("docket dashboard", "the docket ui", "docket's dashboard"):
            assert phrase not in text, f"README must not position docket as a dashboard: {phrase!r}"


class TestNoDollarSavingsClaims:
    """A forward dollar-savings claim is unfalsifiable here: tokens are measured, dollars estimated."""

    _FORWARD_CLAIMS = (
        "save you",
        "saves you",
        "will save",
        "can save",
        "reduces your costs",
        "cut your costs",
    )

    def _check(self, text: str, label: str) -> None:
        bad = [
            (n, line)
            for n, line in enumerate(text.splitlines(), start=1)
            if not line.strip().startswith("#")
            and any(phrase in line.lower() for phrase in self._FORWARD_CLAIMS)
        ]
        assert bad == [], f"{label}: dollar-savings claim(s):\n" + "\n".join(
            f"  line {n}: {line}" for n, line in bad
        )

    def test_readme(self) -> None:
        self._check(_readme(), "README.md")
