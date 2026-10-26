"""``hops/application/compose.py::_hop_message`` -- the four built-in roles carry their own fixed
instruction text, a custom role's instruction comes from its archetype (declared or
generated from `gateContract`), and a step's own `instructions` overrides whichever the
target role would carry, for every role including the Lead: its instruction resolves
through the `lead` archetype's `hopInstruction` rather than a separate literal string in
this module. See specs/functional/role-archetypes.spec.md ("Hop instructions") and
specs/functional/pipeline-format.spec.md ("Variables").
"""

from __future__ import annotations

from docket.hops.application import compose as _compose
from docket.tasks.domain.task import TaskRecord
from docket.teams import roles as _arch

SUBJECT = "docket.hops.application.compose"

_TASK = TaskRecord(description="ship the feature")


class TestBuiltinRolesByteIdenticalToBase:
    """No step override present -- the exact pre-card hardcoded text, unchanged."""

    def test_lead_message_unchanged(self) -> None:
        message, _ = _compose._hop_message(_TASK, "lead", [])
        assert message == (
            "You are the pod Lead. Decompose this task into a concrete plan for "
            "the Implementer (you never edit code yourself):\n\nship the feature"
        )

    def test_implementer_message_unchanged(self) -> None:
        message, _ = _compose._hop_message(_TASK, "implementer", [])
        assert "You are the Implementer. Implement the change in the workspace." in message

    def test_reviewer_message_unchanged(self) -> None:
        message, _ = _compose._hop_message(_TASK, "reviewer", [])
        assert (
            "You are the Reviewer. Review the diff (read-only). The LAST line of your "
            "FINAL message must be exactly `APPROVE` or `REQUEST-CHANGES`, with nothing "
            "else on that line. Reasons go above it." in message
        )

    def test_tester_message_unchanged(self) -> None:
        message, _ = _compose._hop_message(_TASK, "tester", [])
        assert (
            "You are the Tester. Validate behaviour only. The LAST line of your FINAL "
            "message must be exactly `PASS` or `FAIL`, with nothing else on that line. "
            "Evidence goes above it." in message
        )


class TestCustomRoleFallsBackToArchetype:
    def test_unregistered_role_still_gets_no_instruction(self) -> None:
        # No archetype registered for this name -- matches pre-card behavior
        # exactly (the trigger this card closes for a *registered* custom role).
        message, _ = _compose._hop_message(_TASK, "totally-unknown-role", [])
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
                "toolProfile": "read-only",
            },
            "acme",
        )
        message, _ = _compose._hop_message(_TASK, "security-reviewer", [], project="acme")
        assert "exactly `APPROVE` or `REQUEST-CHANGES`" in message

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
                "toolProfile": "write",
                "hopInstruction": "Draft the release notes.",
            },
            "acme",
        )
        message, _ = _compose._hop_message(_TASK, "writer-plus", [], project="acme")
        assert "Draft the release notes." in message


class TestStepInstructionsOverride:
    def test_step_instructions_override_a_built_in_role(self) -> None:
        message, _ = _compose._hop_message(
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
                "toolProfile": "read-only",
            },
            "acme",
        )
        message, _ = _compose._hop_message(
            _TASK, "security-reviewer", [], step_instructions="Focus on auth.", project="acme"
        )
        assert "Focus on auth." in message
        assert "APPROVE or REQUEST-CHANGES" not in message

    def test_lead_is_affected_by_a_step_override(self) -> None:
        # A step's `instructions` targeting `role: lead` must replace the
        # Lead's own instruction text, the same as it does for every other role.
        message, _ = _compose._hop_message(
            _TASK, "lead", [], step_instructions="Plan in three bullets."
        )
        assert message == "Plan in three bullets.\n\nship the feature"
        assert "Decompose this task into a concrete plan for the Implementer" not in message

    def test_lead_message_resolves_through_the_lead_archetype(self) -> None:
        # No step override -- the Lead's instruction now comes from
        # `teams.roles.resolve_hop_instruction` against the built-in `lead`
        # archetype, not a literal string in `_hop_message` itself. An overlay
        # of `lead` changes the Lead's hop message.
        _arch.add_user_archetype(
            {
                "name": "lead",
                "version": 2,
                "scope": "pod",
                "modelClass": "cheap",
                "soulTemplate": "x",
                "agentsTemplate": "y",
                "gateContract": {"kind": "none"},
                "toolProfile": "coordination",
                "hopInstruction": "You are the Lead. Plan for the Researcher.",
            },
            "acme",
        )
        message, _ = _compose._hop_message(_TASK, "lead", [], project="acme")
        assert message == "You are the Lead. Plan for the Researcher.\n\nship the feature"


_VERIFY_SENTENCE = (
    "Your work is accepted only if `sh checks/verify.sh` exits 0. Run it with the `verify` tool "
    "and fix what it reports before you finish."
)


class TestImplementerNamesItsVerifyCommand:
    """A hop whose step has a verify command tells the Implementer how it will be judged."""

    def test_the_sentence_follows_the_built_in_instruction(self) -> None:
        message, _ = _compose._hop_message(
            _TASK, "implementer", [], verify_cmd="sh checks/verify.sh"
        )
        assert message.endswith(
            "You are the Implementer. Implement the change in the workspace.\n\n" + _VERIFY_SENTENCE
        )

    def test_no_verify_command_means_no_sentence(self) -> None:
        message, _ = _compose._hop_message(_TASK, "implementer", [])
        assert "`verify` tool" not in message and "accepted only if" not in message

    def test_a_steps_own_instructions_still_get_the_sentence(self) -> None:
        message, _ = _compose._hop_message(
            _TASK,
            "implementer",
            [],
            step_instructions="Fix it your way.",
            verify_cmd="sh checks/verify.sh",
        )
        assert message.endswith("Fix it your way.\n\n" + _VERIFY_SENTENCE)

    def test_only_the_implementer_is_told(self) -> None:
        for role in ("reviewer", "tester", "lead"):
            message, _ = _compose._hop_message(_TASK, role, [], verify_cmd="sh checks/verify.sh")
            assert "sh checks/verify.sh" not in message, role
