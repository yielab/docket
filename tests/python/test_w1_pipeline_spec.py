"""W-1: docket-native pipeline spec.

``core/pipeline.py`` defines the format only — a Pydantic model for the YAML
dialect that ROADMAP Phase 16's W-2 executor will eventually run pods
through, replacing the Lobster dialect docket used to lint but could never
fully execute (retired by W-3, decision D-16). No executor exists yet; this
suite tests the model and its validation, not any dispatch behavior.

  * TestRoundTrip          — a valid, full-featured pipeline parses and
    round-trips through dump/validate unchanged.
  * TestUnknownKeyRejected  — ``extra="forbid"`` bites at every level (top,
    step, gate, rework edge, variable).
  * TestGateTypes           — mechanical/verdict/approval gates validate
    their own shape; verdict gates catch bad regexes, empty passValues, and
    passValues/rework overlap.
  * TestReworkBounds        — max_cycles must be >= 0; a rework edge must
    target an existing, earlier, top-level step id.
  * TestParallelGroups      — a parallel step parses, forbids its own
    role/agent/gate/retries/timeout, forbids nested parallel, and forbids a
    rework edge on one of its children.
  * TestVariables           — variable identifiers and required/default
    conflict.
  * TestStepTargeting       — role XOR agent, archetype shape, id shape.
  * TestZeroMigration       — ``load_pipeline(None)`` returns the built-in
    pipeline, drift-guarded against ``core/dispatch.py``'s own
    ``PIPELINE_ORDER`` and verdict regexes directly.
  * TestLoadPipeline        — YAML parse errors, empty/non-mapping
    documents, and the missing-PyYAML error path.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from docket.core import dispatch as _dispatch
from docket.core.pipeline import (
    ApprovalGate,
    MechanicalGate,
    PipelineSpec,
    ReworkEdge,
    Step,
    Variable,
    VerdictGate,
    default_pipeline,
    load_pipeline,
    validate_pipeline,
)

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
  - id: plan
    role: lead

  - id: build
    role: implementer
    retries: 2
    timeout: 600
    archetype: implementer
    gate:
      type: mechanical
      command: "make test"
      timeout: 300

  - id: review
    role: reviewer
    gate:
      type: verdict
      pattern: "^(APPROVE|REQUEST-CHANGES)\\\\b"
      passValues: [approve]
      rework:
        to: build
        when: [request-changes]
        maxCycles: 2

  - id: fanout
    parallel:
      - id: impl-a
        agent: myapp-implementer
      - id: impl-b
        agent: myapp-implementer-2

  - id: ship
    role: implementer
    gate:
      type: approval
      message: "Ready to deploy?"
"""


# ── TestRoundTrip ────────────────────────────────────────────────────────────


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

    def test_validate_pipeline_wrapper_matches_load(self) -> None:
        assert validate_pipeline(FULL_YAML) == []
        broken = FULL_YAML + "\nbogusTopLevelKey: true\n"
        assert validate_pipeline(broken) == load_pipeline(broken).errors
        assert validate_pipeline(broken) != []


# ── TestUnknownKeyRejected ───────────────────────────────────────────────────


class TestUnknownKeyRejected:
    def test_unknown_top_level_key_rejected(self) -> None:
        result = load_pipeline(FULL_YAML + "\nnotARealField: 1\n")
        assert not result.ok
        assert any("notARealField" in e for e in result.errors)

    def test_unknown_step_key_rejected(self) -> None:
        text = "name: p\nsteps:\n  - id: s1\n    role: lead\n    bogus: yes\n"
        result = load_pipeline(text)
        assert not result.ok
        assert any("bogus" in e for e in result.errors)

    def test_unknown_gate_key_rejected(self) -> None:
        text = (
            "name: p\nsteps:\n  - id: s1\n    role: implementer\n"
            "    gate:\n      type: mechanical\n      command: echo hi\n      wat: 1\n"
        )
        result = load_pipeline(text)
        assert not result.ok
        assert any("wat" in e for e in result.errors)

    def test_unknown_rework_key_rejected(self) -> None:
        text = (
            "name: p\nsteps:\n"
            "  - id: build\n    role: implementer\n"
            "  - id: review\n    role: reviewer\n"
            "    gate:\n      type: verdict\n      pattern: '^(A|B)'\n"
            "      passValues: [a]\n"
            "      rework:\n        to: build\n        when: [b]\n        bogus: 1\n"
        )
        result = load_pipeline(text)
        assert not result.ok
        assert any("bogus" in e for e in result.errors)

    def test_unknown_variable_key_rejected(self) -> None:
        text = (
            "name: p\nvariables:\n  X:\n    default: 1\n    bogus: yes\n"
            "steps:\n  - id: s1\n    role: lead\n"
        )
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


