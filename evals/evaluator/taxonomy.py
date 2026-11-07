"""Failure classes: the one place a trial that did not go cleanly is named (specs/test-framework.md).

`product` is a governance violation docket let happen or an internal docket error (a breach the
gate refused is the model's), `model` a bound reached or a wrong
outcome, `harness` a grader that raised, an operator script with no answer or a truncated reply,
`infra` an endpoint that never answered. Only `model` and `product` count against anyone.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from evals.evaluator.graders.governance import REFUSED_BREACH
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
    `graders`. A required error is `harness`, a failed `governance.no_violation` is `product` (a breach
    the gate refused is `model`: the guard held) and
    another required failure on a finished trial is `model`."""
    required = {n: g for n, g in (graded or {}).items() if g.get("required")}
    calls = [e["payload"] for e in events if e.get("event_type") == "llm_call"]
    if any(c.get("finishReason") == "length" for c in calls):
        return "harness"
    if outcome.unscripted or (outcome.status == "done" and verifier.status == "error"):
        return "harness"
    if any(g["status"] == "error" for g in required.values()):
        return "harness"
    governance = required.get(_GOVERNANCE, {})
    if governance.get("status") == "fail":
        # A breach the gate refused is the model's attempt; docket failed only if a rule broke.
        return (
            "model" if str(governance.get("reason", "")).startswith(REFUSED_BREACH) else "product"
        )
    if required and all(g["status"] == "pass" for g in required.values()):
        return None
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
