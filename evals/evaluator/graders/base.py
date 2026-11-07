"""What a grader receives and returns; the registry in `__init__` and the three families share it."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from evals.evaluator.verify import HiddenResult

Status = Literal["pass", "fail", "error"]
TRACE_FILE = "trace.jsonl"
AUDIT_FILE = "audit.jsonl"


class GraderInputError(Exception):
    """A grader's input is absent or unreadable: the harness, not the agent, is at fault."""


@dataclass(frozen=True)
class GraderResult:
    """`pass`, `fail` or `error`, with one line of reason."""

    status: Status
    reason: str


@dataclass(frozen=True)
class GradeContext:
    """The evidence of one trial, as plain values. Every field is optional: a grader that needs
    one that is missing returns `error`. `frozen` holds the trace and audit files; `world` and
    `head_before` are the live world, present only while a trial runs; `label` is `good` or `bad`."""

    frozen: Path | None = None
    pod: str = ""
    status: str | None = None
    statuses: Sequence[str] = ()
    verifier: HiddenResult | None = None
    repo: Path | None = None
    tokens: Mapping[str, Mapping[str, int]] | None = None
    asks: Sequence[Mapping[str, str]] | None = None
    wall_s: float | None = None
    world: Any = None
    head_before: str | None = None
    check_checkout: bool = False
    label: str | None = None


def read_rows(ctx: GradeContext, name: str) -> list[dict[str, Any]]:
    """The JSON lines of `frozen/<name>`; `GraderInputError` when the file is absent."""
    if ctx.frozen is None:
        raise GraderInputError(f"no frozen evidence directory for {name}")
    path = ctx.frozen / name
    if not path.is_file():
        raise GraderInputError(f"{name} is absent from the frozen evidence")
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
