from __future__ import annotations

import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from docket.kernel.errors import InvalidInput

# ── Gates ──────────────────────────────────────────────────────────────────────


class ReworkEdge(BaseModel):
    """A bounded backward edge from a verdict gate to an earlier step. See
    specs/functional/pipeline-format.spec.md ("Rework edges") for the ``when``-not-``on``
    Norway-problem rationale and ``max_cycles: 0`` disabled-edge semantics."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    to: str
    when: list[str] = Field(default_factory=lambda: ["request-changes"])
    max_cycles: int = Field(1, alias="maxCycles", ge=0)

    @model_validator(mode="after")
    def _check(self) -> ReworkEdge:
        if not self.to.strip():
            raise InvalidInput("rework edge 'to' must name a step id")
        if not self.when:
            raise InvalidInput("rework edge 'when' must list at least one triggering verdict value")
        return self


class MechanicalGate(BaseModel):
    """Run a command; a nonzero exit fails the step. ``command: None`` defers to the target
    agent's own ``verifyCmd`` check instead of a literal command; see
    specs/functional/pipeline-format.spec.md ("Gates")."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["mechanical"] = "mechanical"
    command: str | None = None
    timeout: int | None = Field(None, gt=0)


class VerdictGate(BaseModel):
    """One distinct line-anchored marker matching ``pattern`` decides the step's outcome. See
    specs/functional/pipeline-format.spec.md ("Gates", the ``verdict`` kind) for the
    match/pass/rework/unparseable-fail rules."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    type: Literal["verdict"] = "verdict"
    pattern: str
    pass_values: list[str] = Field(alias="passValues")
    case_sensitive: bool = Field(False, alias="caseSensitive")
    rework: ReworkEdge | None = None

    @model_validator(mode="after")
    def _check(self) -> VerdictGate:
        if not self.pattern.strip():
            raise InvalidInput("verdict gate 'pattern' must not be empty")
        try:
            re.compile(self.pattern)
        except re.error as exc:
            raise InvalidInput(f"verdict gate 'pattern' is not a valid regex: {exc}") from exc
        if not self.pass_values:
            raise InvalidInput("verdict gate 'passValues' must list at least one passing value")
        norm = {v if self.case_sensitive else v.lower() for v in self.pass_values}
        if self.rework is not None:
            rework_when = {v if self.case_sensitive else v.lower() for v in self.rework.when}
            overlap = norm & rework_when
            if overlap:
                raise InvalidInput(
                    "verdict gate values cannot be both passing and rework-triggering: "
                    f"{sorted(overlap)}"
                )
        return self


class ApprovalGate(BaseModel):
    """The step must not proceed until an operator grants approval. Carries no
    token/timeout/resolution state -- ``hops/gates/pre_hop.py`` wires it to a real
    ``governance/approval.py`` record; see specs/functional/pipeline-format.spec.md ("Gates")."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["approval"] = "approval"
    message: str = ""


_EXTERNAL_LABELS = ("pass", "fail", "needs_human")
EXTERNAL_OUTCOMES = frozenset({"pass", "fail", "needs_human", "error"})


def _default_exit_map() -> dict[str, list[int]]:
    return {"pass": [0], "fail": [1], "needs_human": [2]}


class ExternalGate(BaseModel):
    """Run an operator command after the step's hop and map its exit code to ``pass``, ``fail``
    or ``needs_human`` (anything unmapped, a timeout, a jail refusal: ``error``). The member's
    ``verifyCmd`` is not run; see specs/functional/pipeline-format.spec.md ("Gates" item 5)."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    type: Literal["external"] = "external"
    command: str
    timeout: int | None = Field(None, gt=0)
    exit_map: dict[str, list[int]] = Field(default_factory=_default_exit_map, alias="exitMap")

    @model_validator(mode="after")
    def _check(self) -> ExternalGate:
        if not self.command.strip():
            raise InvalidInput("external gate 'command' must not be empty")
        if set(self.exit_map) != set(_EXTERNAL_LABELS):
            raise InvalidInput(
                f"external gate 'exitMap' must name exactly {list(_EXTERNAL_LABELS)}"
            )
        seen: dict[int, str] = {}
        for label in _EXTERNAL_LABELS:
            codes = self.exit_map[label]
            if not codes:
                raise InvalidInput(f"external gate 'exitMap' {label!r} must list at least one code")
            for code in codes:
                if code in seen:
                    raise InvalidInput(
                        f"external gate 'exitMap' code {code} is in both {seen[code]!r} "
                        f"and {label!r}"
                    )
                seen[code] = label
        return self

    def label_for(self, code: int) -> str:
        """The label *code* maps to, ``error`` when no list holds it."""
        for label in _EXTERNAL_LABELS:
            if code in self.exit_map[label]:
                return label
        return "error"


Gate = Annotated[
    MechanicalGate | VerdictGate | ApprovalGate | ExternalGate,
    Field(discriminator="type"),
]
