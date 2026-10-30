from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from docket.kernel.errors import InvalidInput
from docket.kernel.ports import jail as _jail
from docket.pipeline.domain.gates import EXTERNAL_OUTCOMES, ExternalGate, Gate

_SLUG_RE = re.compile(r"^[a-z][a-z0-9_-]*$")

# `Step.model`'s two rank words (see model-profiles.spec.md); any other shape-valid value is
# a `<provider>/<id>` literal, whose *existence* against the provider catalog is a
# plan/dispatch-time concern, never this format's -- the same posture `archetype` takes.
_MODEL_RANKS = frozenset({"cheap", "strong"})


_DURATION_RE = re.compile(r"^([1-9][0-9]*)([smhd])$")
_DURATION_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


def parse_duration(text: str) -> int:
    """*text* (a positive integer and one unit ``s``, ``m``, ``h`` or ``d``) as seconds; a
    ``ValueError`` naming the accepted spelling for anything else."""
    found = _DURATION_RE.fullmatch(text) if isinstance(text, str) else None
    if found is None:
        raise InvalidInput(f"a duration is a positive count and a unit s, m, h or d (got {text!r})")
    return int(found.group(1)) * _DURATION_UNITS[found.group(2)]


def _is_slug(value: str) -> bool:
    return bool(_SLUG_RE.match(value))


def _is_model_literal(value: str) -> bool:
    provider, _sep, model_id = value.partition("/")
    return bool(provider) and bool(model_id)


# ── Steps ──────────────────────────────────────────────────────────────────────


class When(BaseModel):
    """A step's closed conditional-skip predicate vocabulary: ``changed``, ``var``/``is``,
    ``memberPresent``, ANDed together -- see specs/functional/pipeline-format.spec.md
    ("Conditional steps and command steps")."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    changed: str | None = None
    var: str | None = None
    is_: str | None = Field(None, alias="is")
    member_present: str | None = Field(None, alias="memberPresent")

    @model_validator(mode="after")
    def _check(self) -> When:
        if (self.var is None) != (self.is_ is None):
            raise InvalidInput("'when.var' and 'when.is' must be set together")
        if self.changed is None and self.var is None and self.member_present is None:
            raise InvalidInput(
                "'when' must set at least one of 'changed', 'var'+'is', 'memberPresent'"
            )
        return self


class InputSpec(BaseModel):
    """An operator-input step: the pipeline pauses and asks the operator a question."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    from_: str = Field(alias="from")
    message: str = ""
    expires_hours: int | None = Field(None, alias="expiresHours", gt=0)


