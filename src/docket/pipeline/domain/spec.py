"""docket-native pipeline spec: the format only. ``pipeline/domain/plan.py`` is the executor.
See specs/functional/pipeline-format.spec.md for the document shape, gate kinds, rework
edges, and parallel-group contract this module implements.

Zero-migration: ``load_pipeline(None)`` returns :func:`default_pipeline`, byte-equivalent to
``hops/application/steps.py``'s built-in pipeline order (drift-guarded by test, not hand-copied). This module
does not import ``dispatch`` itself, to stay decoupled from its heavier import chain -- the same
reason a step's ``archetype`` field validates only slug shape, never existence against the
archetype registry.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from docket.kernel.errors import InvalidInput
from docket.pipeline.domain.gates import (
    ExternalGate,
    MechanicalGate,
    ReworkEdge,
    VerdictGate,
)
from docket.pipeline.domain.short_form import _ShortFormError, normalize_pipeline
from docket.pipeline.domain.step import Step

_VAR_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


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
            raise InvalidInput("a required variable must not declare a default")
        return self


class VariableError(InvalidInput):
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


# ── Step instruction interpolation ──────────────────────────────────────────
#
# A step's own `instructions` (see the Step docstring) may reference
# `${var}`-style placeholders resolved from the run's variable namespace
# (`resolve_variables`'s own output, not this format's declared `variables`
# alone -- a caller-supplied name absent from `variables` still resolves).
# This is deliberately its own regex, not `string.Template`, so a literal `$`
# in prose (e.g. a dollar amount) is never mistaken for a placeholder --
# only the exact `${name}` spelling is ever substituted.

_STEP_VAR_REF_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _iter_step_instructions(steps: list[Step]) -> list[tuple[str, str]]:
    """(step_id, instructions) for every step (including parallel children)
    that declares one; a step with none is simply absent."""
    out: list[tuple[str, str]] = []
    for s in steps:
        if s.parallel:
            out.extend(_iter_step_instructions(s.parallel))
        elif s.instructions:
            out.append((s.id, s.instructions))
    return out


def step_instructions_by_id(spec: PipelineSpec) -> dict[str, str]:
    """Every step id (including parallel children) mapped to its own declared,
    not-yet-interpolated ``instructions`` text."""
    return dict(_iter_step_instructions(spec.steps))


def unresolved_step_variables(spec: PipelineSpec, variables: dict[str, Any]) -> list[str]:
    """Every ``${name}`` referenced in any step's ``instructions`` that *variables* does
    not resolve, deduplicated and sorted -- see specs/functional/pipeline-format.spec.md."""
    # The dispatch executor calls this once, up front, against the run's fully
    # resolved variable namespace, refusing the whole run before any hop when
    # the result is non-empty.
    missing: set[str] = set()
    for _step_id, text in _iter_step_instructions(spec.steps):
        for name in _STEP_VAR_REF_RE.findall(text):
            if name not in variables:
                missing.add(name)
    return sorted(missing)


def interpolate_instructions(text: str, variables: dict[str, Any]) -> str:
    """Substitute every ``${name}`` reference in *text* from *variables* (stringified).
    A reference *variables* does not resolve is left literal -- callers refuse the run up
    front via :func:`unresolved_step_variables` instead of relying on this to raise."""

    def _sub(match: re.Match[str]) -> str:
        name = match.group(1)
        return str(variables[name]) if name in variables else match.group(0)

    return _STEP_VAR_REF_RE.sub(_sub, text)


def _default_edge_reachable(step: Step) -> bool:
    """Whether *step*'s plain default-advance edge can still fire, i.e. its ``on`` map
    (if any) does not already name every one of its gate's own passing outcomes."""
    if not step.on:
        return True
    on_labels = {str(k).lower() for k in step.on}
    gate = step.gate
    if isinstance(gate, MechanicalGate):
        return not {"pass", "fail"} <= on_labels
    if isinstance(gate, VerdictGate):
        pass_labels = {v.lower() for v in gate.pass_values}
        return not pass_labels <= on_labels
    if isinstance(gate, ExternalGate):
        return "pass" not in on_labels
    return True


