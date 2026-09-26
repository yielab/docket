"""``core/dispatch.py::_hop_message`` -- the four built-in roles stay byte-identical to
base, a custom role's instruction now comes from its archetype (declared or generated
from `gateContract`), and a step's own `instructions` overrides whichever the target
role would otherwise carry. See specs/functional/role-archetypes.spec.md ("Hop
instructions") and specs/functional/pipeline-format.spec.md ("Variables").
"""

from __future__ import annotations

from pathlib import Path

import pytest

import docket.config as _cfg
from docket.core import archetypes as _arch
from docket.core import dispatch as _dispatch

SUBJECT = "docket.core.dispatch"

_TASK = {"description": "ship the feature"}


@pytest.fixture(autouse=True)
def _hermetic_registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_cfg, "ARCHETYPE_REGISTRY_FILE", tmp_path / "docket-roles.json")


class TestBuiltinRolesByteIdenticalToBase:
    """No step override present -- the exact pre-card hardcoded text, unchanged."""

    def test_lead_message_unchanged(self) -> None:
        message, _ = _dispatch._hop_message(_TASK, "lead", [])
        assert message == (
            "You are the pod Lead. Decompose this task into a concrete plan for "
            "the Implementer (you never edit code yourself):\n\nship the feature"
        )

    def test_implementer_message_unchanged(self) -> None:
        message, _ = _dispatch._hop_message(_TASK, "implementer", [])
        assert "You are the Implementer. Implement the change in the workspace." in message

    def test_reviewer_message_unchanged(self) -> None:
        message, _ = _dispatch._hop_message(_TASK, "reviewer", [])
        assert (
            "You are the Reviewer. Review the diff (read-only). Start exactly one "
            "output line with APPROVE or REQUEST-CHANGES (case-insensitive); "
            "reasons may come before or after that marker line." in message
        )

    def test_tester_message_unchanged(self) -> None:
        message, _ = _dispatch._hop_message(_TASK, "tester", [])
        assert (
            "You are the Tester. Validate behaviour only. Start exactly one output "
            "line with PASS or FAIL (case-insensitive); evidence may come before or "
            "after that marker line." in message
        )


class TestCustomRoleFallsBackToArchetype:
    def test_unregistered_role_still_gets_no_instruction(self) -> None:
        # No archetype registered for this name -- matches pre-card behavior
        # exactly (the trigger this card closes for a *registered* custom role).
        message, _ = _dispatch._hop_message(_TASK, "totally-unknown-role", [])
        assert "Task: ship the feature" in message
        assert message.strip().endswith("ship the feature")

    def test_registered_verdict_role_gets_generated_marker_instruction(self) -> None:
        _arch.add_user_archetype(
            {
                "name": "security-reviewer",
                "version": 1,
                "scope": "pod",
                "modelClass": "cheap",
                "soulTemplate": "x",
                "agentsTemplate": "y",
                "gateContract": {"kind": "verdict", "regexes": ["APPROVE", "REQUEST-CHANGES"]},
                "editRights": "read-only",
                "toolProfile": "read-only",
            }
        )
        message, _ = _dispatch._hop_message(_TASK, "security-reviewer", [])
        assert "APPROVE or REQUEST-CHANGES" in message

    def test_registered_role_with_declared_hop_instruction_uses_it_verbatim(self) -> None:
        _arch.add_user_archetype(
            {
                "name": "writer-plus",
                "version": 1,
                "scope": "pod",
                "modelClass": "cheap",
                "soulTemplate": "x",
                "agentsTemplate": "y",
                "gateContract": {"kind": "none"},
                "editRights": "write",
                "toolProfile": "write",
                "hopInstruction": "Draft the release notes.",
            }
        )
        message, _ = _dispatch._hop_message(_TASK, "writer-plus", [])
        assert "Draft the release notes." in message


class TestStepInstructionsOverride:
    def test_step_instructions_override_a_built_in_role(self) -> None:
        message, _ = _dispatch._hop_message(
            _TASK, "implementer", [], step_instructions="Focus on auth only."
        )
        assert "Focus on auth only." in message
        assert "Implement the change in the workspace" not in message

    def test_step_instructions_override_a_custom_role(self) -> None:
        _arch.add_user_archetype(
            {
                "name": "security-reviewer",
                "version": 1,
                "scope": "pod",
                "modelClass": "cheap",
                "soulTemplate": "x",
                "agentsTemplate": "y",
                "gateContract": {"kind": "verdict", "regexes": ["APPROVE", "REQUEST-CHANGES"]},
                "editRights": "read-only",
                "toolProfile": "read-only",
            }
        )
        message, _ = _dispatch._hop_message(
            _TASK, "security-reviewer", [], step_instructions="Focus on auth."
        )
        assert "Focus on auth." in message
        assert "APPROVE or REQUEST-CHANGES" not in message

    def test_lead_is_not_affected_by_a_step_override(self) -> None:
        # The Lead's hop message has no separate instruction segment to
        # override -- a deliberate scope boundary (see the module docstring).
        message, _ = _dispatch._hop_message(
            _TASK, "lead", [], step_instructions="This should not appear."
        )
        assert message == (
            "You are the pod Lead. Decompose this task into a concrete plan for "
            "the Implementer (you never edit code yourself):\n\nship the feature"
        )
