"""The addressable-task fields of an enqueue: shape and narrowing checks, no resolution.

``baseRef``, ``pipeline`` and ``prepare`` are resolved at claim, ``gate``, ``maxTokens``,
``restrictions`` and ``autonomy`` at hop time; this module only refuses what can never be valid or would widen a
pod's limits."""

from __future__ import annotations

from collections.abc import Callable, Collection
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, ValidationError

from docket.kernel.errors import InvalidInput
from docket.tasks.domain.parts import is_none
from docket.tasks.domain.state import Status

_GATE_LABELS = ("pass", "fail", "needs_human")
TASK_STATUSES = frozenset(status.value for status in Status)
_REF_MAX = 200


@dataclass(frozen=True)
class OptionRules:
    """What validating an option needs from outside the task domain, passed in as data.

    ``known_tools`` is the built-in tool names a restriction may deny; ``check_policy`` raises on a
    malformed task policy document; ``check_prepare`` returns a valid prepare command or raises
    ``ValueError``."""

    known_tools: Collection[str]
    check_policy: Callable[[Any], object]
    check_prepare: Callable[[object], str]


class TaskOptionsError(InvalidInput):
    """A task option has the wrong shape (HTTP 400)."""


class TaskRestrictionError(TaskOptionsError):
    """A task restriction would widen what the pod allows (HTTP 422)."""


class TaskGate(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    command: StrictStr = Field(min_length=1)
    timeout_s: StrictInt | None = Field(None, gt=0, alias="timeoutS", exclude_if=is_none)
    exit_map: dict[StrictStr, StrictStr] | None = Field(None, alias="map", exclude_if=is_none)


class TaskRestrictions(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    denied_tools: list[StrictStr] | None = Field(None, alias="deniedTools", exclude_if=is_none)
    network: StrictStr | None = Field(None, exclude_if=is_none)
    policies: list[dict[str, Any]] | None = Field(None, exclude_if=is_none)


class TaskOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    external_ref: StrictStr | None = Field(
        None, alias="externalRef", min_length=1, max_length=_REF_MAX
    )
    idempotency_key: StrictStr | None = Field(
        None, alias="idempotencyKey", min_length=1, max_length=_REF_MAX
    )
    base_ref: StrictStr | None = Field(None, alias="baseRef", min_length=1)
    pipeline: StrictStr | None = Field(None, min_length=1)
    gate: TaskGate | None = None
    max_tokens: StrictInt | None = Field(None, alias="maxTokens", gt=0)
    prepare: StrictStr | None = None
    restrictions: TaskRestrictions | None = None
    autonomy: Literal["L3", "L4", "L5"] | None = None


def _describe(exc: ValidationError) -> str:
    first = exc.errors()[0]
    where = ".".join(str(part) for part in first["loc"])
    return f"invalid {where}: {first['msg']}" if where else f"invalid task option: {first['msg']}"


def _check_gate(gate: TaskGate) -> None:
    if not gate.command.strip():
        raise TaskOptionsError("invalid gate.command: must not be blank")
    for code, label in (gate.exit_map or {}).items():
        if not code.isdigit():
            raise TaskOptionsError(f"invalid gate.map: exit code {code!r} is not a number")
        if label not in _GATE_LABELS:
            raise TaskOptionsError(
                f"invalid gate.map: label {label!r} is not one of {', '.join(_GATE_LABELS)}"
            )


def _check_restrictions(restrictions: TaskRestrictions, rules: OptionRules) -> None:
    if restrictions.network not in (None, "none"):
        raise TaskRestrictionError("restrictions.network may only be 'none' (open would widen)")
    known = set(rules.known_tools)
    for name in restrictions.denied_tools or []:
        if name not in known:
            raise TaskRestrictionError(
                f"restrictions.deniedTools: {name!r} is not a known tool ({', '.join(sorted(known))})"
            )
    for index, doc in enumerate(restrictions.policies or []):
        try:
            rules.check_policy(doc)
        except Exception as exc:
            raise TaskRestrictionError(f"restrictions.policies[{index}]: {exc}") from exc


def validate_task_options(
    *,
    rules: OptionRules,
    external_ref: Any = None,
    idempotency_key: Any = None,
    base_ref: Any = None,
    pipeline: Any = None,
    gate: Any = None,
    max_tokens: Any = None,
    prepare: Any = None,
    restrictions: Any = None,
    autonomy: Any = None,
) -> TaskOptions:
    """Validate the raw values (``None`` is unset) against *rules*; raises TaskOptionsError, or its
    subclass TaskRestrictionError for a restriction that would widen."""
    raw = {
        "externalRef": external_ref,
        "idempotencyKey": idempotency_key,
        "baseRef": base_ref,
        "pipeline": pipeline,
        "gate": gate,
        "maxTokens": max_tokens,
        "prepare": prepare,
        "restrictions": restrictions,
        "autonomy": autonomy,
    }
    try:
        options = TaskOptions.model_validate({k: v for k, v in raw.items() if v is not None})
    except ValidationError as exc:
        raise TaskOptionsError(_describe(exc)) from exc
    if options.pipeline is not None and not options.pipeline.strip():
        raise TaskOptionsError("invalid pipeline: must not be blank")
    if options.gate is not None:
        _check_gate(options.gate)
    if options.prepare is not None:
        try:
            rules.check_prepare(options.prepare)
        except ValueError as exc:
            raise TaskOptionsError(f"invalid prepare: {exc}") from exc
    if options.restrictions is not None:
        _check_restrictions(options.restrictions, rules)
    return options
