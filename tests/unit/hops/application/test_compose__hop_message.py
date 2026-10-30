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
from docket.kernel import brief as _brief
from docket.kernel import handoff as _handoff
from docket.kernel.home import current_home
from docket.tasks.domain.task import HopResult, TaskRecord
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
            "You are the Reviewer. Review the work of the step before (read-only). The LAST line of your "
            "FINAL message must be exactly `APPROVE` or `REQUEST-CHANGES`, with nothing "
            "else on that line. Reasons go above it." in message
        )


class TestCustomRoleFallsBackToArchetype:
    def test_unregistered_role_still_gets_no_instruction(self) -> None:
        # No archetype registered for this name -- matches pre-card behavior
        # exactly (the trigger this card closes for a *registered* custom role).
        message, _ = _compose._hop_message(_TASK, "totally-unknown-role", [])
        assert message == "## Task\nship the feature\n\n## Hop"

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
        # `teams.role_schema.resolve_hop_prompt` against the built-in `lead`
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


class TestHopNamesItsVerifyCommand:
    """A hop whose step has a verify command is told how it will be judged, whatever its role."""

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

    def test_any_role_whose_step_has_the_command_is_told(self) -> None:
        for role in ("reviewer", "operator"):
            message, _ = _compose._hop_message(_TASK, role, [], verify_cmd="sh checks/verify.sh")
            assert message.endswith(_VERIFY_SENTENCE), role

    def test_a_hop_composed_without_a_command_is_not_told_one(self) -> None:
        for role in ("reviewer", "lead", "operator"):
            message, _ = _compose._hop_message(_TASK, role, [])
            assert "sh checks/verify.sh" not in message, role


class TestHopInstructionByModelClass:
    def _reviewer_variant(self) -> None:
        directory = current_home().prompts_dir / "hop"
        directory.mkdir(parents=True)
        (directory / "reviewer.cheap.md").write_text(
            "---\nkind: prompt\nname: reviewer\nversion: 1.0.0\nlayer: hop\nfor: reviewer\n"
            "modelClass: cheap\n---\nSHORT REVIEW\n",
            encoding="utf-8",
        )

    def test_a_cheap_hop_reads_the_cheap_file(self) -> None:
        self._reviewer_variant()

        message, _ = _compose._hop_message(_TASK, "reviewer", [], model_class="cheap")

        assert "SHORT REVIEW" in message

    def test_any_other_hop_keeps_the_shipped_text(self) -> None:
        self._reviewer_variant()

        message, _ = _compose._hop_message(_TASK, "reviewer", [], model_class="strong")

        assert "SHORT REVIEW" not in message
        assert "You are the Reviewer." in message


def _lead_hop() -> HopResult:
    brief = _brief.TaskBrief(objective="add a flag", context=["edit src/app/x.py"])
    return HopResult(
        role="lead",
        member_id="demo-lead",
        ok=True,
        output="the plan",
        artifact=_handoff.HandoffArtifact(summary="the plan", brief=brief),
    )


def _task_section(message: str) -> str:
    return message.split("\n\n## Hop\n", 1)[0]


class TestTwoSections:
    """A non-Lead message is a `## Task` section then a `## Hop` section."""

    def test_the_description_is_in_task_and_the_instruction_in_hop(self) -> None:
        message, _ = _compose._hop_message(_TASK, "implementer", [])

        task, hop = message.split("\n\n## Hop\n", 1)
        assert task == "## Task\nship the feature"
        assert hop.startswith("You are the Implementer.")

    def test_the_prior_artifacts_are_in_hop(self) -> None:
        message, _ = _compose._hop_message(_TASK, "reviewer", [_lead_hop()])

        assert "the plan" not in _task_section(message)
        assert "--- lead output ---" in message.split("\n\n## Hop\n", 1)[1]

    def test_the_task_section_is_the_same_for_two_hops_of_one_task(self) -> None:
        prior = [_lead_hop()]
        implementer, _ = _compose._hop_message(_TASK, "implementer", prior)
        reviewer, _ = _compose._hop_message(_TASK, "reviewer", prior)
        rework, _ = _compose._hop_message(
            _TASK,
            "implementer",
            [*prior, HopResult(role="reviewer", ok=True, output="REQUEST-CHANGES\nfix it")],
            rework_hop=HopResult(role="reviewer", ok=True, output="REQUEST-CHANGES\nfix it"),
        )

        assert _task_section(implementer) == _task_section(reviewer) == _task_section(rework)

    def test_the_lead_message_has_no_section_headings(self) -> None:
        message, _ = _compose._hop_message(_TASK, "lead", [])

        assert "## Task" not in message and "## Hop" not in message

    def test_the_layers_name_the_task_between_identity_and_hop(self) -> None:
        _, comp = _compose._hop_message(_TASK, "implementer", [])
        _, lead = _compose._hop_message(_TASK, "lead", [])

        assert [layer.layer for layer in comp.layers] == ["identity", "task", "hop"]
        task_layer = comp.layers[1].prompt
        assert task_layer.text == "## Task\nship the feature"
        assert "task" not in [layer.layer for layer in lead.layers]


_STRUCTURED = {
    "objective": "add a flag",
    "doneWhen": "the flag test passes",
    "acceptance": ["--flag is accepted", "--no-flag is accepted"],
    "constraints": ["no new dependency"],
    "risk": "touches the parser",
    "answers": [{"question": "which flag", "answer": "--flag"}],
    "verify": "pytest tests/test_flag.py",
    "kind": "feature",
    "paths": ["src/app/"],
}


class TestStructuredTask:
    """A task's structured request renders after its description in one fixed order."""

    def test_the_fields_render_after_the_description_in_the_fixed_order(self) -> None:
        task = TaskRecord.model_validate({"description": "Add a flag", "task": _STRUCTURED})

        message, _ = _compose._hop_message(task, "implementer", [])

        section = _task_section(message)
        assert section == (
            "## Task\nAdd a flag\n\n"
            "Objective: add a flag\n"
            "Done when: the flag test passes\n"
            "Acceptance:\n- --flag is accepted\n- --no-flag is accepted\n"
            "Constraints:\n- no new dependency\n"
            "Risk: touches the parser\n"
            'Answers:\n- {"answer": "--flag", "question": "which flag"}\n'
            "Verify: pytest tests/test_flag.py\n"
            "Kind: feature\n"
            "Paths:\n- src/app/"
        )

    def test_only_the_fields_that_are_set_render(self) -> None:
        task = TaskRecord.model_validate(
            {"description": "Add a flag", "task": {"doneWhen": "it works"}}
        )

        message, _ = _compose._hop_message(task, "reviewer", [])

        assert _task_section(message) == "## Task\nAdd a flag\n\nDone when: it works"

    def test_a_task_without_the_request_is_unchanged(self) -> None:
        message, _ = _compose._hop_message(_TASK, "implementer", [])

        assert _task_section(message) == "## Task\nship the feature"

    def test_the_section_is_the_same_for_two_hops(self) -> None:
        task = TaskRecord.model_validate({"description": "Add a flag", "task": _STRUCTURED})

        implementer, _ = _compose._hop_message(task, "implementer", [])
        reviewer, _ = _compose._hop_message(task, "reviewer", [])

        assert _task_section(implementer) == _task_section(reviewer)
