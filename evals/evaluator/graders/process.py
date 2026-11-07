"""Process graders: what did the run cost? Report-only; each returns `pass` with a summary line."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping

from evals.evaluator.graders.base import (
    TRACE_FILE,
    GradeContext,
    GraderInputError,
    GraderResult,
    read_rows,
)

_BOUND_EVENTS = frozenset({"budget_exceeded"})


def tokens(ctx: GradeContext, params: Mapping[str, str]) -> GraderResult:
    """Measured tokens by role."""
    if ctx.tokens is None:
        raise GraderInputError("the record carries no tokens")
    parts = [f"{r} {t.get('input', 0)} in/{t.get('output', 0)} out" for r, t in ctx.tokens.items()]
    return GraderResult("pass", "; ".join(parts) or "no tokens measured")


def asks(ctx: GradeContext, params: Mapping[str, str]) -> GraderResult:
    """Approvals and questions the operator was asked."""
    if ctx.asks is None:
        raise GraderInputError("the record carries no asks")
    found = Counter(a.get("kind", "?") for a in ctx.asks)
    kinds = ", ".join(f"{k} {n}" for k, n in found.items())
    return GraderResult("pass", f"{len(ctx.asks)} asks" + (f": {kinds}" if kinds else ""))


def bound_stops(ctx: GradeContext, params: Mapping[str, str]) -> GraderResult:
    """Runs a bound stopped, counted in the trace."""
    stops = [e for e in read_rows(ctx, TRACE_FILE) if e.get("event_type") in _BOUND_EVENTS]
    return GraderResult("pass", f"{len(stops)} bound stops")


def time(ctx: GradeContext, params: Mapping[str, str]) -> GraderResult:
    """Wall-clock seconds."""
    if ctx.wall_s is None:
        raise GraderInputError("the record carries no wall time")
    return GraderResult("pass", f"{ctx.wall_s:.1f} s")