class WaitUntil(BaseModel):
    """A wait step's probe: *run* is a command run every *every* until it exits ``0``."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    run: str
    every: str


_ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]*$")
_ENV_RESERVED = frozenset({"PATH", "BASH_ENV", "ENV"})
_ENV_RESERVED_PREFIXES = ("LD_", "PYTHON", "DOCKET_")


def _check_env(step_id: str, env: dict[str, str]) -> None:
    """Refuse an ``env`` entry that is malformed, loader/interpreter-controlling, a docket
    coordinate, or a name ``system.credential_names`` treats as a credential."""

    credentials = _jail.credential_names()
    for name, value in env.items():
        if not _ENV_NAME.match(name):
            raise InvalidInput(f"step {step_id!r}: env name {name!r} must match ^[A-Z][A-Z0-9_]*$")
        if name in _ENV_RESERVED or name.startswith(_ENV_RESERVED_PREFIXES):
            raise InvalidInput(f"step {step_id!r}: env name {name!r} is reserved and cannot be set")
        if name in credentials:
            raise InvalidInput(
                f"step {step_id!r}: env name {name!r} is a credential and cannot be set"
            )
        if not isinstance(value, str):
            raise InvalidInput(f"step {step_id!r}: env {name!r} must be a string")


class Step(BaseModel):
    """One node in the pipeline: a unit step (``role`` xor ``agent`` xor ``run`` xor ``input``)
    or a parallel group (unit-step children, one level deep). See
    specs/functional/pipeline-format.spec.md ("Steps", "Parallel groups", "Operator input")."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    id: str
    role: str | None = None
    agent: str | None = None
    archetype: str | None = None
    retries: int | None = Field(None, ge=0)
    timeout: int | None = Field(None, gt=0)
    gate: Gate | None = None
    # Overrides the target role's own hop instruction for this step only (its
    # archetype's `hopInstruction`/generated fallback, or a built-in role's
    # hardcoded text -- see role-archetypes.spec.md "Hop instructions"). May
    # reference `${var}`-style pipeline variables, resolved at dispatch time
    # (see "Variables" below); `None` means "defer to the role", not "no
    # instruction at all".
    instructions: str | None = None
    # Overrides the model this hop runs on, for this hop only -- `cheap`/`strong` (resolved
    # against the live rank anchors) or a `<provider>/<id>` literal. Never persisted to the
    # target agent's `.docket-meta.json`; see pod-dispatch.spec.md "Per-hop execution" and
    # model-profiles.spec.md "Where a member's model comes from". `None` means "defer to the target's
    # own policy/pin resolution", not "no model".
    model: str | None = None
    # Narrows what this hop is offered to these tool names, and bounds the calls it may make
    # (pipeline-format.spec.md "Steps" Req. 11); each overrides the archetype's own for this hop.
    tools: list[str] | None = None
    max_tool_calls: int | None = Field(None, alias="maxToolCalls", gt=0)
    # Skips this step on a closed predicate vocabulary (see `When`) -- applies to any
    # step kind, including a `run` command step. `None` means "always run".
    when: When | None = None
    # A command step's shell command, run directly with no agent turn, exclusive of
    # `role`/`agent` -- see the class docstring and "Conditional steps and command steps".
    run: str | None = None
    # Extra environment for a `run` step only (see `_check_env`); coordinates win over it.
    env: dict[str, str] | None = None
    # An operator-input step: pauses and asks for input, exclusive of role/agent/run.
    input: InputSpec | None = None
    # A wait step: parks the task for this duration, or until the `until` probe exits 0. Typed
    # loosely so a bare YAML number reaches `_check_wait`, whose error names the step.
    wait: Any = None
    until: WaitUntil | None = None
    parallel: list[Step] | None = None
    # Outcome routing: each key is a gate outcome label (a verdict marker, or
    # "pass"/"fail" for a mechanical gate), compared case-insensitively at
    # execution time. A value is either a mapping {"goto": <step id>, "max":
    # <int>=1} (mandatory "max" when the target is at or before this step) or
    # one of the literal strings "fail" | "stop" | "<step id>" (a bare forward
    # target). See specs/functional/pipeline-format.spec.md ("Outcome routing").
    on: dict[str, Any] | None = None

    def _check_hop_limits(self) -> None:
        """``tools`` names at least one tool, and only a step that runs an agent turn (a unit
        step or a child of a group) carries ``tools`` or ``maxToolCalls``."""
        if self.tools is not None and not [t for t in self.tools if t.strip()]:
            raise InvalidInput(f"step {self.id!r}: 'tools' must name at least one tool")
        if self.tools is None and self.max_tool_calls is None:
            return
        for kind, present in (
            ("parallel' group", self.parallel is not None),
            ("run' (command) step", self.run is not None),
            ("input' step", self.input is not None),
            ("wait' step", self.wait is not None),
        ):
            if present:
                raise InvalidInput(f"step {self.id!r}: a '{kind} carries no 'tools'/'maxToolCalls'")

    def _check_wait(self) -> Step:
        """A wait step: a duration, an optional probe, ``when`` and a ``timeout`` route only."""
        if self.wait is None:
            raise InvalidInput(f"step {self.id!r}: 'until' requires 'wait' (a duration)")
        try:
            parse_duration(self.wait)
        except ValueError as exc:
            raise InvalidInput(f"step {self.id!r}: 'wait' {exc}") from exc
        if self.until is not None:
            if not self.until.run.strip():
                raise InvalidInput(f"step {self.id!r}: 'until.run' must not be empty")
            try:
                parse_duration(self.until.every)
            except ValueError as exc:
                raise InvalidInput(f"step {self.id!r}: 'until.every' {exc}") from exc
        for field_name, value in (
            ("role", self.role),
            ("agent", self.agent),
            ("run", self.run),
            ("input", self.input),
            ("gate", self.gate),
            ("retries", self.retries),
            ("timeout", self.timeout),
            ("instructions", self.instructions),
            ("model", self.model),
            ("archetype", self.archetype),
            ("env", self.env),
        ):
            if value is not None:
                raise InvalidInput(f"step {self.id!r}: a 'wait' step carries no {field_name!r}")
        invalid = {str(k).lower() for k in self.on or {}} - {"timeout"}
        if invalid:
            raise InvalidInput(
                f"step {self.id!r}: a wait step's 'on' keys must be a subset of ['timeout']; "
                f"got invalid key(s): {sorted(invalid)}"
            )
        if self.on and self.until is None:
            raise InvalidInput(
                f"step {self.id!r}: 'on: timeout' needs 'until' (a timer alone never times out)"
            )
        return self

    def _check_group(self) -> None:
        """A ``parallel`` group: no hop fields of its own, and unit-step children with none of the
        step kinds a group cannot run."""
        assert self.parallel is not None
        if self.role is not None or self.agent is not None:
            raise InvalidInput(
                f"step {self.id!r}: a 'parallel' group targets no role/agent of its own"
            )
        if self.gate is not None:
            raise InvalidInput(f"step {self.id!r}: a 'parallel' group carries no gate of its own")
        if self.retries is not None or self.timeout is not None:
            raise InvalidInput(
                f"step {self.id!r}: a 'parallel' group carries no retries/timeout of its own"
            )
        if self.instructions is not None:
            raise InvalidInput(
                f"step {self.id!r}: a 'parallel' group carries no instructions of its own"
            )
        if self.model is not None:
            raise InvalidInput(f"step {self.id!r}: a 'parallel' group carries no model of its own")
        if self.on is not None:
            raise InvalidInput(
                f"step {self.id!r}: a 'parallel' group carries no outcome routing of its own"
            )
        if self.env is not None:
            raise InvalidInput(f"step {self.id!r}: a 'parallel' group carries no env of its own")
        for group_field, group_value in (
            ("run", self.run),
            ("input", self.input),
            ("when", self.when),
            ("archetype", self.archetype),
            ("wait", self.wait),
            ("until", self.until),
        ):
            if group_value is not None:
                raise InvalidInput(
                    f"step {self.id!r}: a 'parallel' group carries no {group_field!r} of its own"
                )
        if not self.parallel:
            raise InvalidInput(f"step {self.id!r}: 'parallel' must list at least one step")
        for child in self.parallel:
            for child_field, child_value in (
                ("run", child.run),
                ("input", child.input),
                ("when", child.when),
                ("on", child.on),
                ("wait", child.wait),
                ("until", child.until),
            ):
                if child_value is not None:
                    raise InvalidInput(
                        f"step {child.id!r}: a 'parallel' child carries no {child_field!r} "
                        "(a group runs its children as plain role/agent hops)"
                    )
            if child.parallel is not None:
                raise InvalidInput(
                    f"step {self.id!r}: nested 'parallel' groups are not supported "
                    f"(child {child.id!r} declares its own 'parallel')"
                )

    @model_validator(mode="after")
    def _check_shape(self) -> Step:
        if not self.id.strip():
            raise InvalidInput("step 'id' must not be empty")
        self._check_hop_limits()

        if self.archetype is not None and not _is_slug(self.archetype):
            raise InvalidInput(
                f"step {self.id!r}: 'archetype' must be a lowercase slug (got {self.archetype!r})"
            )

        if self.parallel is not None:
            self._check_group()
            return self

        if self.wait is not None or self.until is not None:
            return self._check_wait()

        if self.run is not None:
            if not self.run.strip():
                raise InvalidInput(f"step {self.id!r}: 'run' must not be empty")
            if self.input is not None:
                raise InvalidInput(f"step {self.id!r}: 'run' and 'input' are mutually exclusive")
            if self.env is not None:
                _check_env(self.id, self.env)
            if self.role is not None or self.agent is not None:
                raise InvalidInput(
                    f"step {self.id!r}: 'run' is exclusive of 'role'/'agent' "
                    "(a command step targets no member)"
                )
            for field_name, value in (
                ("gate", self.gate),
                ("instructions", self.instructions),
                ("retries", self.retries),
                ("archetype", self.archetype),
                ("model", self.model),
            ):
                if value is not None:
                    raise InvalidInput(
                        f"step {self.id!r}: a 'run' (command) step carries no {field_name!r}"
                    )
            return self

        if self.input is not None:
            if self.env is not None:
                raise InvalidInput(f"step {self.id!r}: an 'input' step carries no 'env'")
            for field_name, value in (
                ("role", self.role),
                ("agent", self.agent),
                ("run", self.run),
                ("parallel", self.parallel),
                ("gate", self.gate),
                ("retries", self.retries),
                ("timeout", self.timeout),
                ("instructions", self.instructions),
                ("model", self.model),
            ):
                if value is not None:
                    raise InvalidInput(
                        f"step {self.id!r}: an 'input' step carries no {field_name!r}"
                    )
            return self

        if self.env is not None:
            raise InvalidInput(f"step {self.id!r}: only a 'run' (command) step carries 'env'")
        if self.role is None and self.agent is None:
            raise InvalidInput(f"step {self.id!r}: must target exactly one of 'role' or 'agent'")
        if self.role is not None and self.agent is not None:
            raise InvalidInput(f"step {self.id!r}: 'role' and 'agent' are mutually exclusive")
        if self.role is not None and not _is_slug(self.role):
            raise InvalidInput(
                f"step {self.id!r}: 'role' must be a lowercase slug (got {self.role!r})"
            )
        if self.agent is not None and not self.agent.strip():
            raise InvalidInput(f"step {self.id!r}: 'agent' must not be empty")
        if (
            self.model is not None
            and self.model not in _MODEL_RANKS
            and not _is_model_literal(self.model)
        ):
            raise InvalidInput(
                f"step {self.id!r}: 'model' must be 'cheap', 'strong', or a "
                f"'<provider>/<id>' literal (got {self.model!r})"
            )
        if isinstance(self.gate, ExternalGate) and self.on:
            invalid = {str(k).lower() for k in self.on} - EXTERNAL_OUTCOMES
            if invalid:
                raise InvalidInput(
                    f"step {self.id!r}: an external gate's 'on' keys must be a subset of "
                    f"{sorted(EXTERNAL_OUTCOMES)}; got invalid key(s): {sorted(invalid)}"
                )
        return self
