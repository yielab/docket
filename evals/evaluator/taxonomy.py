"""Failure classes: the one place a trial that did not go cleanly is named (specs/test-framework.md).

`product` is a governance violation or an internal docket error, `model` a bound reached or a wrong
outcome, `harness` a grader that raised, an operator script with no answer or a truncated reply,
`infra` an endpoint that never answered. Only `model` and `product` count against anyone.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from evals.evaluator.operator import OperatorOutcome
from evals.evaluator.verify import HiddenResult

FAILURE_CLASSES = ("product", "model", "harness", "infra")
PRODUCT_KINDS = frozenset(
    {
        "stale_claim",
        "dispatch_refused",
        "prepare",
        "base_ref",
        "pipeline",
        "capability_missing",
        "gate_error",
    }
)
_GOVERNANCE = "governance.no_violation"


def classify(
    outcome: OperatorOutcome,
    stored: Mapping[str, Any],
    events: list[dict[str, Any]],
    verifier: HiddenResult,
    graded: Mapping[str, Mapping[str, Any]] | None = None,
) -> str | None:
    """The mechanical class of a trial that did not go cleanly, or `None`; *graded* is the record's
    `graders`. A required error is `harness`, a failed `governance.no_violation` is `product` and
    another required failure on a finished trial is `model`."""
    required = {n: g for n, g in (graded or {}).items() if g.get("required")}
    calls = [e["payload"] for e in events if e.get("event_type") == "llm_call"]
    if any(c.get("finishReason") == "length" for c in calls):
        return "harness"
    if outcome.unscripted or (outcome.status == "done" and verifier.status == "error"):
        return "harness"
    if any(g["status"] == "error" for g in required.values()):
        return "harness"
    if required.get(_GOVERNANCE, {}).get("status") == "fail":
        return "product"
    answered = any(c.get("ok") for c in calls)
    if outcome.stalled or outcome.timed_out:
        return "model" if answered and outcome.timed_out else "infra"
    if outcome.status == "done":
        failed = any(g["status"] == "fail" for g in required.values())
        return "model" if failed else None
    if not answered:
        return "infra"
    kind = str(stored.get("failureKind") or "")
    return "product" if kind in PRODUCT_KINDS else "model"
