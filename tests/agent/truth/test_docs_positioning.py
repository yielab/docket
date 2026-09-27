"""README front-door contract.

The README carries one pitch and three heroes -- the team you define, the run, the gate and the
record -- each showing
its captured asset, naming its limit beside the capability, and ending claims in the command that
proves them. Every rule here answers to the current README, not to a prior shape of it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

LANE = "truth"
REASON = "Keeps the README on one pitch: three hero sections first and in order, each with its asset, its limit and its proving commands; no self-description the ADRs reject, no stacked feature frames, no dollar-savings claim."
RETIRE_WHEN = "the README front door is generated from a single source of truth instead of hand-maintained prose."

_REPO = Path(__file__).parent.parent.parent.parent
README = _REPO / "README.md"
CLAUDE_MD = _REPO / "CLAUDE.md"

HERO_HEADINGS = ("## The team you define", "## The run", "## The gate and the record")
HERO_ASSETS = {
    "## The team you define": "hero.gif",
    "## The run": "isolation.png",
    "## The gate and the record": "governance.png",
}
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
# Frames the front door must not re-grow: a feature list or a guarantee list beside the heroes.
STACKED_FRAMES = ("## Features", "## Core guarantees", "## Command reference", "## What's next")


def _readme() -> str:
    return README.read_text(encoding="utf-8")


def _sections(text: str) -> list[tuple[str, str]]:
    """Return (heading, body) for every H2, in document order."""
    parts = re.split(r"^(## .+)$", text, flags=re.MULTILINE)
    return [(parts[i].strip(), parts[i + 1]) for i in range(1, len(parts) - 1, 2)]


class TestThreeHeroes:
    def test_heroes_open_the_readme_in_order_then_the_quick_start(self) -> None:
        headings = [heading for heading, _ in _sections(_readme())]
        assert tuple(headings[:3]) == HERO_HEADINGS, headings[:4]
        assert headings[3] == "## Quick start", headings[:4]

    def test_each_hero_shows_its_captured_asset(self) -> None:
        bodies = dict(_sections(_readme()))
        for heading, asset in HERO_ASSETS.items():
            assert asset in bodies[heading], f"{heading} must show docs/assets/{asset}"

    def test_each_hero_names_its_limit_beside_the_capability(self) -> None:
        bodies = dict(_sections(_readme()))
        for heading in HERO_HEADINGS:
            assert re.search(r"\*Limit:\*", bodies[heading]), (
                f"{heading} must state its limit in the same section, not in an appendix"
            )

    def test_the_first_hero_shows_the_files_not_a_list(self) -> None:
        body = dict(_sections(_readme()))["## The team you define"]
        for kind in ("kind: role", "kind: pipeline", "kind: pod", "kind: policy"):
            assert kind in body, f"the first hero must show a {kind} document"

    def test_each_hero_ends_claims_in_commands(self) -> None:
        bodies = dict(_sections(_readme()))
        for heading in HERO_HEADINGS:
            commands = re.findall(r"`docket [a-z]", bodies[heading])
            assert len(commands) >= 2, f"{heading} must name the commands that prove it"


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

    def test_no_stacked_feature_frames(self) -> None:
        text = _readme()
        present = [frame for frame in STACKED_FRAMES if frame in text]
        assert present == [], f"README re-grew a shed frame: {present}"

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

    def test_claude_md(self) -> None:
        if not CLAUDE_MD.exists():
            pytest.skip("CLAUDE.md is not committed to this repo")
        self._check(CLAUDE_MD.read_text(encoding="utf-8"), "CLAUDE.md")
