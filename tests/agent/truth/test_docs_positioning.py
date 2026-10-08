"""README front-door contract.

The README follows the newcomer's path: install, a first team from defaults or a recipe, what a
dispatch does, what gates and records it, and only then how to change the team and the map of every
layer. Each capability section shows its captured asset, names its limit beside the capability, and
ends claims in the command that proves them. Every rule here answers to the current README.
"""

from __future__ import annotations

import re
from pathlib import Path

LANE = "truth"
REASON = "Keeps the README on one pitch told in the order a newcomer uses docket: the daily loop in the intro, install, a first team, the run, the gate and record, then configuration; each capability section with its asset, its limit and its proving commands; no self-description the ADRs reject, no stacked feature frames, no dollar-savings claim."
RETIRE_WHEN = "the README front door is generated from a single source of truth instead of hand-maintained prose."

_REPO = Path(__file__).parent.parent.parent.parent
README = _REPO / "README.md"

PATH_HEADINGS = (
    "## Quick start",
    "## Your first team",
    "## The run",
    "## The gate and the record",
    "## Make it yours",
    "## Everything is configuration",
)
CAPABILITY_ASSETS = {
    "## Your first team": "hero.gif",
    "## The run": "isolation.png",
    "## The gate and the record": "governance.png",
}
LIMITED_SECTIONS = ("## The run", "## The gate and the record", "## Make it yours")
LOOP_COMMANDS = ("`init`", "`task add`", "`run`", "`status`", "`inbox`", "`task approve`")
POD_DEFINITION = "A **pod** is the team of agents attached to one repository"
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


class TestNewcomerPath:
    def test_the_intro_names_the_daily_loop(self) -> None:
        intro = re.split(r"^## ", _readme(), maxsplit=1, flags=re.MULTILINE)[0]
        missing = [command for command in LOOP_COMMANDS if command not in intro]
        assert missing == [], f"the intro must walk the daily loop; missing {missing}"

    def test_sections_follow_the_path_from_install_to_configuration(self) -> None:
        headings = [heading for heading, _ in _sections(_readme())]
        assert tuple(headings[: len(PATH_HEADINGS)]) == PATH_HEADINGS, headings[:7]

    def test_the_first_team_starts_from_defaults_or_a_recipe(self) -> None:
        body = dict(_sections(_readme()))["## Your first team"]
        assert "`docket init`" in body and "`docket init --recipe" in body

    def test_each_capability_shows_its_captured_asset(self) -> None:
        bodies = dict(_sections(_readme()))
        for heading, asset in CAPABILITY_ASSETS.items():
            assert asset in bodies[heading], f"{heading} must show docs/assets/{asset}"

    def test_each_capability_names_its_limit_beside_it(self) -> None:
        bodies = dict(_sections(_readme()))
        for heading in LIMITED_SECTIONS:
            assert re.search(r"\*Limit:\*", bodies[heading]), (
                f"{heading} must state its limit in the same section, not in an appendix"
            )

    def test_make_it_yours_shows_the_files_not_a_list(self) -> None:
        body = dict(_sections(_readme()))["## Make it yours"]
        for kind in ("kind: role", "kind: pipeline", "kind: pod", "kind: policy"):
            assert kind in body, f"Make it yours must show a {kind} document"

    def test_quick_start_registers_a_model_with_setup_before_init(self) -> None:
        t = _readme()
        assert t.index("## Quick start") < t.index("docket setup\n") < t.index("docket init")

    def test_the_pod_is_defined_where_the_first_pod_command_appears(self) -> None:
        text = _readme()
        assert 0 <= text.find(POD_DEFINITION) < text.index("`docket pod ")

    def test_each_capability_ends_claims_in_commands(self) -> None:
        bodies = dict(_sections(_readme()))
        for heading in (*CAPABILITY_ASSETS, "## Make it yours"):
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
