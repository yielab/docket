"""Agent identity: Docket-owned persona + quarantine of foreign scaffolding.

Guards the congruence fix (agent-structure-analysis.md §6): identity is a pure
function of docket metadata (persona → name → role), rendered into SOUL.md; the
self-authored IDENTITY.md/BOOTSTRAP.md files are pollution to be quarantined.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import docket.config as _cfg
from docket.core import identity as I
from docket.core.models import AgentMeta, Persona

SUBJECT = "docket.core.identity"


class TestPersonaModel:
    def test_label_name_and_emoji(self) -> None:
        assert Persona(name="Orion", emoji="🔭").label() == "Orion 🔭"

    def test_label_name_only(self) -> None:
        assert Persona(name="Atlas").label() == "Atlas"

    def test_label_empty_when_no_name(self) -> None:
        assert Persona().label() == ""
        assert Persona(emoji="🔭").label() == ""


class TestDisplayName:
    def test_persona_wins(self) -> None:
        m = AgentMeta.model_validate(
            {
                "kind": "project",
                "role": "lead",
                "name": "docket lead",
                "persona": {"name": "Orion", "emoji": "🔭"},
            }
        )
        assert m.display_name() == "Orion 🔭"

    def test_falls_back_to_name_then_role(self) -> None:
        assert (
            AgentMeta.model_validate(
                {"kind": "project", "role": "lead", "name": "docket lead"}
            ).display_name()
            == "docket lead"
        )
        assert (
            AgentMeta.model_validate({"kind": "project", "role": "lead", "name": ""}).display_name()
            == "lead"
        )

    def test_persona_round_trips_through_json(self) -> None:
        m = AgentMeta.model_validate(
            {"kind": "project", "role": "lead", "persona": {"name": "Orion", "emoji": "🔭"}}
        )
        dumped = m.model_dump(by_alias=True)
        assert dumped["persona"] == {"name": "Orion", "emoji": "🔭", "vibe": ""}
        assert AgentMeta.model_validate(dumped).persona is not None


class TestParseLabel:
    def test_name_and_emoji(self) -> None:
        p = I.parse_persona_label("Orion 🔭")
        assert (p.name, p.emoji) == ("Orion", "🔭")

    def test_multiword_name_no_emoji(self) -> None:
        p = I.parse_persona_label("Site Builder")
        assert (p.name, p.emoji) == ("Site Builder", "")

    def test_empty(self) -> None:
        assert I.parse_persona_label("   ").label() == ""


class TestUpsertPersonaBlock:
    SOUL = "# SOUL.md — docket lead\n\n## Identity\nYou are the Lead.\n"

    def test_insert_then_idempotent(self) -> None:
        p = Persona(name="Orion", emoji="🔭")
        once = I.upsert_persona_block(self.SOUL, p)
        assert I.PERSONA_BEGIN in once and "Orion 🔭" in once
        assert I.upsert_persona_block(once, p) == once  # idempotent

    def test_replace_changes_name_not_duplicate(self) -> None:
        once = I.upsert_persona_block(self.SOUL, Persona(name="Orion", emoji="🔭"))
        twice = I.upsert_persona_block(once, Persona(name="Atlas"))
        assert twice.count(I.PERSONA_BEGIN) == 1
        assert "Atlas" in twice and "Orion" not in twice

    def test_clear_restores_original(self) -> None:
        once = I.upsert_persona_block(self.SOUL, Persona(name="Orion", emoji="🔭"))
        cleared = I.upsert_persona_block(once, None)
        assert I.PERSONA_BEGIN not in cleared
        assert cleared.strip() == self.SOUL.strip()

    def test_no_persona_no_change(self) -> None:
        assert I.upsert_persona_block(self.SOUL, None) == self.SOUL


class TestQuarantineScaffolding:
    def test_moves_scaffolding_reversibly(self, tmp_path: Path) -> None:
        (tmp_path / "IDENTITY.md").write_text("pick a name\n")
        (tmp_path / "BOOTSTRAP.md").write_text("you just woke up\n")
        (tmp_path / "SOUL.md").write_text("# role\n")
        archived = I.quarantine_scaffolding(tmp_path)
        assert set(archived) == {"IDENTITY.md", "BOOTSTRAP.md"}
        assert not (tmp_path / "IDENTITY.md").exists()
        assert not (tmp_path / "BOOTSTRAP.md").exists()
        # reversible: moved, not deleted
        assert (tmp_path / ".docket-archive" / "IDENTITY.md").is_file()
        assert (tmp_path / ".docket-archive" / "BOOTSTRAP.md").is_file()
        # docket-owned files untouched
        assert (tmp_path / "SOUL.md").is_file()

    def test_idempotent_when_clean(self, tmp_path: Path) -> None:
        (tmp_path / "SOUL.md").write_text("# role\n")
        assert I.quarantine_scaffolding(tmp_path) == []
        assert I.quarantine_scaffolding(tmp_path) == []


class TestRuntimeWorkspaceContextReporting:
    """Every available section gets a fit report; a crowded one never erases the rest."""

    def test_every_available_section_reports_full_with_room_to_spare(self, tmp_path: Path) -> None:
        (tmp_path / "HEARTBEAT.md").write_text("## Ledger\nACTIVE-LEDGER-LINE\n")
        (tmp_path / "AGENTS.md").write_text("AGENT-RULE-LINE\n")
        (tmp_path / "TOOLS.md").write_text("VERIFY-GATE-LINE\n")
        (tmp_path / "MEMORY.md").write_text("DURABLE-MEMORY-LINE\n")

        text, sections = I._runtime_workspace_context(tmp_path, "")

        assert [s.name for s in sections] == [
            "HEARTBEAT.md",
            "AGENTS.md",
            "TOOLS.md",
            "MEMORY.md",
        ]
        assert all(s.status == "full" for s in sections)
        assert "ACTIVE-LEDGER-LINE" in text
        assert "VERIFY-GATE-LINE" in text

    def test_a_section_that_cannot_fit_does_not_erase_the_ones_behind_it(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(_cfg, "CONTEXT_TOKEN_BUDGET", 130, raising=True)
        (tmp_path / "HEARTBEAT.md").write_text("## Ledger\n" + ("L" * 800) + "\n")
        (tmp_path / "AGENTS.md").write_text("AGENT-RULE-LINE\n")
        (tmp_path / "TOOLS.md").write_text("VERIFY-GATE-LINE\n")
        (tmp_path / "MEMORY.md").write_text("DURABLE-MEMORY-LINE\n")

        _text, sections = I._runtime_workspace_context(tmp_path, "")

        # HEARTBEAT alone exceeds the whole budget, so it is truncated -- but that
        # must not stop AGENTS/TOOLS/MEMORY from each getting their own report.
        reported = [s.name for s in sections]
        assert reported == ["HEARTBEAT.md", "AGENTS.md", "TOOLS.md", "MEMORY.md"]
        assert sections[0].status == "truncated"
        assert all(s.status == "omitted" for s in sections[1:])

    def test_omitted_sections_leave_a_one_line_marker_when_room_allows(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Even when the whole framed block cannot fit, each section still gets a marker."""
        monkeypatch.setattr(_cfg, "CONTEXT_TOKEN_BUDGET", 70, raising=True)
        (tmp_path / "HEARTBEAT.md").write_text("## Ledger\nACTIVE-LEDGER-LINE\n")
        (tmp_path / "AGENTS.md").write_text("AGENT-RULE-LINE\n")

        text, sections = I._runtime_workspace_context(tmp_path, "")

        assert all(s.status == "omitted" for s in sections)
        assert "[... HEARTBEAT.md omitted:" in text
        assert "[... AGENTS.md omitted:" in text