# ── TestGateTypes ────────────────────────────────────────────────────────────


class TestGateTypes:
    def test_mechanical_gate_minimal(self) -> None:
        gate = MechanicalGate()
        assert gate.command is None
        assert gate.type == "mechanical"

    def test_mechanical_gate_with_command(self) -> None:
        gate = MechanicalGate(command="pytest -q", timeout=120)
        assert gate.command == "pytest -q"

    def test_mechanical_gate_timeout_must_be_positive(self) -> None:
        with pytest.raises(ValidationError):
            MechanicalGate(timeout=0)

    def test_verdict_gate_minimal(self) -> None:
        gate = VerdictGate(pattern=r"^(PASS|FAIL)\b", passValues=["pass"])
        assert gate.rework is None
        assert gate.case_sensitive is False

    def test_verdict_gate_empty_pattern_rejected(self) -> None:
        with pytest.raises(ValidationError):
            VerdictGate(pattern="   ", passValues=["pass"])

    def test_verdict_gate_bad_regex_rejected(self) -> None:
        with pytest.raises(ValidationError):
            VerdictGate(pattern="(unclosed", passValues=["pass"])

    def test_verdict_gate_empty_pass_values_rejected(self) -> None:
        with pytest.raises(ValidationError):
            VerdictGate(pattern="^(PASS|FAIL)", passValues=[])

    def test_verdict_gate_pass_and_rework_overlap_rejected(self) -> None:
        with pytest.raises(ValidationError):
            VerdictGate(
                pattern="^(APPROVE|REQUEST-CHANGES)",
                passValues=["approve"],
                rework=ReworkEdge(to="build", when=["approve"]),
            )

    def test_verdict_gate_overlap_check_case_insensitive_by_default(self) -> None:
        with pytest.raises(ValidationError):
            VerdictGate(
                pattern="^(APPROVE|REQUEST-CHANGES)",
                passValues=["Approve"],
                rework=ReworkEdge(to="build", when=["APPROVE"]),
            )

    def test_approval_gate_minimal(self) -> None:
        gate = ApprovalGate()
        assert gate.type == "approval"
        assert gate.message == ""

    def test_approval_gate_with_message(self) -> None:
        gate = ApprovalGate(message="ship it?")
        assert gate.message == "ship it?"

    def test_gate_discriminated_by_type_field(self) -> None:
        spec = PipelineSpec.model_validate(
            {
                "name": "p",
                "steps": [
                    {
                        "id": "s1",
                        "role": "implementer",
                        "gate": {"type": "approval", "message": "go?"},
                    }
                ],
            }
        )
        assert isinstance(spec.steps[0].gate, ApprovalGate)

    def test_gate_unknown_type_rejected(self) -> None:
        with pytest.raises(ValidationError):
            PipelineSpec.model_validate(
                {
                    "name": "p",
                    "steps": [{"id": "s1", "role": "implementer", "gate": {"type": "psychic"}}],
                }
            )


