"""SUBJECT: evals/evaluator/report.py -- a safety suite's summary shows, per suite, the attack success
rate and the false-positive rate of the harmless twins, each with n and a Wilson 95% interval."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from evals.evaluator.metrics import wilson
from evals.evaluator.report import summarize, write_report
from evals.tests.lines import trial


def _graded(attempted: bool | None, executed: bool | None) -> dict[str, Any]:
    if attempted is None:
        return {}
    status = {True: "pass", False: "fail"}
    return {
        "attack.attempted": {"status": status[attempted], "reason": "r", "required": False},
        "attack.executed": {"status": status[bool(executed)], "reason": "r", "required": False},
    }


def attack(name: str, attempted: bool, executed: bool, **extra: Any) -> dict[str, Any]:
    line = trial(f"{name}@1", not executed, "model", suite="safety", **extra)
    line["graders"] = _graded(attempted, executed)
    return line


def twin(name: str, passed: bool, **extra: Any) -> dict[str, Any]:
    return trial(f"{name}-twin@1", passed, "product", suite="safety", **extra)


def test_the_table_counts_attacks_executed_and_twins_that_failed() -> None:
    lines = [
        attack("a", True, True),
        attack("b", True, False),
        attack("c", False, False),
        attack("d", True, False),
        twin("a", True),
        twin("b", True),
        twin("c", False),
        twin("d", True),
    ]

    row = summarize(lines)["safety"]["safety"]

    assert (row["attacks"], row["attempted"], row["executed"]) == (4, 3, 1)
    assert row["attack_success"] == pytest.approx(0.25)
    assert row["attack_success_ci"] == pytest.approx(list(wilson(0.25, 4)))
    assert (row["twins"], row["twins_passed"], row["false_positives"]) == (4, 3, 1)
    assert row["twin_pass"] == pytest.approx(0.75)
    assert row["twin_pass_ci"] == pytest.approx(list(wilson(0.75, 4)))


def test_harness_failures_and_errored_graders_are_not_counted() -> None:
    errored = attack("e", True, True)
    errored["graders"]["attack.executed"]["status"] = "error"
    infra = twin("f", False)
    infra["failure_class"] = "harness"
    lines = [attack("a", True, False), errored, twin("a", True), infra]

    row = summarize(lines)["safety"]["safety"]

    assert (row["attacks"], row["twins"], row["false_positives"]) == (1, 1, 0)


def test_a_suite_with_no_attack_has_no_safety_table() -> None:
    lines = [trial("a@1", True), trial("b@1", False, "model")]

    assert summarize(lines)["safety"] == {}


def test_the_markdown_table_shows_the_rates_with_n_and_interval(tmp_path: Path) -> None:
    lines = [attack("a", True, True), attack("b", False, False), twin("a", True), twin("b", False)]

    out = write_report(tmp_path / "out", lines)

    md = out["md"].read_text(encoding="utf-8")
    assert "| suite | attacks | attempted | executed | attack success (95% CI) |" in md
    lo, hi = wilson(0.5, 2)
    assert f"| safety | 2 | 1 | 1 | 0.50 (n=2, {lo:.2f}-{hi:.2f}) |" in md
    assert f"0.50 (n=2, {lo:.2f}-{hi:.2f}) | 1 |" in md
    assert json.loads(out["json"].read_text(encoding="utf-8"))["safety"]["safety"]["attacks"] == 2
