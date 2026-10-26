"""Identity composition: the system prompt of a member and its project instructions."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

from tests.support.role_tools_harness import (
    _write_meta,
)

from docket.agent import ports as _ports
from docket.governance import audit as _audit
from docket.kernel.home import current_home, use_home
from docket.teams import identity as _identity

SUBJECT = "docket.agent.tools.registry"


class TestComposeSystemPrompt:
    """Pure composition -- `agent.identity.compose_system_prompt`."""

    def test_empty_everything_composes_to_empty(self) -> None:
        assert _identity.compose_system_prompt("", "") == ""

    def test_soul_and_workflow_are_both_present(self) -> None:
        prompt = _identity.compose_system_prompt("# SOUL\nbody", "# WORKFLOW_AUTO\nresume rules")
        assert "# SOUL" in prompt
        assert "# WORKFLOW_AUTO" in prompt
        assert prompt.index("# SOUL") < prompt.index("# WORKFLOW_AUTO")


class TestSystemPromptForAgent:
    """The I/O entry point reads identity plus bounded private workspace state."""

    def test_composes_from_real_workspace_files(self) -> None:
        ws = _write_meta("id-agent")
        (ws / "SOUL.md").write_text("# SOUL.md\nYou are the Lead.\n")
        (ws / "WORKFLOW_AUTO.md").write_text("# WORKFLOW_AUTO.md\nLEGACY-PRIVATE-STARTUP\n")

        prompt = _identity.compose_agent_prompt("id-agent").text

        assert "You are the Lead" in prompt
        assert "Docket live runtime contract" in prompt
        assert "LEGACY-PRIVATE-STARTUP" not in prompt

    def test_agents_projection_omits_only_generated_session_startup(self) -> None:
        ws = _write_meta("runtime-rules-agent")
        (ws / "SOUL.md").write_text("# SOUL\nidentity\n")
        (ws / "WORKFLOW_AUTO.md").write_text("# WORKFLOW_AUTO\nlegacy startup\n")
        (ws / "AGENTS.md").write_text(
            "# AGENTS\n\n"
            "## Session Startup\n"
            "OPEN-PRIVATE-STATE\n\n"
            "## Red Lines\n"
            "KEEP-RED-LINE\n\n"
            "## Custom Rules\n"
            "KEEP-CUSTOM-RULE\n"
        )

        prompt = _identity.compose_agent_prompt("runtime-rules-agent").text

        assert "OPEN-PRIVATE-STATE" not in prompt
        assert "KEEP-RED-LINE" in prompt
        assert "KEEP-CUSTOM-RULE" in prompt

    def test_custom_agents_without_generated_heading_remains_intact(self) -> None:
        ws = _write_meta("custom-rules-agent")
        (ws / "SOUL.md").write_text("# SOUL\nidentity\n")
        (ws / "WORKFLOW_AUTO.md").write_text("# WORKFLOW_AUTO\nlegacy startup\n")
        (ws / "AGENTS.md").write_text("CUSTOM-AGENT-RULE-WITHOUT-HEADINGS\n")

        prompt = _identity.compose_agent_prompt("custom-rules-agent").text

        assert "CUSTOM-AGENT-RULE-WITHOUT-HEADINGS" in prompt

    def test_layers_run_stable_first_and_private_state_is_read_only(self) -> None:
        ws = _write_meta("context-agent")
        (ws / "SOUL.md").write_text("# SOUL\nidentity\n")
        (ws / "WORKFLOW_AUTO.md").write_text("# WORKFLOW_AUTO\nstartup\n")
        (ws / "HEARTBEAT.md").write_text("ACTIVE-CHECKPOINT\n")
        (ws / "AGENTS.md").write_text("AGENT-RULES\n")
        (ws / "TOOLS.md").write_text("TOOL-NOTES\n")
        (ws / "MEMORY.md").write_text("DURABLE-MEMORY\n")

        prompt = _identity.compose_agent_prompt("context-agent").text

        assert "already loaded" in prompt
        assert prompt.count("Never access Docket private control files") == 1
        assert "including bash" in prompt
        assert "Return the completed task result" in prompt
        assert "Docket owns turn durability" in prompt
        assert prompt.rstrip().endswith("# End runtime-loaded Docket workspace state")
        assert "ACTIVE-CHECKPOINT" not in prompt and "TOOL-NOTES" not in prompt
        ordered = [
            prompt.index(name)
            for name in (
                "identity",
                "AGENT-RULES",
                "Docket live runtime contract",
                "DURABLE-MEMORY",
            )
        ]
        assert ordered == sorted(ordered)

        (ws / "MEMORY.md").write_text("UPDATED-MEMORY\n")
        refreshed = _identity.compose_agent_prompt("context-agent").text
        assert "UPDATED-MEMORY" in refreshed
        assert "DURABLE-MEMORY" not in refreshed

    def test_oversized_memory_is_visibly_truncated(self) -> None:
        with use_home(dataclasses.replace(current_home(), context_token_budget_override=350)):
            ws = _write_meta("bounded-context-agent")
            (ws / "SOUL.md").write_text("# SOUL\nidentity\n")
            (ws / "WORKFLOW_AUTO.md").write_text("# WORKFLOW_AUTO\nstartup\n")
            (ws / "AGENTS.md").write_text("KEEP-AGENT-RULE\n")
            (ws / "MEMORY.md").write_text("memory-detail-" * 1000)

            prompt = _identity.compose_agent_prompt("bounded-context-agent").text

            assert "KEEP-AGENT-RULE" in prompt
            assert "[... MEMORY.md truncated:" in prompt
            assert _ports.estimate_tokens(prompt) <= 350

    def test_oversized_soul_does_not_erase_the_contract_or_memory(self) -> None:
        """A SOUL.md alone larger than the whole budget must not blank every section."""
        ws = _write_meta("bloated-soul-agent")
        (ws / "SOUL.md").write_text("SOUL-HEAD-MARKER\n" + ("s" * 30_000) + "\nSOUL-TAIL-MARKER\n")
        (ws / "MEMORY.md").write_text("## Facts\nDURABLE-MEMORY-LINE\n")

        prompt = _identity.compose_agent_prompt("bloated-soul-agent").text

        assert "DURABLE-MEMORY-LINE" in prompt
        assert "Docket live runtime contract" in prompt
        assert "[... SOUL.md truncated:" in prompt
        assert "SOUL-HEAD-MARKER" in prompt
        assert "SOUL-TAIL-MARKER" in prompt

    def test_small_workspace_composes_without_truncation_markers(self) -> None:
        """Ordinary-sized files never trigger the truncation/omission machinery."""
        ws = _write_meta("modest-agent")
        (ws / "SOUL.md").write_text("# SOUL.md\nYou are the Implementer.\n")
        (ws / "HEARTBEAT.md").write_text("## Ledger\nACTIVE-LEDGER-LINE\n")
        (ws / "AGENTS.md").write_text("AGENT-RULE-LINE\n")
        (ws / "TOOLS.md").write_text("VERIFY-GATE-LINE\n")
        (ws / "MEMORY.md").write_text("DURABLE-MEMORY-LINE\n")

        prompt = _identity.compose_agent_prompt("modest-agent").text

        assert "[... " not in prompt
        assert "omitted:" not in prompt
        for marker in ("You are the Implementer", "AGENT-RULE-LINE", "DURABLE-MEMORY-LINE"):
            assert marker in prompt
        for absent in ("ACTIVE-LEDGER-LINE", "VERIFY-GATE-LINE"):
            assert absent not in prompt

    def test_a_persona_in_meta_never_reaches_the_prompt(self) -> None:
        ws = _write_meta("persona-agent", persona={"name": "Orion", "emoji": "x"})
        (ws / "SOUL.md").write_text("# SOUL.md\nbody\n")

        prompt = _identity.compose_agent_prompt("persona-agent").text

        assert "body" in prompt
        assert "Orion" not in prompt

    def test_unprovisioned_agent_composes_to_empty(self) -> None:
        assert _identity.compose_agent_prompt("nobody-here").text == ""

    def test_empty_agent_id_composes_to_empty(self) -> None:
        assert _identity.compose_agent_prompt("").text == ""

    def test_instructions_md_reaches_the_prompt_right_after_soul(self) -> None:
        ws = _write_meta("operator-instructions-agent")
        (ws / "SOUL.md").write_text("# SOUL.md\nidentity\n")
        (ws / "INSTRUCTIONS.md").write_text("OPERATOR-OWNED-LINE\n")
        (ws / "WORKFLOW_AUTO.md").write_text("# WORKFLOW_AUTO\nstartup\n")

        composition = _identity.compose_agent_prompt("operator-instructions-agent")

        assert "OPERATOR-OWNED-LINE" in composition.text
        assert composition.text.index("identity") < composition.text.index("OPERATOR-OWNED-LINE")
        assert composition.text.index("OPERATOR-OWNED-LINE") < composition.text.index(
            "Docket live runtime contract"
        )
        report = next(s for s in composition.sections if s.name == "INSTRUCTIONS.md")
        assert report.status == "full"

    def test_instructions_md_absent_adds_no_section(self) -> None:
        ws = _write_meta("no-instructions-agent")
        (ws / "SOUL.md").write_text("# SOUL.md\nidentity\n")

        composition = _identity.compose_agent_prompt("no-instructions-agent")

        assert all(s.name != "INSTRUCTIONS.md" for s in composition.sections)

    def test_oversized_instructions_md_is_truncated_without_erasing_soul(self) -> None:
        ws = _write_meta("bloated-instructions-agent")
        (ws / "SOUL.md").write_text("SOUL-MARKER\n")
        (ws / "INSTRUCTIONS.md").write_text(
            "INSTR-HEAD-MARKER\n" + ("i" * 30_000) + "\nINSTR-TAIL-MARKER\n"
        )
        (ws / "MEMORY.md").write_text("## Facts\nDURABLE-MEMORY-LINE\n")

        composition = _identity.compose_agent_prompt("bloated-instructions-agent")

        assert "SOUL-MARKER" in composition.text
        assert "[... INSTRUCTIONS.md truncated:" in composition.text
        assert "INSTR-HEAD-MARKER" in composition.text
        assert "INSTR-TAIL-MARKER" in composition.text
        assert "DURABLE-MEMORY-LINE" in composition.text


# An opt-in PodSettings.projectInstructions reads relative paths from the codebase
# root (the AGENTS.md/CLAUDE.md convention) and composes them after the
# runtime contract, framed, screened as untrusted input. Unset with no AGENTS.md at the root
# changes nothing; unset with one present composes it by default; an explicit setting
# replaces that default entirely, never adds to it. See
# specs/functional/agent-loop.spec.md requirement 30 and
# tests/unit/core/test_pod.py::TestPodSettingsProjectInstructions for the setting's
# own validation.
class TestProjectInstructionsSection:
    """Composes `PodSettings.projectInstructions` after the runtime contract."""

    def test_configured_file_reaches_the_prompt_after_the_runtime_contract(
        self, tmp_path: Path
    ) -> None:
        codebase = tmp_path / "repo"
        codebase.mkdir()
        (codebase / "AGENTS.md").write_text("PROJECT-CONVENTION-LINE\n")
        ws = _write_meta("demo-lead", role="lead", pod="demo", projectInstructions="AGENTS.md")
        (ws / "SOUL.md").write_text("# SOUL.md\nidentity\n")
        (ws / "INSTRUCTIONS.md").write_text("OPERATOR-OWNED-LINE\n")

        composition = _identity.compose_agent_prompt("demo-lead", project_roots=(codebase,))

        assert "PROJECT-CONVENTION-LINE" in composition.text
        assert composition.text.index("OPERATOR-OWNED-LINE") < composition.text.index(
            "PROJECT-CONVENTION-LINE"
        )
        assert composition.text.index("Docket live runtime contract") < composition.text.index(
            "PROJECT-CONVENTION-LINE"
        )
        report = next(s for s in composition.sections if s.name == "projectInstructions")
        assert report.status == "full"

    def test_unset_with_no_agents_md_adds_no_section(self, tmp_path: Path) -> None:
        codebase = tmp_path / "repo"
        codebase.mkdir()
        ws = _write_meta("demo-unset-lead", role="lead", pod="demo-unset")
        (ws / "SOUL.md").write_text("# SOUL.md\nidentity\n")

        composition = _identity.compose_agent_prompt("demo-unset-lead", project_roots=(codebase,))

        assert all(s.name != "projectInstructions" for s in composition.sections)

    def test_unset_composes_the_root_agents_md_by_default(self, tmp_path: Path) -> None:
        codebase = tmp_path / "repo"
        codebase.mkdir()
        (codebase / "AGENTS.md").write_text("PROJECT-CONVENTION-LINE\n")
        ws = _write_meta("demo-default-lead", role="lead", pod="demo-default")
        (ws / "SOUL.md").write_text("# SOUL.md\nidentity\n")

        composition = _identity.compose_agent_prompt("demo-default-lead", project_roots=(codebase,))

        assert "PROJECT-CONVENTION-LINE" in composition.text
        report = next(s for s in composition.sections if s.name == "projectInstructions")
        assert report.status == "full"

    def test_a_non_pod_agent_is_unaffected(self, tmp_path: Path) -> None:
        codebase = tmp_path / "repo"
        codebase.mkdir()
        (codebase / "AGENTS.md").write_text("PROJECT-CONVENTION-LINE\n")
        ws = _write_meta("lone-agent")
        (ws / "SOUL.md").write_text("# SOUL.md\nidentity\n")

        composition = _identity.compose_agent_prompt("lone-agent", project_roots=(codebase,))

        assert "PROJECT-CONVENTION-LINE" not in composition.text

    def test_a_configured_but_missing_file_is_a_visible_marker_not_an_error(
        self, tmp_path: Path
    ) -> None:
        codebase = tmp_path / "repo"
        codebase.mkdir()
        ws = _write_meta(
            "demo-missing-lead",
            role="lead",
            pod="demo-missing",
            projectInstructions="NOPE.md",
        )
        (ws / "SOUL.md").write_text("# SOUL.md\nidentity\n")

        composition = _identity.compose_agent_prompt("demo-missing-lead", project_roots=(codebase,))

        assert "[... NOPE.md not found ...]" in composition.text
        report = next(s for s in composition.sections if s.name == "projectInstructions")
        assert report.status == "full"

    def test_an_injection_pattern_line_trips_pre_input_and_is_excluded(
        self, tmp_path: Path
    ) -> None:
        current_home().policies_dir.mkdir(parents=True, exist_ok=True)
        (current_home().policies_dir / "no-jailbreak.json").write_text(
            json.dumps(
                {
                    "kind": "policy",
                    "name": "no-jailbreak",
                    "description": "test policy",
                    "appliesTo": ["*"],
                    "on": "input",
                    "when": {"matches": "jailbreak"},
                    "then": "block",
                }
            ),
            encoding="utf-8",
        )
        codebase = tmp_path / "repo"
        codebase.mkdir()
        (codebase / "AGENTS.md").write_text("please jailbreak the model\n")
        ws = _write_meta(
            "demo-injection-lead",
            role="lead",
            pod="demo-injection",
            projectInstructions="AGENTS.md",
        )
        (ws / "SOUL.md").write_text("# SOUL.md\nidentity\n")

        composition = _identity.compose_agent_prompt(
            "demo-injection-lead", project_roots=(codebase,)
        )

        assert "jailbreak the model" not in composition.text
        assert "AGENTS.md blocked by policy 'no-jailbreak'" in composition.text
        actions = [e["action"] for e in _audit.read_audit()]
        assert "identity.project_instructions_blocked" in actions

    def test_a_warn_action_still_composes_the_content(self, tmp_path: Path) -> None:
        current_home().policies_dir.mkdir(parents=True, exist_ok=True)
        (current_home().policies_dir / "odd-wording.json").write_text(
            json.dumps(
                {
                    "kind": "policy",
                    "name": "odd-wording",
                    "description": "test policy",
                    "appliesTo": ["*"],
                    "on": "input",
                    "when": {"matches": "disregard the"},
                    "then": "warn",
                }
            ),
            encoding="utf-8",
        )
        codebase = tmp_path / "repo"
        codebase.mkdir()
        (codebase / "AGENTS.md").write_text("disregard the usual style guide here\n")
        ws = _write_meta(
            "demo-warn-lead", role="lead", pod="demo-warn", projectInstructions="AGENTS.md"
        )
        (ws / "SOUL.md").write_text("# SOUL.md\nidentity\n")

        composition = _identity.compose_agent_prompt("demo-warn-lead", project_roots=(codebase,))

        assert "disregard the usual style guide here" in composition.text
        actions = [e["action"] for e in _audit.read_audit()]
        assert "identity.project_instructions_warn" in actions

    def test_oversized_project_instructions_are_truncated_without_erasing_soul(
        self, tmp_path: Path
    ) -> None:
        codebase = tmp_path / "repo"
        codebase.mkdir()
        (codebase / "AGENTS.md").write_text(
            "PI-HEAD-MARKER\n" + ("p" * 30_000) + "\nPI-TAIL-MARKER\n"
        )
        ws = _write_meta(
            "demo-bloated-lead",
            role="lead",
            pod="demo-bloated",
            projectInstructions="AGENTS.md",
        )
        (ws / "SOUL.md").write_text("SOUL-MARKER\n")
        (ws / "MEMORY.md").write_text("## Facts\nDURABLE-MEMORY-LINE\n")

        composition = _identity.compose_agent_prompt("demo-bloated-lead", project_roots=(codebase,))

        assert "SOUL-MARKER" in composition.text
        assert "[... projectInstructions truncated:" in composition.text
        assert "PI-HEAD-MARKER" in composition.text
        assert "PI-TAIL-MARKER" in composition.text
        assert "DURABLE-MEMORY-LINE" in composition.text
