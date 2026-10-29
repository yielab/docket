"""docket-native pipeline spec.

``pipeline/domain/spec.py`` defines the format only, a Pydantic model for the
YAML dialect the executor runs pods through; tests the model and its
validation only, not dispatch behavior. See
specs/functional/pipeline-format.spec.md for the zero-migration contract.

  * TestRoundTrip, TestUnknownKeyRejected, TestGateTypes, TestReworkBounds,
    TestParallelGroups, TestVariables, TestStepTargeting — shape validation.
  * TestZeroMigration, TestLoadPipeline, TestCommandSteps — the built-in
    pipeline, YAML/PyYAML errors, and a ``run`` step's shape/rendering.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from docket.pipeline.domain.short_form import normalize_pipeline
from docket.pipeline.domain.spec import (
    PipelineSpec,
    interpolate_instructions,
    load_pipeline,
    step_instructions_by_id,
    unresolved_step_variables,
)
from docket.pipeline.domain.step import Step

SUBJECT = "docket.pipeline.domain.step"


# ── TestStepTargeting ────────────────────────────────────────────────────────


class TestStepTargeting:
    def test_role_only(self) -> None:
        step = Step(id="s1", role="implementer")
        assert step.agent is None

    def test_agent_only(self) -> None:
        step = Step(id="s1", agent="myapp-implementer-2")
        assert step.role is None

    def test_neither_role_nor_agent_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Step(id="s1")

    def test_both_role_and_agent_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Step(id="s1", role="implementer", agent="myapp-implementer")

    def test_empty_id_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Step(id="   ", role="lead")

    def test_uppercase_role_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Step(id="s1", role="Implementer")

    def test_role_with_hyphen_and_digits_ok(self) -> None:
        step = Step(id="s1", role="content-writer-2")
        assert step.role == "content-writer-2"

    def test_archetype_shape_validated(self) -> None:
        with pytest.raises(ValidationError):
            Step(id="s1", role="implementer", archetype="Not A Slug")

    def test_archetype_valid_slug_accepted(self) -> None:
        step = Step(id="s1", role="implementer", archetype="backend-implementer")
        assert step.archetype == "backend-implementer"

    def test_archetype_existence_never_checked(self) -> None:
        # The pipeline format deliberately does not know about the archetype
        # registry — any shape-valid name is accepted, existing or not.
        step = Step(id="s1", role="implementer", archetype="some-archetype-that-does-not-exist")
        assert step.archetype == "some-archetype-that-does-not-exist"

    def test_duplicate_top_level_step_id_rejected(self) -> None:
        text = "name: p\nsteps:\n  - dup: lead\n  - dup: implementer\n"
        result = load_pipeline(text)
        assert not result.ok
        assert any("duplicate" in e for e in result.errors)

    def test_empty_steps_list_rejected(self) -> None:
        result = load_pipeline("name: p\nsteps: []\n")
        assert not result.ok

    def test_retries_must_be_non_negative(self) -> None:
        with pytest.raises(ValidationError):
            Step(id="s1", role="implementer", retries=-1)

    def test_timeout_must_be_positive(self) -> None:
        with pytest.raises(ValidationError):
            Step(id="s1", role="implementer", timeout=0)


# ── TestStepModel ─────────────────────────────────────────────────────────────


class TestStepModel:
    """A unit step's own ``model`` override (pipeline-format.spec.md Steps Req. 10):
    shape-only validation here, and short-form passthrough like ``timeout``/``retries``."""

    def test_step_model_defaults_to_none(self) -> None:
        assert Step(id="s1", role="implementer").model is None

    def test_step_model_accepts_rank_word(self) -> None:
        assert Step(id="s1", role="implementer", model="strong").model == "strong"

    def test_step_model_accepts_provider_literal(self) -> None:
        step = Step(id="s1", role="implementer", model="anthropic/claude-sonnet-4-6")
        assert step.model == "anthropic/claude-sonnet-4-6"

    def test_step_model_rejects_malformed_literal(self) -> None:
        with pytest.raises(ValidationError):
            Step(id="s1", role="implementer", model="not-a-rank-or-model-id")

    def test_parallel_group_cannot_declare_model(self) -> None:
        with pytest.raises(ValidationError):
            Step(id="fanout", model="strong", parallel=[Step(id="a", role="implementer")])

    def test_run_step_cannot_declare_model(self) -> None:
        with pytest.raises(ValidationError):
            Step(id="check", run="false", model="strong")

    def test_short_form_carries_model_through(self) -> None:
        doc = {
            "name": "p",
            "steps": [{"plan": "lead"}, {"build": "implementer", "model": "strong"}],
        }
        normalized = normalize_pipeline(doc)
        build = normalized["steps"][1]
        assert build == {"id": "build", "role": "implementer", "model": "strong"}
        spec = PipelineSpec.model_validate(normalized)
        assert spec.steps[1].model == "strong"


class TestStepToolsAndCalls:
    """A unit step's ``tools`` allow-list and ``maxToolCalls`` (pipeline-format.spec.md Steps
    Req. 11): shape-only validation, short-form passthrough, and where they are refused."""

    def test_both_default_to_none(self) -> None:
        step = Step(id="s1", role="reviewer")
        assert step.tools is None and step.max_tool_calls is None

    def test_short_form_carries_both_through(self) -> None:
        doc = {
            "name": "p",
            "steps": [{"look": "reviewer", "tools": ["read", "bash"], "maxToolCalls": 3}],
        }
        spec = PipelineSpec.model_validate(normalize_pipeline(doc))
        assert spec.steps[0].tools == ["read", "bash"]
        assert spec.steps[0].max_tool_calls == 3

    def test_an_empty_allow_list_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="tools"):
            Step(id="s1", role="reviewer", tools=[])

    @pytest.mark.parametrize("calls", [0, -1])
    def test_a_non_positive_cap_is_refused(self, calls: int) -> None:
        with pytest.raises(ValidationError):
            Step(id="s1", role="reviewer", max_tool_calls=calls)

    @pytest.mark.parametrize("field", [{"tools": ["read"]}, {"max_tool_calls": 3}])
    def test_a_command_step_and_an_input_step_carry_neither(self, field: dict[str, object]) -> None:
        with pytest.raises(ValidationError):
            Step(id="check", run="true", **field)  # type: ignore[arg-type]
        with pytest.raises(ValidationError):
            Step(id="ask", input={"from": "operator", "message": "q"}, **field)  # type: ignore[arg-type]

    @pytest.mark.parametrize("field", [{"tools": ["read"]}, {"max_tool_calls": 3}])
    def test_a_group_carries_neither_but_its_children_may(self, field: dict[str, object]) -> None:
        child = Step(id="a", role="implementer", **field)  # type: ignore[arg-type]
        assert Step(id="fanout", parallel=[child]).parallel == [child]
        with pytest.raises(ValidationError):
            Step(id="fanout", parallel=[Step(id="a", role="implementer")], **field)  # type: ignore[arg-type]


# ── TestStepInstructions ─────────────────────────────────────────────────────


class TestStepInstructions:
    def test_step_instructions_defaults_to_none(self) -> None:
        step = Step(id="s1", role="implementer")
        assert step.instructions is None

    def test_step_instructions_accepted(self) -> None:
        step = Step(id="s1", role="security-reviewer", instructions="Focus on ${area}")
        assert step.instructions == "Focus on ${area}"

    def test_parallel_group_cannot_declare_instructions(self) -> None:
        with pytest.raises(ValidationError):
            Step(
                id="fanout",
                instructions="not allowed on a group",
                parallel=[Step(id="a", role="implementer")],
            )

    def test_step_instructions_by_id_collects_top_level_and_parallel_children(self) -> None:
        spec = PipelineSpec(
            name="p",
            steps=[
                Step(id="lead", role="lead"),
                Step(id="review", role="security-reviewer", instructions="Focus on ${area}"),
                Step(
                    id="fanout",
                    parallel=[
                        Step(id="a", role="implementer", instructions="A note"),
                        Step(id="b", role="implementer"),
                    ],
                ),
            ],
        )
        assert step_instructions_by_id(spec) == {"review": "Focus on ${area}", "a": "A note"}

    def test_unresolved_step_variables_names_missing_reference(self) -> None:
        spec = PipelineSpec(
            name="p",
            steps=[Step(id="review", role="security-reviewer", instructions="Focus on ${area}")],
        )
        assert unresolved_step_variables(spec, {}) == ["area"]

    def test_unresolved_step_variables_empty_when_resolved(self) -> None:
        spec = PipelineSpec(
            name="p",
            steps=[Step(id="review", role="security-reviewer", instructions="Focus on ${area}")],
        )
        assert unresolved_step_variables(spec, {"area": "auth"}) == []

    def test_interpolate_instructions_substitutes_var(self) -> None:
        assert interpolate_instructions("Focus on ${area}", {"area": "auth"}) == "Focus on auth"

    def test_interpolate_instructions_leaves_unresolved_reference_literal(self) -> None:
        assert interpolate_instructions("Focus on ${area}", {}) == "Focus on ${area}"

    def test_interpolate_instructions_ignores_bare_dollar_sign(self) -> None:
        # Only the exact ${name} spelling is a placeholder -- a literal dollar
        # amount in prose is never mistaken for one.
        assert interpolate_instructions("Costs $5 total", {}) == "Costs $5 total"
