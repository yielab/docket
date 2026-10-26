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

from docket.pipeline.domain.gates import ApprovalGate, MechanicalGate, ReworkEdge, VerdictGate
from docket.pipeline.domain.spec import (
    PipelineSpec,
)

SUBJECT = "docket.pipeline.domain.gates"


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