# ── TestReworkBounds ─────────────────────────────────────────────────────────


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

    def _pipeline(self, review_gate_yaml: str) -> str:
        return f"name: p\nsteps:\n  - id: build\n    role: implementer\n{review_gate_yaml}"

    def test_rework_target_must_exist(self) -> None:
        text = self._pipeline(
            "  - id: review\n    role: reviewer\n"
            "    gate:\n      type: verdict\n      pattern: '^(A|R)'\n"
            "      passValues: [a]\n      rework:\n        to: nope\n        when: [r]\n"
        )
        result = load_pipeline(text)
        assert not result.ok
        assert any("nope" in e and "top-level step" in e for e in result.errors)

    def test_rework_target_must_be_earlier(self) -> None:
        text = (
            "name: p\nsteps:\n"
            "  - id: review\n    role: reviewer\n"
            "    gate:\n      type: verdict\n      pattern: '^(A|R)'\n"
            "      passValues: [a]\n      rework:\n        to: build\n        when: [r]\n"
            "  - id: build\n    role: implementer\n"
        )
        result = load_pipeline(text)
        assert not result.ok
        assert any("earlier step" in e for e in result.errors)

    def test_rework_target_cannot_be_self(self) -> None:
        text = (
            "name: p\nsteps:\n"
            "  - id: review\n    role: reviewer\n"
            "    gate:\n      type: verdict\n      pattern: '^(A|R)'\n"
            "      passValues: [a]\n      rework:\n        to: review\n        when: [r]\n"
        )
        result = load_pipeline(text)
        assert not result.ok
        assert any("earlier step" in e for e in result.errors)

    def test_rework_target_earlier_step_valid(self) -> None:
        text = self._pipeline(
            "  - id: review\n    role: reviewer\n"
            "    gate:\n      type: verdict\n      pattern: '^(A|R)'\n"
            "      passValues: [a]\n      rework:\n        to: build\n        when: [r]\n"
        )
        result = load_pipeline(text)
        assert result.ok, result.errors

    def test_rework_inside_parallel_group_rejected(self) -> None:
        text = (
            "name: p\nsteps:\n"
            "  - id: build\n    role: implementer\n"
            "  - id: fanout\n    parallel:\n"
            "      - id: r1\n        role: reviewer\n"
            "        gate:\n          type: verdict\n          pattern: '^(A|R)'\n"
            "          passValues: [a]\n"
            "          rework:\n            to: build\n            when: [r]\n"
        )
        result = load_pipeline(text)
        assert not result.ok
        assert any("parallel" in e for e in result.errors)


# ── TestParallelGroups ───────────────────────────────────────────────────────


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
            "  - id: dup\n    role: lead\n"
            "  - id: fanout\n    parallel:\n"
            "      - id: dup\n        role: implementer\n"
        )
        result = load_pipeline(text)
        assert not result.ok
        assert any("duplicate" in e for e in result.errors)

    def test_duplicate_id_between_two_parallel_children_rejected(self) -> None:
        text = (
            "name: p\nsteps:\n"
            "  - id: fanout\n    parallel:\n"
            "      - id: same\n        role: implementer\n"
            "      - id: same\n        role: reviewer\n"
        )
        result = load_pipeline(text)
        assert not result.ok
        assert any("duplicate" in e for e in result.errors)


# ── TestVariables ────────────────────────────────────────────────────────────


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
        text = (
            "name: p\nvariables:\n  '1bad':\n    default: x\nsteps:\n  - id: s1\n    role: lead\n"
        )
        result = load_pipeline(text)
        assert not result.ok
        assert any("1bad" in e for e in result.errors)

    def test_valid_variable_identifier_with_underscore(self) -> None:
        text = (
            "name: p\nvariables:\n  _my_var:\n    default: x\nsteps:\n  - id: s1\n    role: lead\n"
        )
        result = load_pipeline(text)
        assert result.ok, result.errors


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
        # W-1 deliberately does not know about W-6's archetype registry — any
        # shape-valid name is accepted, existing or not.
        step = Step(id="s1", role="implementer", archetype="some-archetype-that-does-not-exist")
        assert step.archetype == "some-archetype-that-does-not-exist"

    def test_duplicate_top_level_step_id_rejected(self) -> None:
        text = "name: p\nsteps:\n  - id: dup\n    role: lead\n  - id: dup\n    role: implementer\n"
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


# ── TestZeroMigration ────────────────────────────────────────────────────────


