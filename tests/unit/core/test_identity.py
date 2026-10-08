"""Agent identity: prompt composition from the workspace identity files.

The display name is a pure function of docket metadata (name → role).
"""

from __future__ import annotations

from pathlib import Path

import pytest

import docket.config as _cfg
from docket.core import identity as I
from docket.core import pod as _pod
from docket.core.models import AgentMeta
from docket.edges import store as _store

_LOCAL_WINDOW = 16_384
_LOCAL_MAX_OUTPUT = 8_192
_HOSTED_WINDOW = 200_000

SUBJECT = "docket.core.identity"


class TestDisplayName:
    def test_a_persona_key_in_meta_does_not_rename_the_agent(self) -> None:
        m = AgentMeta.model_validate(
            {
                "kind": "project",
                "role": "lead",
                "name": "docket lead",
                "persona": {"name": "Orion", "emoji": "🔭"},
            }
        )
        assert m.display_name() == "docket lead"

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


class TestSoulHasNoPersonaBlock:
    def test_a_meta_written_with_a_persona_composes_without_it(self) -> None:
        ws = _cfg.workspace_dir("persona-free")
        ws.mkdir(parents=True, exist_ok=True)
        (ws / "SOUL.md").write_text("# SOUL\nbody\n")
        _store.write_json(
            _cfg.meta_path("persona-free"),
            {"kind": "project", "role": "lead", "persona": {"name": "Orion", "emoji": "x"}},
        )
        text = I.compose_agent_prompt("persona-free").text
        assert "body" in text
        assert "Orion" not in text
        assert "## Persona" not in text


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
        meta file to no prompt material rather than raising, and DOCKET_HOME isolation is the
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


class TestProjectInstructionsDefault:
    """An unset `PodSettings.project_instructions` composes the codebase root's own
    AGENTS.md by default; an explicit setting replaces the default entirely."""

    def _lead_workspace(self, agent_id: str, project: str, **overrides: object) -> Path:
        ws = _cfg.workspace_dir(agent_id)
        ws.mkdir(parents=True, exist_ok=True)
        data: dict[str, object] = {"kind": "project", "role": "lead", "pod": project}
        data.update(overrides)
        _store.write_json(_cfg.meta_path(agent_id), data)
        return ws

    def test_unset_composes_the_root_agents_md_by_default(self, tmp_path: Path) -> None:
        codebase = tmp_path / "repo"
        codebase.mkdir()
        (codebase / "AGENTS.md").write_text("REPO-AGENTS-SENTINEL\n")
        ws = self._lead_workspace("default-demo-lead", "default-demo")
        (ws / "SOUL.md").write_text("# SOUL.md\nidentity\n")

        composition = I.compose_agent_prompt("default-demo-lead", project_roots=(codebase,))

        assert "REPO-AGENTS-SENTINEL" in composition.text
        report = next(s for s in composition.sections if s.name == I.PROJECT_INSTRUCTIONS_LABEL)
        assert report.status == "full"

        files, source = I.project_instruction_files(
            _pod.PodSettings.load_for("default-demo"), codebase
        )
        assert files == ("AGENTS.md",)
        assert source == "default"

    def test_an_explicit_setting_replaces_the_default_not_adds_to_it(self, tmp_path: Path) -> None:
        codebase = tmp_path / "repo"
        codebase.mkdir()
        (codebase / "AGENTS.md").write_text("REPO-AGENTS-SENTINEL\n")
        (codebase / "CONTRIBUTING.md").write_text("REPO-CONTRIBUTING-SENTINEL\n")
        ws = self._lead_workspace(
            "explicit-demo-lead", "explicit-demo", projectInstructions="CONTRIBUTING.md"
        )
        (ws / "SOUL.md").write_text("# SOUL.md\nidentity\n")

        composition = I.compose_agent_prompt("explicit-demo-lead", project_roots=(codebase,))

        assert "REPO-CONTRIBUTING-SENTINEL" in composition.text
        assert "REPO-AGENTS-SENTINEL" not in composition.text

        files, source = I.project_instruction_files(
            _pod.PodSettings.load_for("explicit-demo"), codebase
        )
        assert files == ("CONTRIBUTING.md",)
        assert source == "set"


class TestSkillsSection:
    """A discovered skill composes a `# Skills` index right after project instructions and
    still ahead of the runtime contract (ADR 0013 §3 rule 8); no skill, no section."""

    def _lead_workspace(self, agent_id: str, project: str) -> Path:
        ws = _cfg.workspace_dir(agent_id)
        ws.mkdir(parents=True, exist_ok=True)
        _store.write_json(
            _cfg.meta_path(agent_id), {"kind": "project", "role": "lead", "pod": project}
        )
        return ws

    def test_a_discovered_skill_composes_a_named_section(self, tmp_path: Path) -> None:
        codebase = tmp_path / "repo"
        codebase.mkdir()
        project = "skilled-demo"
        ws = self._lead_workspace("skilled-demo-lead", project)
        (ws / "SOUL.md").write_text("# SOUL.md\nidentity\n")
        skill_dir = _cfg.pod_config_dir(project) / "skills" / "security-review"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: security-review\ndescription: Reviews a diff for security bugs.\n"
            "---\n\nChecklist body.\n"
        )

        composition = I.compose_agent_prompt("skilled-demo-lead", project_roots=(codebase,))

        assert "# Skills" in composition.text
        assert "- security-review: Reviews a diff for security bugs." in composition.text
        report = next(s for s in composition.sections if s.name == I.SKILLS_LABEL)
        assert report.status == "full"

    def test_no_discovered_skills_composes_no_section(self, tmp_path: Path) -> None:
        codebase = tmp_path / "repo"
        codebase.mkdir()
        project = "skill-free-demo"
        ws = self._lead_workspace("skill-free-demo-lead", project)
        (ws / "SOUL.md").write_text("# SOUL.md\nidentity\n")

        composition = I.compose_agent_prompt("skill-free-demo-lead", project_roots=(codebase,))

        assert "# Skills" not in composition.text
        assert not any(s.name == I.SKILLS_LABEL for s in composition.sections)