def _route_shape(step_id: str, label: str, route: Any) -> tuple[str, Any, bool]:
    """(target, max, has_max) for one ``on:`` entry -- *target* is ``"fail"``/``"stop"``/a
    step id; *route* is a bare target string or a ``{"goto": ..., "max": ...}`` mapping."""
    if isinstance(route, str):
        return route, None, False
    if (
        isinstance(route, dict)
        and isinstance(route.get("goto"), str)
        and not (set(route) - {"goto", "max"})
    ):
        return route["goto"], route.get("max"), "max" in route
    raise InvalidInput(f"step {step_id!r}: 'on' entry {label!r} is malformed")


def _check_input_from(step: Step, index: int, top_index: dict[str, int]) -> None:
    """Refuse an ``input`` step whose ``from`` is not a top-level step before *index*."""
    assert step.input is not None
    source = step.input.from_
    if source not in top_index:
        raise InvalidInput(f"step {step.id!r}: input 'from' references {source!r}, not a step id")
    if top_index[source] >= index:
        raise InvalidInput(f"step {step.id!r}: input 'from' {source!r} must be an earlier step")


def _check_input_keys(step: Step) -> None:
    valid_keys = frozenset({"answered", "declined"})
    invalid = {str(k).lower() for k in step.on or {}} - valid_keys
    if invalid:
        raise InvalidInput(
            f"step {step.id!r}: input step 'on' keys must be a subset of "
            f"{sorted(valid_keys)}; got invalid key(s): {sorted(invalid)}"
        )