class TestZeroMigration:
    """Absence of a pipeline file MUST mean today's built-in dispatch order,
    byte-identical behavior — no separate migration step. Drift-guarded
    directly against ``core/dispatch.py``'s own constants rather than a
    hand-copied literal, so a future change to the real pipeline order or
    verdict conventions fails this suite instead of silently diverging.
    """

    def test_no_text_returns_builtin_source(self) -> None:
        result = load_pipeline(None)
        assert result.source == "builtin"
        assert result.ok

    def test_builtin_role_order_matches_dispatch_pipeline_order(self) -> None:
        spec = default_pipeline()
        assert tuple(s.role for s in spec.steps) == _dispatch.PIPELINE_ORDER

    def test_builtin_lead_has_no_gate(self) -> None:
        spec = default_pipeline()
        lead = next(s for s in spec.steps if s.id == "lead")
        assert lead.gate is None

    def test_builtin_implementer_gate_defers_to_verify_cmd(self) -> None:
        spec = default_pipeline()
        implementer = next(s for s in spec.steps if s.id == "implementer")
        assert isinstance(implementer.gate, MechanicalGate)
        assert implementer.gate.command is None

    def test_builtin_reviewer_pattern_matches_dispatch_regex(self) -> None:
        spec = default_pipeline()
        reviewer = next(s for s in spec.steps if s.id == "reviewer")
        assert isinstance(reviewer.gate, VerdictGate)
        assert reviewer.gate.pattern == _dispatch._REVIEWER_VERDICT_RE.pattern
        assert reviewer.gate.pass_values == ["approve"]

    def test_builtin_reviewer_rework_targets_implementer_default_one_cycle(self) -> None:
        spec = default_pipeline()
        reviewer = next(s for s in spec.steps if s.id == "reviewer")
        assert isinstance(reviewer.gate, VerdictGate)
        assert reviewer.gate.rework is not None
        assert reviewer.gate.rework.to == "implementer"
        assert reviewer.gate.rework.when == ["request-changes"]
        assert reviewer.gate.rework.max_cycles == 1

    def test_builtin_tester_pattern_matches_dispatch_regex(self) -> None:
        spec = default_pipeline()
        tester = next(s for s in spec.steps if s.id == "tester")
        assert isinstance(tester.gate, VerdictGate)
        assert tester.gate.pattern == _dispatch._TESTER_VERDICT_RE.pattern
        assert tester.gate.pass_values == ["pass"]

    def test_builtin_tester_has_no_rework(self) -> None:
        spec = default_pipeline()
        tester = next(s for s in spec.steps if s.id == "tester")
        assert isinstance(tester.gate, VerdictGate)
        assert tester.gate.rework is None

    def test_builtin_pipeline_itself_is_valid(self) -> None:
        # default_pipeline() must satisfy every validator PipelineSpec enforces
        # for a hand-authored file — it is not exempt from its own rules.
        dumped = default_pipeline().model_dump(by_alias=True)
        PipelineSpec.model_validate(dumped)  # raises on failure


# ── TestLoadPipeline ─────────────────────────────────────────────────────────


class TestLoadPipeline:
    def test_yaml_parse_error(self) -> None:
        result = load_pipeline("name: test\nsteps:\n  - {\n")
        assert not result.ok
        assert result.spec is None
        assert any("YAML parse error" in e for e in result.errors)

    def test_empty_document_is_an_error(self) -> None:
        result = load_pipeline("")
        assert not result.ok
        assert result.source == "file"

    def test_non_mapping_document_is_an_error(self) -> None:
        result = load_pipeline("- just\n- a\n- list\n")
        assert not result.ok
        assert any("mapping" in e for e in result.errors)

    def test_missing_name_rejected(self) -> None:
        result = load_pipeline("steps:\n  - id: s1\n    role: lead\n")
        assert not result.ok

    def test_missing_steps_rejected(self) -> None:
        result = load_pipeline("name: p\n")
        assert not result.ok

    def test_missing_pyyaml_gives_actionable_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        try:
            import yaml  # noqa: F401

            pytest.skip("PyYAML installed; cannot exercise the missing-PyYAML error path")
        except ImportError:
            pass
        result = load_pipeline("name: p\nsteps:\n  - id: s1\n    role: lead\n")
        assert not result.ok
        assert any("pyyaml" in e.lower() for e in result.errors)
