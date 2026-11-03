"""One hop's clock: the seconds of a single attempt, with the owner that declared them.

The work declares the size of one attempt: the pipeline step (``timeout``), then the pod
(``turnTimeoutS``). The machine only fills a gap. Rounds and tool calls are guards the machine
owns (``AGENT_LOOP_MAX_ITERATIONS``, ``AGENT_LOOP_MAX_TOOL_CALLS``), declared by no step, role or
task. Pure: the caller reads each layer and passes what it declared, or ``None``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from docket.kernel.errors import InvalidInput

Source = Literal["step", "pod", "default"]


@dataclass(frozen=True)
class Limit:
    """One resolved bound and the owner that declared it."""

    value: int
    source: Source


def resolve_seconds(*, step: int | None, pod: int | None, default: int) -> Limit:
    """The time chain, for the runner, which owns the clock: step, then pod, then machine. A
    declared value that is not positive is refused."""
    if step is not None:
        return Limit(_positive(step, "step"), "step")
    if pod is not None:
        return Limit(_positive(pod, "pod"), "pod")
    return Limit(default, "default")


def _positive(value: int, source: Source) -> int:
    if value <= 0:
        raise InvalidInput(f"a {source} budget must be a positive integer, got {value}")
    return value