def _check_routes(step: Step, index: int, top_index: dict[str, int]) -> None:
    """Validate every ``on`` entry of the top-level *step* at position *index*: the target,
    and ``max`` wherever it is written, an integer ``>= 1`` and required when the target is
    not ahead."""
    for label, route in (step.on or {}).items():
        target, max_value, has_max = _route_shape(step.id, label, route)
        valid_max = (
            isinstance(max_value, int) and not isinstance(max_value, bool) and max_value >= 1
        )
        if has_max and not valid_max:
            raise InvalidInput(
                f"step {step.id!r}: 'on' entry {label!r} has an invalid 'max' "
                f"{max_value!r} (an integer >= 1)"
            )
        if target in ("fail", "stop"):
            continue
        if target not in top_index:
            raise InvalidInput(f"step {step.id!r}: 'on' target {target!r} is not a step id")
        if top_index[target] <= index and not has_max:
            raise InvalidInput(
                f"step {step.id!r}: backward or self route to {target!r} requires 'max' >= 1"
            )


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
            raise InvalidInput("pipeline 'name' must not be empty")
        if not self.steps:
            raise InvalidInput("pipeline 'steps' must not be empty")

        for var_name in self.variables:
            if not _VAR_NAME_RE.match(var_name):
                raise InvalidInput(f"variable {var_name!r} is not a valid identifier")

        all_ids: list[str] = []
        for s in self.steps:
            all_ids.append(s.id)
            if s.parallel:
                all_ids.extend(c.id for c in s.parallel)
        seen: set[str] = set()
        for sid in all_ids:
            if sid in seen:
                raise InvalidInput(f"duplicate step id {sid!r}")
            seen.add(sid)

        top_index = {s.id: i for i, s in enumerate(self.steps)}
        for i, s in enumerate(self.steps):
            if s.parallel:
                for child in s.parallel:
                    if isinstance(child.gate, VerdictGate) and child.gate.rework is not None:
                        raise InvalidInput(
                            f"step {child.id!r}: a rework edge inside a 'parallel' group "
                            "is not supported (target a top-level step instead)"
                        )
                continue
            if s.input is not None:
                _check_input_from(s, i, top_index)
                _check_input_keys(s)
                continue
            if not isinstance(s.gate, VerdictGate) or s.gate.rework is None:
                continue
            rework = s.gate.rework
            if rework.to not in top_index:
                raise InvalidInput(
                    f"step {s.id!r}: rework target {rework.to!r} is not a top-level step id"
                )
            if top_index[rework.to] >= i:
                raise InvalidInput(
                    f"step {s.id!r}: rework target {rework.to!r} must be an earlier step"
                )

        for i, s in enumerate(self.steps):
            if s.parallel or not s.on:
                continue
            _check_routes(s, i, top_index)
            for label, route in s.on.items():
                target, _max_value, _has_max = _route_shape(s.id, label, route)
                if target in ("fail", "stop"):
                    continue
                nxt = self.steps[i + 1] if i + 1 < len(self.steps) else None
                # Only where `pass` is the gate's ordinary success; a verdict gate names its
                # passing values itself and may route every real one.
                if (
                    nxt is not None
                    and nxt.input is not None
                    and target == nxt.id
                    and isinstance(s.gate, (MechanicalGate, ExternalGate))
                    and "pass" not in {str(k).lower() for k in s.on}
                ):
                    raise InvalidInput(
                        f"step {s.id!r} routes {label!r} to the input step {target!r} right after "
                        "it, so a passing outcome would enter it too; route 'pass' explicitly "
                        "(for example 'pass: stop', or the step that should follow)"
                    )

        reachable = {0}
        frontier = [0]
        while frontier:
            i = frontier.pop()
            targets: set[int] = set()
            step = self.steps[i]
            if i + 1 < len(self.steps) and _default_edge_reachable(step):
                targets.add(i + 1)
            if not step.parallel and step.on:
                for label, route in step.on.items():
                    target, _max_value, _has_max = _route_shape(step.id, label, route)
                    if target in top_index:
                        targets.add(top_index[target])
            for t in targets:
                if t not in reachable:
                    reachable.add(t)
                    frontier.append(t)
        for i, s in enumerate(self.steps):
            if i not in reachable:
                raise InvalidInput(f"step {s.id!r} is not reachable")
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
    if "kind" in doc:
        kind = doc["kind"]
        if kind != "pipeline":
            return PipelineLoadResult(
                spec=None,
                errors=[f"pipeline document: 'kind' must be 'pipeline' (got {kind!r})"],
                source="file",
            )
        doc = {k: v for k, v in doc.items() if k != "kind"}
    try:
        doc = normalize_pipeline(doc)
    except _ShortFormError as exc:
        return PipelineLoadResult(spec=None, errors=[str(exc)], source="file")
    try:
        spec = PipelineSpec.model_validate(doc)
    except ValidationError as exc:
        return PipelineLoadResult(spec=None, errors=_format_validation_error(exc), source="file")
    return PipelineLoadResult(spec=spec, errors=[], source="file")


# Mirrors the Reviewer/Tester verdict conventions of the built-in archetypes exactly —
# ``tests/unit/pipeline/domain/test_spec__spec.py`` cross-checks these two patterns
# and the role order below directly against the archetype registry and
# ``hops/application/steps.py``'s ``PIPELINE_ORDER``,
# so this module's hardcoding one drift-guarded copy (rather than importing
# the executor at runtime) is a deliberate, tested tradeoff — see the module
# docstring.
_REVIEWER_PATTERN = r"^\s*(APPROVE|REQUEST-CHANGES)\b"
_TESTER_PATTERN = r"^\s*(PASS|FAIL)\b"

# The literal default teams/settings.py's pod_max_rework_cycles() falls back to
# when a pod's Lead has no maxReworkCycles meta set.
_DEFAULT_MAX_REWORK_CYCLES = 1


def default_pipeline() -> PipelineSpec:
    """The built-in zero-migration pipeline, equivalent to ``hops/application/steps.py``'s
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
