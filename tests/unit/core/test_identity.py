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

_LOCAL_WINDOW = 16_384
_LOCAL_MAX_OUTPUT = 8_192
_HOSTED_WINDOW = 200_000

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


class TestResolveStaticContextBudget:
    """Explicit override > window share > today's plain constant."""

    def test_no_window_resolves_to_the_default(self) -> None:
        tokens, source = I.resolve_static_context_budget(None, None)
        assert (tokens, source) == (_cfg.CONTEXT_TOKEN_BUDGET_DEFAULT, "default")

    def test_a_small_registered_window_keeps_the_default(self) -> None:
        """Today's only deployed window (local llama.cpp, 16384/8192) must not change
        the resolved static budget -- the floor, not the share, wins here."""
        tokens, source = I.resolve_static_context_budget(_LOCAL_WINDOW, _LOCAL_MAX_OUTPUT)
        assert (tokens, source) == (_cfg.CONTEXT_TOKEN_BUDGET_DEFAULT, "default")

    def test_a_large_registered_window_resolves_a_bigger_share(self) -> None:
        tokens, source = I.resolve_static_context_budget(_HOSTED_WINDOW, _LOCAL_MAX_OUTPUT)
        assert source == "window"
        assert tokens > _cfg.CONTEXT_TOKEN_BUDGET_DEFAULT

    def test_env_style_override_wins_even_with_a_large_window(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A test-style override (module attribute, never the environment) must still be
        honoured as an explicit override -- the same path a real CONTEXT_TOKEN_BUDGET env
        var takes, since the module constant is what every reader actually sees."""
        monkeypatch.setattr(_cfg, "CONTEXT_TOKEN_BUDGET", 350, raising=True)
        tokens, source = I.resolve_static_context_budget(_HOSTED_WINDOW, _LOCAL_MAX_OUTPUT)
        assert (tokens, source) == (350, "env")

    def test_real_env_var_wins_even_when_equal_to_the_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CONTEXT_TOKEN_BUDGET", str(_cfg.CONTEXT_TOKEN_BUDGET_DEFAULT))
        tokens, source = I.resolve_static_context_budget(_HOSTED_WINDOW, _LOCAL_MAX_OUTPUT)
        assert (tokens, source) == (_cfg.CONTEXT_TOKEN_BUDGET_DEFAULT, "env")


class TestComposeAgentPromptIsWindowAware:
    """The oversized-SOUL fixture: a 16k window changes nothing; a large
    registered window fits every section in full instead of truncating SOUL."""

    def _oversized_soul_workspace(self, agent_id: str) -> Path:
        """No ``.docket-meta.json`` needed: ``compose_agent_prompt`` degrades a missing
        persona lookup to ``None`` rather than raising, and DOCKET_HOME isolation is the
        autouse ``tests/conftest.py`` fixture, not something this test manages."""
        ws = _cfg.workspace_dir(agent_id)
        ws.mkdir(parents=True, exist_ok=True)
        (ws / "SOUL.md").write_text("SOUL-HEAD-MARKER\n" + ("s" * 30_000) + "\nSOUL-TAIL-MARKER\n")
        (ws / "HEARTBEAT.md").write_text("## Ledger\nACTIVE-LEDGER-LINE\n")
        (ws / "TOOLS.md").write_text("Run the verify gate: VERIFY-GATE-LINE\n")
        return ws

    def test_red_at_16k_the_oversized_soul_is_still_truncated(self) -> None:
        """Pinned: a registered-but-small window changes nothing from the unregistered
        (no-window) case this fixture already covers in test_role_tools_and_identity.py."""
        self._oversized_soul_workspace("windowed-16k-agent")
        composition = I.compose_agent_prompt(
            "windowed-16k-agent",
            context_window_tokens=_LOCAL_WINDOW,
            max_output_tokens=_LOCAL_MAX_OUTPUT,
        )
        assert "[... SOUL.md truncated:" in composition.text
        assert "SOUL-HEAD-MARKER" in composition.text
        assert "SOUL-TAIL-MARKER" in composition.text
        assert "ACTIVE-LEDGER-LINE" in composition.text
        assert "VERIFY-GATE-LINE" in composition.text
        assert composition.budget_tokens == _cfg.CONTEXT_TOKEN_BUDGET_DEFAULT
        assert composition.budget_source == "default"

    def test_a_large_registered_window_fits_every_section_in_full(self) -> None:
        """The RED-first case: on the base, this same fixture is truncated regardless of
        window because nothing reads context_window_tokens at all yet."""
        self._oversized_soul_workspace("windowed-200k-agent")
        composition = I.compose_agent_prompt(
            "windowed-200k-agent",
            context_window_tokens=_HOSTED_WINDOW,
            max_output_tokens=_LOCAL_MAX_OUTPUT,
        )
        assert "[... SOUL.md truncated:" not in composition.text
        assert "[... SOUL.md omitted:" not in composition.text
        assert "s" * 30_000 in composition.text
        assert "ACTIVE-LEDGER-LINE" in composition.text
        assert "VERIFY-GATE-LINE" in composition.text
        assert composition.budget_source == "window"
        assert all(s.status == "full" for s in composition.sections)
