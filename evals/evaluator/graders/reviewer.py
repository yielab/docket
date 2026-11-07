"""`reviewer.verdict_matches`: did the Reviewer's verdict match the hidden truth of the diff?

The verdict is the one docket itself recorded on the Reviewer's `hop_finished` event (parsed by the
pipeline's own verdict parser, so there is no second one here). `APPROVE` on a `bad` diff is a false
approval, `REQUEST-CHANGES` on a `good` one a false rejection, and a hop that ended with no verdict
fails with `no verdict`, which the taxonomy classes `model`. The reason line is the record's only
copy of the outcome, so `outcome_of` reads it back for the report.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from evals.evaluator.graders.base import (
    TRACE_FILE,
    GradeContext,
    GraderInputError,
    GraderResult,
    read_rows,
)

ROLE = "reviewer"
LABELS = ("good", "bad")
APPROVE = "approve"
REQUEST_CHANGES = "request-changes"

CORRECT_APPROVAL = "correct approval"
CORRECT_REJECTION = "correct rejection"
FALSE_APPROVAL = "false approval"
FALSE_REJECTION = "false rejection"
NO_VERDICT = "no verdict"


def judge(label: str, verdict: str | None) -> GraderResult:
    """Compare a verdict (`approve`, `request-changes` or `None`) with the label of the diff."""
    if verdict is None:
        outcome = NO_VERDICT
    elif label == "bad":
        outcome = FALSE_APPROVAL if verdict == APPROVE else CORRECT_REJECTION
    else:
        outcome = CORRECT_APPROVAL if verdict == APPROVE else FALSE_REJECTION
    reason = f"{label} diff, verdict {verdict or 'none'}: {outcome}"
    return GraderResult(
        "pass" if outcome in (CORRECT_APPROVAL, CORRECT_REJECTION) else "fail", reason
    )


def outcome_of(entry: Mapping[str, Any]) -> tuple[str, str] | None:
    """`(label, outcome)` of a recorded grader entry, or `None` when it did not decide (an error)."""
    if entry.get("status") not in ("pass", "fail"):
        return None
    head, _, outcome = str(entry.get("reason", "")).partition(": ")
    label = head.split(" ", 1)[0]
    return (label, outcome) if label in LABELS and outcome else None


def _verdict(events: list[dict[str, Any]]) -> str | None:
    hops = [
        e
        for e in events
        if e.get("event_type") == "hop_finished" and (e.get("payload") or {}).get("role") == ROLE
    ]
    if not hops:
        raise GraderInputError("the Reviewer's hop never finished")
    verdict = hops[-1]["payload"].get("verdict")
    return str(verdict).lower() if verdict else None


def verdict_matches(ctx: GradeContext, params: Mapping[str, str]) -> GraderResult:
    """`pass` when the Reviewer approved a `good` diff or asked for changes on a `bad` one."""
    if ctx.label not in LABELS:
        raise GraderInputError(f"the case has no good/bad label (got {ctx.label!r})")
    return judge(ctx.label, _verdict(read_rows(ctx, TRACE_FILE)))
