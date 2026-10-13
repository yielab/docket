"""README front-door contract.

The README is the repository's front door for a reader who knows nothing about docket: what it is
in plain words, the five ideas behind it, install, a four-step quick start, how the team becomes
files, the limits that matter, and where each guide lives. Detail belongs to `docs/`, persuasion to
the website. Every rule here answers to the current README.
"""

from __future__ import annotations

import re
from pathlib import Path

LANE = "truth"
REASON = "Keeps the README a short front door told in a newcomer's order (what it is, how it works, install, quick start, make it yours, limits, documentation), keeps reference detail in docs/ rather than the README, and rejects self-descriptions the ADRs reject and dollar-savings claims."
RETIRE_WHEN = "the README front door is generated from a single source of truth instead of hand-maintained prose."

_REPO = Path(__file__).parent.parent.parent.parent
README = _REPO / "README.md"
DOCS_INDEX = _REPO / "docs" / "README.md"

FRONT_DOOR_HEADINGS = (
    "## How it works",
    "## Install",
    "## Quick start",
    "## Make the team yours",
    "## Known limits",
    "## Documentation",
    "## Contributing",
    "## License",
)
CONCEPTS = ("**Pod.**", "**Role.**", "**Pipeline.**", "**Policy.**", "**Recipe.**")
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
# Frames the front door must not re-grow: each one is a docs guide's job.
STACKED_FRAMES = ("## Features", "## Core guarantees", "## Command reference", "## What's next")
STACKED_FRAMES += ("## Also shipped", "## Everything is configuration")


def _readme() -> str:
    return README.read_text(encoding="utf-8")


def _sections(text: str) -> list[tuple[str, str]]:
    """Return (heading, body) for every H2, in document order."""
    parts = re.split(r"^(## .+)$", text, flags=re.MULTILINE)
    return [(parts[i].strip(), parts[i + 1]) for i in range(1, len(parts) - 1, 2)]


class TestFrontDoor:
    def test_sections_follow_the_newcomer_order(self) -> None:
        headings = tuple(heading for heading, _ in _sections(_readme()))
        assert headings == FRONT_DOOR_HEADINGS, headings

    def test_the_intro_says_what_it_does_in_plain_words(self) -> None:
        intro = re.split(r"^## ", _readme(), maxsplit=1, flags=re.MULTILINE)[0]
        for phrase in ("Lead", "Implementer", "`git push origin production`", "tamper-evident"):
            assert phrase in intro, f"the intro must show what docket does: missing {phrase!r}"
        for target in ("docs/README.md", "docs/QUICK-START-DOCKET.md"):
            assert f"]({target})" in intro, f"the intro must link {target}"

    def test_how_it_works_names_the_five_ideas_and_the_daily_loop(self) -> None:
        body = dict(_sections(_readme()))["## How it works"]
        assert "hero.gif" in body
        missing = [concept for concept in CONCEPTS if concept not in body]
        assert missing == [], f"How it works must define {missing}"
        missing = [command for command in LOOP_COMMANDS if command not in body]
        assert missing == [], f"How it works must walk the daily loop; missing {missing}"

    def test_the_pod_is_defined_before_the_first_pod_command(self) -> None:
        text = _readme()
        assert 0 <= text.find(POD_DEFINITION) < text.index("`docket pod ")

    def test_quick_start_registers_a_model_before_creating_the_team(self) -> None:
        body = dict(_sections(_readme()))["## Quick start"]
        order = ("docket setup\n", "docket init ", "docket init --recipe", "docket task add")
        order += ("docket run\n",)
        positions = [body.find(step) for step in order]
        assert -1 not in positions and positions == sorted(positions), positions

    def test_make_the_team_yours_shows_the_files_and_the_loop(self) -> None:
        body = dict(_sections(_readme()))["## Make the team yours"]
        for kind in ("kind: pod", "kind: role", "kind: pipeline", "kind: policy"):
            assert kind in body, f"Make the team yours must name {kind}"
        for verb in ("export", "validate", "plan", "update"):
            command = f"docket pod {verb}"
            assert f"`{command}" in body or f"{command}\n" in body, f"missing {command}"

    def test_known_limits_are_short_here_and_complete_in_the_docs(self) -> None:
        body = dict(_sections(_readme()))["## Known limits"]
        assert "](docs/README.md#known-limits)" in body
        assert "## Known limits" in DOCS_INDEX.read_text(encoding="utf-8")

    def test_reference_detail_lives_in_the_docs(self) -> None:
        text = _readme()
        assert "```yaml" not in text, "configuration examples belong to docs/CONFIGURATION.md"
        assert "*Limit:*" not in text, "per-capability limits belong to docs/README.md#known-limits"


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
        assert present == [], f"README re-grew a frame a docs guide owns: {present}"

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
