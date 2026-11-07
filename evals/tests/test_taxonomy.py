"""SUBJECT: evals/evaluator/taxonomy.py -- one function names why a trial failed, from the operator's
outcome, the stored task, the trace, the verifier and the graders' results."""

from __future__ import annotations

from typing import Any

from evals.evaluator.operator import OperatorOutcome
from evals.evaluator.taxonomy import classify
from evals.evaluator.verify import HiddenResult

CLEAN = HiddenResult("pass", 0, "")
CALL: dict[str, Any] = {"event_type": "llm_call", "payload": {"ok": True, "finishReason": "stop"}}


def _graded(**results: str) -> dict[str, dict[str, Any]]:
    return {
        n.replace("__", "."): {"status": s, "reason": "", "required": True}
        for n, s in results.items()
    }


def test_a_clean_done_trial_has_no_class() -> None:
    assert (
        classify(OperatorOutcome("done"), {}, [CALL], CLEAN, _graded(outcome__task_status="pass"))
        is None
    )
    assert classify(OperatorOutcome("done"), {}, [CALL], CLEAN) is None


def test_a_required_grader_error_is_harness() -> None:
    graded = _graded(outcome__hidden_tests="error", governance__no_violation="fail")
    assert classify(OperatorOutcome("done"), {}, [CALL], CLEAN, graded) == "harness"


def test_a_required_fail_on_an_otherwise_clean_trial_is_a_wrong_outcome_by_the_model() -> None:
    graded = _graded(outcome__hidden_tests="fail", process__tokens="pass")
    assert classify(OperatorOutcome("done"), {}, [CALL], CLEAN, graded) == "model"


def test_a_failed_governance_grader_is_product_even_when_the_outcome_also_failed() -> None:
    graded = _graded(outcome__hidden_tests="fail", governance__no_violation="fail")
    assert classify(OperatorOutcome("done"), {}, [CALL], CLEAN, graded) == "product"


def test_a_report_only_failure_does_not_class_the_trial() -> None:
    graded = {"process.time": {"status": "fail", "reason": "", "required": False}}
    assert classify(OperatorOutcome("done"), {}, [CALL], CLEAN, graded) is None


def test_the_mechanical_rules_that_come_first() -> None:
    cut = {"event_type": "llm_call", "payload": {"ok": True, "finishReason": "length"}}
    assert classify(OperatorOutcome("done"), {}, [cut], CLEAN) == "harness"
    assert (
        classify(OperatorOutcome("waiting_input", unscripted="consult"), {}, [CALL], CLEAN)
        == "harness"
    )
    assert classify(OperatorOutcome("done"), {}, [CALL], HiddenResult("error", 5, "")) == "harness"
    assert classify(OperatorOutcome("running", timed_out=True), {}, [CALL], CLEAN) == "model"
    assert classify(OperatorOutcome("running", timed_out=True), {}, [], CLEAN) == "infra"
    assert classify(OperatorOutcome("failed"), {}, [], CLEAN) == "infra"
    assert (
        classify(OperatorOutcome("failed"), {"failureKind": "stale_claim"}, [CALL], CLEAN)
        == "product"
    )
    assert classify(OperatorOutcome("failed"), {"failureKind": "budget"}, [CALL], CLEAN) == "model"
