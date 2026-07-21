"""Agent identity: docket-owned persona + quarantine of OpenClaw scaffolding.

Guards the congruence fix (agent-structure-analysis.md §6): identity is a pure
function of docket metadata (persona → name → role), rendered into SOUL.md; the
self-authored OpenClaw IDENTITY.md/BOOTSTRAP.md are pollution to be quarantined.
"""

from __future__ import annotations

from pathlib import Path

from docket.core import identity as I
from docket.core.models import AgentMeta, Persona


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
