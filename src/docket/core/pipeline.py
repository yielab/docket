"""docket-native pipeline spec (ROADMAP Phase 16, W-1).

This module defines the **format**, not an executor. `core/dispatch.py`'s
hardcoded ``PIPELINE_ORDER`` (lead -> implementer -> reviewer -> tester) keeps
driving every pod today; nothing here is wired into it yet. That wiring —
running a ``PipelineSpec`` over the R-1 task state machine, a bounded worker
pool, per-step trace spans, and a real ``docket workflow plan`` renderer — is
ROADMAP Phase 16 card W-2, deliberately **not** built here (see that card's
note: a second pretty-printer that drifts from the real executor is exactly
what ROADMAP warns against).

Zero-migration contract: a pod with **no** pipeline file MUST behave exactly
as it does today. ``load_pipeline(None)`` returns :func:`default_pipeline`
— a ``PipelineSpec`` equivalent to ``core/dispatch.py``'s hardcoded pipeline
(same role order, same verdict conventions, same default rework bound) — so a
caller that always goes through this loader never needs a separate "is there
a file" branch of its own to get wrong. (The literal equivalence is drift-
guarded by ``tests/python/test_w1_pipeline_spec.py``, which cross-checks
against ``dispatch.PIPELINE_ORDER`` and the Reviewer/Tester verdict regexes
directly — this module does not import ``dispatch`` itself, to keep a pure
format module decoupled from the heavier dispatch/ACL import chain.)

Steps target a **role** or a specific **agent** (mutually exclusive), and may
carry an optional ``archetype`` — a plain string name referencing a ROADMAP
Phase 16 W-6 role archetype. Only the *shape* of that name is validated here
(a lowercase slug) — never its existence against some registry, so this card
composes with W-6 without depending on its code landing first.

A step's ``gate`` is one of three kinds:

- ``mechanical`` — run a command; nonzero exit fails the step. ``command:
  None`` defers to the target agent's own configured check (today's
  Implementer ``verifyCmd`` meta field — see docket-meta.spec.md) rather than
  a literal command in the pipeline file, which is what lets
  :func:`default_pipeline` express today's exact behavior.
- ``verdict`` — match the first non-blank line of the step's output against a
  regex; a matched value in ``passValues`` advances the pipeline. Generalizes
  ``dispatch.py``'s Reviewer (APPROVE/REQUEST-CHANGES) and Tester (PASS/FAIL)
  conventions to an arbitrary marker vocabulary. May carry a bounded
  ``rework`` edge (see :class:`ReworkEdge`) — R-4's semantics, generalized
  past "always the Reviewer, always back to the Implementer".
- ``approval`` — the step must not proceed until an operator grants it via
  docket's existing headless approval channels (see security-gates.spec.md).
  Wiring a pipeline step to that store is Phase 15 G-1 / W-2's job.

``parallel`` groups let a step fan out into concurrently-run child steps
(e.g. one per ``--count N`` duplicate role member) — the model can express
this today even though no executor runs it yet. Exactly one level of nesting
is supported; join semantics for a group, and rework edges declared inside
one, are executor concerns this module deliberately does not model.
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
    """A bounded backward edge from a verdict gate to an earlier step (R-4).

    Mirrors ``core/dispatch.py``'s Reviewer -> Implementer rework loop: while
    a value in ``when`` keeps being the verdict, the pipeline jumps back to
    ``to`` up to ``max_cycles`` times before the verdict becomes a terminal
    failure. ``max_cycles: 0`` disables rework entirely — the gate becomes a
    hard block, matching ``dispatch.py``'s Tester gate today (no ``rework``
    at all is the same as ``max_cycles: 0``, just without the edge existing).

    Deliberately named ``when``, not ``on``: YAML 1.1's implicit-boolean
    resolver (the one PyYAML's ``safe_load`` implements) turns a bare ``on:``
    key into the boolean ``True`` unless it's quoted — the same "Norway
    problem" that bit GitHub Actions' top-level ``on:``. Using ``when``
    sidesteps the trap entirely rather than requiring every pipeline author
    to remember to quote a key.
    """

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
    """Run a command; a nonzero exit fails the step.

    ``command: None`` defers to the target agent's own configured check
    rather than a literal command in the pipeline file — see the module
    docstring.
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal["mechanical"] = "mechanical"
    command: str | None = None
    timeout: int | None = Field(None, gt=0)


class VerdictGate(BaseModel):
    """Match the step output's first non-blank line against ``pattern``.

    ``pattern``'s first capturing group is the verdict marker, compared
    (case-insensitively unless ``case_sensitive``) against ``pass_values``. A
    match in ``pass_values`` advances the pipeline; a match named in
    ``rework.when`` (if ``rework`` is set) triggers a bounded rework cycle;
    anything else — including no match at all (unparseable output) — fails
    the step. Unparseable output is never given a rework cycle, matching
    ``dispatch.py``'s explicit fail-vs-unparseable distinction for both its
    Reviewer and Tester gates.
    """

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
    """The step must not proceed until an operator grants approval.

    Deliberately minimal — wiring this to docket's approval store (tokens,
    timeout-resolves-to-denied, CLI/HTTP grant/deny) is Phase 15 G-1 / W-2's
    job, not this card's. ``message`` is optional context shown to the
    approver.
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal["approval"] = "approval"
    message: str = ""


Gate = Annotated[
    MechanicalGate | VerdictGate | ApprovalGate,
    Field(discriminator="type"),
]


# ── Steps ──────────────────────────────────────────────────────────────────────


class Step(BaseModel):
    """One node in the pipeline.

    A **unit step** targets exactly one of ``role`` (a pod role / W-6
    archetype slot, e.g. ``implementer``) or ``agent`` (a specific agent id,
    e.g. ``myapp-implementer-2``) and may carry ``retries``/``timeout``
    overrides and a ``gate``.

    A **parallel group** step sets ``parallel`` to a list of unit steps that
    run concurrently (e.g. one per ``--count N`` duplicate role member) and
    carries no role/agent/gate/retries/timeout of its own — only its children
    do. Nesting is limited to one level: a child step must not itself declare
    ``parallel``.
    """

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
    """A pipeline variable: a default value, or ``required`` for one supplied
    at dispatch time (e.g. a future W-4 webhook param). No interpolation
    engine exists here — that belongs to the executor (W-2); this only
    declares the variable's shape.
    """

    model_config = ConfigDict(extra="forbid")

    default: Any = None
    description: str = ""
    required: bool = False

    @model_validator(mode="after")
    def _check(self) -> Variable:
        if self.required and self.default is not None:
            raise ValueError("a required variable must not declare a default")
        return self


# ── Pipeline ───────────────────────────────────────────────────────────────────


class PipelineSpec(BaseModel):
    """The docket-native pipeline format (ROADMAP Phase 16 W-1).

    ``extra="forbid"`` at every level is the point: an unknown key anywhere
    in the document is a validation error, not a silently-ignored construct
    (unlike ``core/lobster.py``'s Lobster validator, which is exactly the gap
    ROADMAP decision D-16 retires this format to close).
    """

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
    """Outcome of :func:`load_pipeline`. Exactly one of ``spec``/``errors`` is
    meaningful — a successful load has ``errors == []``; a failed one has
    ``spec is None``.
    """

    spec: PipelineSpec | None
    errors: list[str] = field(default_factory=list)
    source: str = "file"  # "file" | "builtin"

    @property
    def ok(self) -> bool:
        return self.spec is not None and not self.errors


def _load_yaml_text(text: str) -> tuple[dict[str, Any] | None, str]:
    """Parse YAML text. Returns (doc, error); error is '' on success.

    Mirrors ``core/lobster.py``'s ``_load`` — PyYAML is a real project
    dependency (``pyproject.toml``), but the import stays guarded so a
    stripped-down environment missing it fails with an actionable message
    instead of an unguarded traceback.
    """
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
    """Load a pipeline spec from YAML text.

    ``text is None`` is the zero-migration case — no pipeline file exists for
    this pod — and returns :func:`default_pipeline` (``source="builtin"``)
    rather than an error, so a caller that always routes through this loader
    gets today's exact behavior with no separate "file missing" branch to
    maintain on its own. Passing ``""`` (an existing-but-empty file) is
    treated as a real, invalid document — not the zero-migration case.
    """
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
    """Structural validation only. Returns [] on success.

    A thin wrapper over :func:`load_pipeline` mirroring
    ``core/lobster.py``'s ``validate_lobster`` contract for symmetry.
    """
    return load_pipeline(text).errors


# Mirrors core/dispatch.py's Reviewer/Tester verdict conventions exactly —
# ``tests/python/test_w1_pipeline_spec.py`` cross-checks these two patterns
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
    """The built-in pipeline equivalent to ``core/dispatch.py``'s hardcoded
    ``PIPELINE_ORDER`` — the zero-migration contract.

    Lead (no gate) -> Implementer (mechanical check, deferring to its own
    ``verifyCmd`` meta) -> Reviewer (APPROVE/REQUEST-CHANGES verdict, bounded
    rework back to Implementer, default 1 cycle) -> Tester (PASS/FAIL
    verdict, hard gate, no rework). A pod that only has Lead + Implementer
    (the lean default) simply never reaches the later steps at dispatch time
    — which roles a pod actually has is a runtime/executor concern, not this
    spec's (see ``core/dispatch.py``'s ``pod_pipeline``, which already skips
    absent roles).
    """
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
