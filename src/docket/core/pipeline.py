"""docket-native pipeline spec: the format only. ``core/orchestrator.py`` is the executor.
See specs/functional/pipeline-format.spec.md for the document shape, gate kinds, rework
edges, and parallel-group contract this module implements.

Zero-migration: ``load_pipeline(None)`` returns :func:`default_pipeline`, byte-equivalent to
``core/dispatch.py``'s hardcoded pipeline (drift-guarded by test, not hand-copied). This module
does not import ``dispatch`` itself, to stay decoupled from its heavier import chain -- the same
reason a step's ``archetype`` field validates only slug shape, never existence against the
archetype registry.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

_SLUG_RE = re.compile(r"^[a-z][a-z0-9_-]*$")
_VAR_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _is_slug(value: str) -> bool:
    return bool(_SLUG_RE.match(value))


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
            raise ValueError("rework edge 'to' must name a step id")
        if not self.when:
            raise ValueError("rework edge 'when' must list at least one triggering verdict value")
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
            raise ValueError("verdict gate 'pattern' must not be empty")
        try:
            re.compile(self.pattern)
        except re.error as exc:
            raise ValueError(f"verdict gate 'pattern' is not a valid regex: {exc}") from exc
        if not self.pass_values:
            raise ValueError("verdict gate 'passValues' must list at least one passing value")
        norm = {v if self.case_sensitive else v.lower() for v in self.pass_values}
        if self.rework is not None:
            rework_when = {v if self.case_sensitive else v.lower() for v in self.rework.when}
            overlap = norm & rework_when
            if overlap:
                raise ValueError(
                    "verdict gate values cannot be both passing and rework-triggering: "
                    f"{sorted(overlap)}"
                )
        return self


class ApprovalGate(BaseModel):
    """The step must not proceed until an operator grants approval. Carries no
    token/timeout/resolution state -- ``core/dispatch.py`` wires it to a real
    ``core/approval.py`` record; see specs/functional/pipeline-format.spec.md ("Gates")."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["approval"] = "approval"
    message: str = ""


Gate = Annotated[
    MechanicalGate | VerdictGate | ApprovalGate,
    Field(discriminator="type"),
]


# ── Steps ──────────────────────────────────────────────────────────────────────


class Step(BaseModel):
    """One node in the pipeline: a unit step (``role`` xor ``agent``, plus optional
    gate/retries/timeout) or a parallel group (``parallel``: unit-step children only, one
    level deep). See specs/functional/pipeline-format.spec.md ("Steps", "Parallel groups")."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    id: str
    role: str | None = None
    agent: str | None = None
    archetype: str | None = None
    retries: int | None = Field(None, ge=0)
    timeout: int | None = Field(None, gt=0)
    gate: Gate | None = None
    parallel: list[Step] | None = None

    @model_validator(mode="after")
    def _check_shape(self) -> Step:
        if not self.id.strip():
            raise ValueError("step 'id' must not be empty")
        if self.archetype is not None and not _is_slug(self.archetype):
            raise ValueError(
                f"step {self.id!r}: 'archetype' must be a lowercase slug (got {self.archetype!r})"
            )

        if self.parallel is not None:
            if self.role is not None or self.agent is not None:
                raise ValueError(
                    f"step {self.id!r}: a 'parallel' group targets no role/agent of its own"
                )
            if self.gate is not None:
                raise ValueError(f"step {self.id!r}: a 'parallel' group carries no gate of its own")
            if self.retries is not None or self.timeout is not None:
                raise ValueError(
                    f"step {self.id!r}: a 'parallel' group carries no retries/timeout of its own"
                )
            if not self.parallel:
                raise ValueError(f"step {self.id!r}: 'parallel' must list at least one step")
            for child in self.parallel:
                if child.parallel is not None:
                    raise ValueError(
                        f"step {self.id!r}: nested 'parallel' groups are not supported "
                        f"(child {child.id!r} declares its own 'parallel')"
                    )
            return self

        if self.role is None and self.agent is None:
            raise ValueError(f"step {self.id!r}: must target exactly one of 'role' or 'agent'")
        if self.role is not None and self.agent is not None:
            raise ValueError(f"step {self.id!r}: 'role' and 'agent' are mutually exclusive")
        if self.role is not None and not _is_slug(self.role):
            raise ValueError(
                f"step {self.id!r}: 'role' must be a lowercase slug (got {self.role!r})"
            )
        if self.agent is not None and not self.agent.strip():
            raise ValueError(f"step {self.id!r}: 'agent' must not be empty")
        return self


Step.model_rebuild()


# ── Variables ──────────────────────────────────────────────────────────────────


class Variable(BaseModel):
    """A pipeline variable: a default, or ``required`` for a value supplied at dispatch time
    (see :func:`resolve_variables`). No interpolation engine exists here -- this only
    declares the variable's shape; that stays an executor concern."""

    model_config = ConfigDict(extra="forbid")

    default: Any = None
    description: str = ""
    required: bool = False

    @model_validator(mode="after")
    def _check(self) -> Variable:
        if self.required and self.default is not None:
            raise ValueError("a required variable must not declare a default")
        return self


