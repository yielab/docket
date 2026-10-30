"""The pipeline spec: round trip, rejected keys, rework bounds, parallel groups and variables."""

from __future__ import annotations

import pytest
import yaml
from pydantic import ValidationError

from docket.pipeline.domain import plan as _orch
from docket.pipeline.domain.gates import MechanicalGate, ReworkEdge
from docket.pipeline.domain.short_form import normalize_pipeline
from docket.pipeline.domain.spec import (
    PipelineSpec,
    Variable,
    load_pipeline,
)
from docket.pipeline.domain.step import Step
from docket.teams import roles as _archetypes

SUBJECT = "docket.pipeline.domain.spec"


FULL_YAML = """\
name: release
description: Ship a change through the pod.

variables:
  TARGET:
    default: main
    description: branch to ship
  REASON:
    required: true

steps:
  - plan: lead

  - build: implementer
    retries: 2
    timeout: 600
    archetype: implementer
    verify: {command: "make test", timeout: 300}

  - review: reviewer
    verdict: [APPROVE, REQUEST-CHANGES]
    on: {REQUEST-CHANGES: {goto: build, max: 2}}

  - fanout:
      parallel:
        - impl-a: myapp-implementer
        - impl-b: myapp-implementer-2

  - ship: implementer
    approval: "Ready to deploy?"
"""


_SECURE_BUILD_CANONICAL: dict[str, object] = {
    "name": "secure-build",
    "description": (
        "Lead plans the change, Implementer builds it (gated on its own verify command), then a "
        "read-only Security Vetter reviews the diff and must APPROVE before the task is done. A "
        "REQUEST-CHANGES verdict sends it back to the Implementer once."
    ),
    "steps": [
        {"id": "plan", "role": "lead"},
        {"id": "build", "role": "implementer", "timeout": 900, "gate": {"type": "mechanical"}},
        {
            "id": "vet",
            "role": "security-vetter",
            "gate": {
                "type": "verdict",
                "pattern": r"^\s*(APPROVE|REQUEST-CHANGES)\b",
                "passValues": ["approve"],
                "rework": {"to": "build", "when": ["request-changes"], "maxCycles": 1},
            },
        },
    ],
}


_SECURE_BUILD_SHORT = """\
kind: pipeline
name: secure-build
description: >-
  Lead plans the change, Implementer builds it (gated on its own verify command), then a
  read-only Security Vetter reviews the diff and must APPROVE before the task is done. A
  REQUEST-CHANGES verdict sends it back to the Implementer once.
steps:
  - plan: lead
  - build: implementer
    timeout: 900
    verify: true
  - vet: security-vetter
    verdict: [APPROVE, REQUEST-CHANGES]
    on: {REQUEST-CHANGES: {goto: build, max: 1}}
"""


class TestRoundTrip:
    def test_valid_pipeline_loads(self) -> None:
        result = load_pipeline(FULL_YAML)
        assert result.ok, result.errors
        assert result.source == "file"
        assert result.spec is not None
        assert [s.id for s in result.spec.steps] == ["plan", "build", "review", "fanout", "ship"]

    def test_round_trips_through_dump(self) -> None:
        spec = load_pipeline(FULL_YAML).spec
        assert spec is not None
        dumped = spec.model_dump(by_alias=True)
        reloaded = PipelineSpec.model_validate(dumped)
        assert reloaded == spec

    def test_variables_parsed(self) -> None:
        spec = load_pipeline(FULL_YAML).spec
        assert spec is not None
        assert spec.variables["TARGET"].default == "main"
        assert spec.variables["REASON"].required is True
        assert spec.variables["REASON"].default is None

    def test_nested_parallel_children_parsed(self) -> None:
        spec = load_pipeline(FULL_YAML).spec
        assert spec is not None
        fanout = next(s for s in spec.steps if s.id == "fanout")
        assert fanout.parallel is not None
        assert [c.id for c in fanout.parallel] == ["impl-a", "impl-b"]
        assert fanout.parallel[0].agent == "myapp-implementer"


