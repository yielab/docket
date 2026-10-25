"""README honesty contract.

The README is descriptive: its structure, section order and wording are not pinned. What stays
pinned is what it must never claim: a self-description the ADRs reject, "tamper-proof", docket as a
dashboard, or a forward dollar-savings promise.
"""

from __future__ import annotations

import re
from pathlib import Path

LANE = "truth"
REASON = "Rejects README self-descriptions the ADRs reject, tamper-proof audit claims, a dashboard positioning and dollar-savings claims; the README structure itself is not pinned."
RETIRE_WHEN = "the README is generated from a source that already enforces these claims."

_REPO = Path(__file__).parent.parent.parent.parent
README = _REPO / "README.md"

# Self-descriptions the ADRs reject: "fleet" implies a scale docket denies, "control plane"
# implies a dashboard docket refuses to build, "enterprise" a buyer the ADRs scope out, and
# "factory"/"substrate" are internal strategy words, not product ones.
FORBIDDEN_SELF_DESCRIPTIONS = (
    r"\bfleet\b",
    r"\benterprise\b",
    r"\bcontrol plane\b",
    r"\bfactory\b",
    r"\bsubstrate\b",
    r"\bcost optimi[sz]ation\b",
)


def _readme() -> str:
    return README.read_text(encoding="utf-8")


class TestOneVoice:
    def test_no_rejected_self_description(self) -> None:
        text = _readme()
        hits = [p for p in FORBIDDEN_SELF_DESCRIPTIONS if re.search(p, text, flags=re.IGNORECASE)]
        assert hits == [], f"README uses a self-description the ADRs reject: {hits}"

    def test_tamper_proof_appears_only_negated(self) -> None:
        for match in re.finditer(r"tamper-proof", _readme(), flags=re.IGNORECASE):
            preceding = _readme()[max(0, match.start() - 4) : match.start()]
            assert preceding.endswith("not "), (
                "audit evidence is tamper-evident, never tamper-proof"
            )

    def test_dashboard_is_fed_not_shipped(self) -> None:
        text = re.sub(r"\s+", " ", _readme().lower())
        assert "does not ship one" in text
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