class VariableError(Exception):
    """Raised by :func:`resolve_variables` when a required variable has no value at all --
    neither a caller-supplied one nor a default, since a required variable is defined to
    have no default (see ``Variable._check``)."""


def resolve_variables(spec: PipelineSpec, provided: dict[str, Any] | None = None) -> dict[str, Any]:
    """Resolve *spec*'s variables against caller-supplied *provided*: present wins outright
    (even ``None``), else the ``default``; a missing ``required`` raises :class:`VariableError`
    naming every missing name at once. See specs/functional/pipeline-format.spec.md (Req. 4)."""
    values: dict[str, Any] = dict(provided or {})
    missing = sorted(
        name for name, var in spec.variables.items() if var.required and name not in values
    )
    if missing:
        raise VariableError("missing required pipeline variable(s): " + ", ".join(missing))
    for name, var in spec.variables.items():
        if name not in values:
            values[name] = var.default
    return values


# ── Pipeline ───────────────────────────────────────────────────────────────────


class PipelineSpec(BaseModel):
    """The docket-native pipeline format: ``extra="forbid"`` at every level makes an unknown
    key anywhere a validation error, never silently ignored. See
    specs/functional/pipeline-format.spec.md ("Purpose", Requirement 1) for why."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    name: str
    description: str = ""
    variables: dict[str, Variable] = Field(default_factory=dict)
    steps: list[Step]

    @model_validator(mode="after")
    def _check(self) -> PipelineSpec:
        if not self.name.strip():
            raise ValueError("pipeline 'name' must not be empty")
        if not self.steps:
            raise ValueError("pipeline 'steps' must not be empty")

        for var_name in self.variables:
            if not _VAR_NAME_RE.match(var_name):
                raise ValueError(f"variable {var_name!r} is not a valid identifier")

        all_ids: list[str] = []
        for s in self.steps:
            all_ids.append(s.id)
            if s.parallel:
                all_ids.extend(c.id for c in s.parallel)
        seen: set[str] = set()
        for sid in all_ids:
            if sid in seen:
                raise ValueError(f"duplicate step id {sid!r}")
            seen.add(sid)

        top_index = {s.id: i for i, s in enumerate(self.steps)}
        for i, s in enumerate(self.steps):
            if s.parallel:
                for child in s.parallel:
                    if isinstance(child.gate, VerdictGate) and child.gate.rework is not None:
                        raise ValueError(
                            f"step {child.id!r}: a rework edge inside a 'parallel' group "
                            "is not supported (target a top-level step instead)"
                        )
                continue
            if not isinstance(s.gate, VerdictGate) or s.gate.rework is None:
                continue
            rework = s.gate.rework
            if rework.to not in top_index:
                raise ValueError(
                    f"step {s.id!r}: rework target {rework.to!r} is not a top-level step id"
                )
            if top_index[rework.to] >= i:
                raise ValueError(
                    f"step {s.id!r}: rework target {rework.to!r} must be an earlier step"
                )
        return self


# ── Loading ────────────────────────────────────────────────────────────────────


@dataclass
class PipelineLoadResult:
    """Outcome of :func:`load_pipeline`: exactly one of ``spec``/``errors`` is meaningful --
    ``errors == []`` on success, ``spec is None`` on failure."""

    spec: PipelineSpec | None
    errors: list[str] = field(default_factory=list)
    source: str = "file"  # "file" | "builtin"

    @property
    def ok(self) -> bool:
        return self.spec is not None and not self.errors


def _load_yaml_text(text: str) -> tuple[dict[str, Any] | None, str]:
    """Parse YAML text; returns (doc, error), error == "" on success. Import stays guarded
    despite PyYAML being a declared dependency, so a stripped-down environment gets an
    actionable message instead of an unguarded traceback."""
    try:
        import yaml as _yaml  # type: ignore[import-untyped]
    except ImportError:
        return None, "PyYAML not installed — run: pip install pyyaml"
    try:
        doc = _yaml.safe_load(text)
    except Exception as exc:
        return None, f"YAML parse error: {exc}"
    if doc is None:
        return None, "pipeline document is empty"
    if not isinstance(doc, dict):
        return None, f"pipeline document must be a mapping (got {type(doc).__name__})"
    return doc, ""


def _format_validation_error(exc: ValidationError) -> list[str]:
    out: list[str] = []
    for e in exc.errors():
        loc = ".".join(str(p) for p in e["loc"]) if e["loc"] else "<root>"
        out.append(f"{loc}: {e['msg']}")
    return out


def load_pipeline(text: str | None) -> PipelineLoadResult:
    """Load a pipeline spec from YAML text. ``text is None`` is zero-migration (returns
    :func:`default_pipeline`); ``""`` is a real validation error, not zero-migration. See
    specs/functional/pipeline-format.spec.md ("Zero migration")."""
    if text is None:
        return PipelineLoadResult(spec=default_pipeline(), errors=[], source="builtin")

    doc, err = _load_yaml_text(text)
    if err:
        return PipelineLoadResult(spec=None, errors=[err], source="file")
    assert doc is not None
    try:
        spec = PipelineSpec.model_validate(doc)
    except ValidationError as exc:
        return PipelineLoadResult(spec=None, errors=_format_validation_error(exc), source="file")
    return PipelineLoadResult(spec=spec, errors=[], source="file")


def validate_pipeline(text: str) -> list[str]:
    """Structural validation only; returns [] on success. Thin wrapper over
    :func:`load_pipeline`, kept separate for callers that only want the error list."""
    return load_pipeline(text).errors


# Mirrors core/dispatch.py's Reviewer/Tester verdict conventions exactly —
# ``tests/unit/core/test_pipeline__spec.py`` cross-checks these two patterns
# and the role order below directly against ``dispatch.py``'s own constants,
# so this module's hardcoding one drift-guarded copy (rather than importing
# dispatch.py at runtime) is a deliberate, tested tradeoff — see the module
# docstring.
_REVIEWER_PATTERN = r"^\s*(APPROVE|REQUEST-CHANGES)\b"
_TESTER_PATTERN = r"^\s*(PASS|FAIL)\b"

# The literal default dispatch.py's pod_max_rework_cycles() falls back to
# when a pod's Lead has no maxReworkCycles meta set.
_DEFAULT_MAX_REWORK_CYCLES = 1


def default_pipeline() -> PipelineSpec:
    """The built-in zero-migration pipeline, equivalent to ``core/dispatch.py``'s hardcoded
    ``PIPELINE_ORDER``: lead -> implementer -> reviewer -> tester. See
    specs/functional/pipeline-format.spec.md ("Zero migration") for the exact gates/rework bound."""
    return PipelineSpec(
        name="default",
        description="Built-in lead -> implementer -> reviewer -> tester pipeline (zero migration).",
        steps=[
            Step(id="lead", role="lead"),
            Step(id="implementer", role="implementer", gate=MechanicalGate(command=None)),
            Step(
                id="reviewer",
                role="reviewer",
                gate=VerdictGate(
                    pattern=_REVIEWER_PATTERN,
                    pass_values=["approve"],
                    rework=ReworkEdge(
                        to="implementer",
                        when=["request-changes"],
                        max_cycles=_DEFAULT_MAX_REWORK_CYCLES,
                    ),
                ),
            ),
            Step(
                id="tester",
                role="tester",
                gate=VerdictGate(pattern=_TESTER_PATTERN, pass_values=["pass"]),
            ),
        ],
    )