class TestUnknownKeyRejected:
    def test_unknown_top_level_key_rejected(self) -> None:
        result = load_pipeline(FULL_YAML + "\nnotARealField: 1\n")
        assert not result.ok
        assert any("notARealField" in e for e in result.errors)

    def test_unknown_step_key_rejected(self) -> None:
        text = "name: p\nsteps:\n  - s1: lead\n    bogus: yes\n"
        result = load_pipeline(text)
        assert not result.ok
        assert any("bogus" in e for e in result.errors)

    def test_unknown_gate_key_rejected(self) -> None:
        text = (
            "name: p\nsteps:\n  - s1: implementer\n"
            "    verify:\n      command: echo hi\n      wat: 1\n"
        )
        result = load_pipeline(text)
        assert not result.ok
        assert any("wat" in e for e in result.errors)

    def test_unknown_rework_key_rejected(self) -> None:
        with pytest.raises(ValidationError, match="bogus"):
            ReworkEdge.model_validate({"to": "build", "when": ["b"], "bogus": 1})

    def test_unknown_variable_key_rejected(self) -> None:
        text = "name: p\nvariables:\n  X:\n    default: 1\n    bogus: yes\nsteps:\n  - s1: lead\n"
        result = load_pipeline(text)
        assert not result.ok
        assert any("bogus" in e for e in result.errors)

    def test_pydantic_model_extra_forbid_directly(self) -> None:
        with pytest.raises(ValidationError):
            PipelineSpec.model_validate(
                {
                    "name": "p",
                    "steps": [{"id": "s1", "role": "lead"}],
                    "notAField": True,
                }
            )


class TestReworkBounds:
    def test_max_cycles_default_is_one(self) -> None:
        edge = ReworkEdge(to="build", when=["request-changes"])
        assert edge.max_cycles == 1

    def test_max_cycles_zero_disables_rework_but_still_valid(self) -> None:
        edge = ReworkEdge(to="build", when=["request-changes"], maxCycles=0)
        assert edge.max_cycles == 0

    def test_max_cycles_negative_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ReworkEdge(to="build", when=["request-changes"], maxCycles=-1)

    def test_empty_to_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ReworkEdge(to="   ", when=["request-changes"])

    def test_empty_when_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ReworkEdge(to="build", when=[])

    @staticmethod
    def _spec(*steps: dict[str, object]) -> PipelineSpec:
        return PipelineSpec.model_validate({"name": "p", "steps": list(steps)})

    @staticmethod
    def _review(to: str) -> dict[str, object]:
        return {
            "id": "review",
            "role": "reviewer",
            "gate": {
                "type": "verdict",
                "pattern": "^(A|R)",
                "passValues": ["a"],
                "rework": {"to": to, "when": ["r"]},
            },
        }

    def test_rework_target_must_exist(self) -> None:
        with pytest.raises(ValidationError, match=r"nope.*top-level step id"):
            self._spec({"id": "build", "role": "implementer"}, self._review("nope"))

    def test_rework_target_must_be_earlier(self) -> None:
        with pytest.raises(ValidationError, match="earlier step"):
            self._spec(self._review("build"), {"id": "build", "role": "implementer"})

    def test_rework_target_cannot_be_self(self) -> None:
        with pytest.raises(ValidationError, match="earlier step"):
            self._spec(self._review("review"))

    def test_rework_target_earlier_step_valid(self) -> None:
        self._spec({"id": "build", "role": "implementer"}, self._review("build"))

    def test_rework_inside_parallel_group_rejected(self) -> None:
        child = self._review("build") | {"id": "r1"}
        with pytest.raises(ValidationError, match="parallel"):
            self._spec(
                {"id": "build", "role": "implementer"}, {"id": "fanout", "parallel": [child]}
            )


class TestParallelGroups:
    def test_parallel_group_parses(self) -> None:
        spec = PipelineSpec.model_validate(
            {
                "name": "p",
                "steps": [
                    {
                        "id": "fanout",
                        "parallel": [
                            {"id": "a", "role": "implementer"},
                            {"id": "b", "role": "implementer"},
                        ],
                    }
                ],
            }
        )
        assert spec.steps[0].parallel is not None
        assert len(spec.steps[0].parallel) == 2

    def test_parallel_group_rejects_own_role(self) -> None:
        with pytest.raises(ValidationError):
            PipelineSpec.model_validate(
                {
                    "name": "p",
                    "steps": [
                        {
                            "id": "fanout",
                            "role": "implementer",
                            "parallel": [{"id": "a", "role": "implementer"}],
                        }
                    ],
                }
            )

    def test_parallel_group_rejects_own_gate(self) -> None:
        with pytest.raises(ValidationError):
            PipelineSpec.model_validate(
                {
                    "name": "p",
                    "steps": [
                        {
                            "id": "fanout",
                            "gate": {"type": "approval"},
                            "parallel": [{"id": "a", "role": "implementer"}],
                        }
                    ],
                }
            )

    def test_parallel_group_rejects_own_retries_timeout(self) -> None:
        with pytest.raises(ValidationError):
            PipelineSpec.model_validate(
                {
                    "name": "p",
                    "steps": [
                        {
                            "id": "fanout",
                            "retries": 1,
                            "parallel": [{"id": "a", "role": "implementer"}],
                        }
                    ],
                }
            )

    def test_parallel_group_must_be_non_empty(self) -> None:
        with pytest.raises(ValidationError):
            PipelineSpec.model_validate({"name": "p", "steps": [{"id": "fanout", "parallel": []}]})

    def test_nested_parallel_rejected(self) -> None:
        with pytest.raises(ValidationError):
            PipelineSpec.model_validate(
                {
                    "name": "p",
                    "steps": [
                        {
                            "id": "fanout",
                            "parallel": [
                                {
                                    "id": "inner",
                                    "parallel": [{"id": "a", "role": "implementer"}],
                                }
                            ],
                        }
                    ],
                }
            )

    def test_duplicate_id_across_parallel_children_rejected(self) -> None:
        text = (
            "name: p\nsteps:\n"
            "  - dup: lead\n"
            "  - fanout:\n      parallel:\n"
            "        - dup: implementer\n"
        )
        result = load_pipeline(text)
        assert not result.ok
        assert any("duplicate" in e for e in result.errors)

    def test_duplicate_id_between_two_parallel_children_rejected(self) -> None:
        text = (
            "name: p\nsteps:\n"
            "  - fanout:\n      parallel:\n"
            "        - same: implementer\n"
            "        - same: reviewer\n"
        )
        result = load_pipeline(text)
        assert not result.ok
        assert any("duplicate" in e for e in result.errors)


