"""One registry: `grade` runs a task's graders on a trial's evidence and returns the record's `graders`.

A grader that raises, or whose input is absent, is `error`, and an `error` classes the trial
`harness` (taxonomy). `process.*` graders never decide: they are report-only by their place in
`task.yaml`, and they return `pass` with a summary.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from evals.evaluator.graders import attack, governance, outcome, process, reviewer
from evals.evaluator.graders.base import GradeContext, GraderInputError, GraderResult
from evals.evaluator.task import Grader, Graders

__all__ = ["GradeContext", "GraderResult", "grade", "grade_one", "passed"]

_Fn = Callable[[GradeContext, Mapping[str, str]], GraderResult]
_REGISTRY: dict[str, _Fn] = {
    "outcome.hidden_tests": outcome.hidden_tests,
    "outcome.file_exact": outcome.file_exact,
    "outcome.task_status": outcome.task_status,
    "governance.no_violation": governance.no_violation,
    "governance.no_tool": governance.no_tool,
    "reviewer.verdict_matches": reviewer.verdict_matches,
    "attack.attempted": attack.attempted,
    "attack.executed": attack.executed,
    "process.tokens": process.tokens,
    "process.asks": process.asks,
    "process.bound_stops": process.bound_stops,
    "process.time": process.time,
}


def grade_one(grader: Grader, ctx: GradeContext) -> GraderResult:
    """Run one grader; a name with no implementation, an absent input or a raise is `error`."""
    fn = _REGISTRY.get(grader.name)
    if fn is None:
        return GraderResult("error", f"{grader.name} has no implementation")
    try:
        return fn(ctx, grader.params)
    except GraderInputError as error:
        return GraderResult("error", str(error))
    except Exception as error:
        return GraderResult("error", f"{type(error).__name__}: {error}")


def grade(graders: Graders, ctx: GradeContext) -> dict[str, dict[str, Any]]:
    """`{name: {status, reason, required}}` for every grader of a task, required ones first."""
    graded: dict[str, dict[str, Any]] = {}
    for required, group in ((True, graders.required), (False, graders.report)):
        for grader in group:
            if grader.name in graded:
                continue
            result = grade_one(grader, ctx)
            graded[grader.name] = {
                "status": result.status,
                "reason": result.reason,
                "required": required,
            }
    return graded


def passed(graded: Mapping[str, Mapping[str, Any]]) -> bool:
    """Every required grader passed; `False` when none was run."""
    required = [g for g in graded.values() if g["required"]]
    return bool(required) and all(g["status"] == "pass" for g in required)
