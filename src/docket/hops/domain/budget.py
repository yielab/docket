"""One hop's budget: the rounds, tool calls and seconds of a single attempt, each with its owner.

The work declares the size of one attempt: the pipeline step (``maxIterations``, ``maxToolCalls``,
``timeout``), then the role archetype (``maxIterations``, ``maxToolCalls``), then the pod
(``turnTimeoutS``, time only). The machine only fills a gap. Pure: the caller reads each layer
and passes what it declared, or ``None``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from docket.kernel.errors import InvalidInput

Source = Literal["step", "role", "pod", "default"]


@dataclass(frozen=True)
class Limit:
    """One resolved bound and the owner that declared it."""

    value: int
    source: Source


@dataclass(frozen=True)
class HopBudget:
    """The three per-hop bounds of one attempt. Tokens are the task's, never a hop's."""

    rounds: Limit
    tool_calls: Limit
    seconds: Limit


def _first(layers: tuple[tuple[int | None, Source], ...], default: int) -> Limit:
    for value, source in layers:
        if value is None:
            continue
        if value <= 0:
            raise InvalidInput(f"a {source} budget must be a positive integer, got {value}")
        return Limit(value, source)
    return Limit(default, "default")


def resolve_seconds(*, step: int | None, pod: int | None, default: int) -> Limit:
    """The time chain alone, for the runner, which owns the clock: step, then pod, then machine."""
    return _first(((step, "step"), (pod, "pod")), default)


def resolve_hop_budget(
    *,
    step_rounds: int | None = None,
    step_tool_calls: int | None = None,
    step_seconds: int | None = None,
    role_rounds: int | None = None,
    role_tool_calls: int | None = None,
    pod_seconds: int | None = None,
    default_rounds: int,
    default_tool_calls: int,
    default_seconds: int,
) -> HopBudget:
    """Resolve each bound on its own chain: step, then role, then pod (time only), then the
    machine default. A declared value that is not positive is refused."""
    return HopBudget(
        rounds=_first(((step_rounds, "step"), (role_rounds, "role")), default_rounds),
        tool_calls=_first(
            ((step_tool_calls, "step"), (role_tool_calls, "role")), default_tool_calls
        ),
        seconds=resolve_seconds(step=step_seconds, pod=pod_seconds, default=default_seconds),
    )