class TestVariables:
    def test_variable_with_default(self) -> None:
        v = Variable(default="main")
        assert v.default == "main"
        assert v.required is False

    def test_required_variable_no_default(self) -> None:
        v = Variable(required=True)
        assert v.default is None

    def test_required_variable_with_default_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Variable(required=True, default="main")

    def test_invalid_variable_identifier_rejected(self) -> None:
        text = "name: p\nvariables:\n  '1bad':\n    default: x\nsteps:\n  - s1: lead\n"
        result = load_pipeline(text)
        assert not result.ok
        assert any("1bad" in e for e in result.errors)

    def test_valid_variable_identifier_with_underscore(self) -> None:
        text = "name: p\nvariables:\n  _my_var:\n    default: x\nsteps:\n  - s1: lead\n"
        result = load_pipeline(text)
        assert result.ok, result.errors


class TestShortForm:
    def test_secure_build_short_form_expands_to_the_canonical_spec(self) -> None:
        canonical = PipelineSpec.model_validate(_SECURE_BUILD_CANONICAL)

        short_doc = yaml.safe_load(_SECURE_BUILD_SHORT)
        short_doc.pop("kind")
        normalized = normalize_pipeline(short_doc)
        assert PipelineSpec.model_validate(normalized) == canonical

        # load_pipeline itself accepts the short form end to end, `kind` included.
        assert load_pipeline(_SECURE_BUILD_SHORT).spec == canonical

    def test_a_step_written_in_the_canonical_form_is_refused_naming_the_short_form(self) -> None:
        result = load_pipeline("name: p\nsteps:\n  - id: plan\n    role: lead\n")

        assert not result.ok
        assert "'- plan: <role>'" in result.errors[0]

    def test_a_parallel_group_is_written_with_short_children(self) -> None:
        text = "name: p\nsteps:\n  - fan:\n      parallel:\n        - a: reviewer\n        - b: reviewer\n"

        spec = load_pipeline(text).spec

        assert spec is not None
        assert [c.id for c in spec.steps[0].parallel or []] == ["a", "b"]

    def test_a_verify_gate_carries_its_command_and_timeout(self) -> None:
        text = "name: p\nsteps:\n  - b: implementer\n    verify: {command: make, timeout: 30}\n"

        spec = load_pipeline(text).spec

        assert spec is not None
        assert spec.steps[0].gate == MechanicalGate(command="make", timeout=30)

    def test_backward_goto_without_max_names_the_step(self) -> None:
        text = _SECURE_BUILD_SHORT.replace(
            "on: {REQUEST-CHANGES: {goto: build, max: 1}}",
            "on: {REQUEST-CHANGES: {goto: build}}",
        )
        result = load_pipeline(text)
        assert not result.ok
        assert len(result.errors) == 1
        assert "vet" in result.errors[0]
        assert "max" in result.errors[0]


class TestCommandSteps:
    def test_run_step_loads_and_renders_gate_as_exit_code(self) -> None:
        spec = PipelineSpec(name="p", steps=[Step(id="check", run="false")])
        plan = _orch.resolve_plan(spec, {}, registry=_archetypes.load_registry())
        assert "run 'false' [gate: exit code]" in _orch.render_plan(plan)
