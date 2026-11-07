"""Metrics are pure functions over trial records; the expected values are computed by hand."""

from __future__ import annotations

import math

import pytest

from evals.evaluator.metrics import (
    clustered_se,
    counted,
    paired_difference,
    pass_at_k,
    pass_pow_k,
    scores_by_task,
    wilson,
)
from evals.tests.lines import trial


def test_pass_at_k_is_the_unbiased_estimator() -> None:
    assert pass_at_k(5, 3, 2) == pytest.approx(0.9)
    assert pass_at_k(5, 0, 2) == 0.0
    assert pass_at_k(5, 4, 2) == 1.0
    assert pass_at_k(3, 1, 1) == pytest.approx(1 / 3)


def test_pass_pow_k_is_all_k_trials_passing() -> None:
    assert pass_pow_k(5, 3, 2) == pytest.approx(0.3)
    assert pass_pow_k(5, 1, 2) == 0.0
    assert pass_pow_k(3, 3, 3) == 1.0


def test_wilson_matches_the_closed_form_for_15_of_25() -> None:
    # Wilson (1927): the interval is the two roots of (p_hat - p)^2 = z^2 p (1 - p) / n.
    # Solving that quadratic for 15 of 25 at z = 1.96 gives 0.407 and 0.766 (standard tables).
    z, n, p_hat = 1.96, 25, 0.6
    a = 1 + z * z / n
    b = -(2 * p_hat + z * z / n)
    c = p_hat * p_hat
    disc = math.sqrt(b * b - 4 * a * c)
    expected = ((-b - disc) / (2 * a), (-b + disc) / (2 * a))
    lo, hi = wilson(0.6, 25)
    assert lo == pytest.approx(expected[0], abs=5e-4)
    assert hi == pytest.approx(expected[1], abs=5e-4)
    assert (round(lo, 3), round(hi, 3)) == (0.407, 0.766)


def test_wilson_stays_inside_the_unit_interval_at_the_edges() -> None:
    lo, hi = wilson(1.0, 3)
    assert hi == pytest.approx(1.0)
    assert 0.0 < lo < 1.0
    assert wilson(0.0, 3)[0] == pytest.approx(0.0)


def test_clustered_se_widens_when_trials_of_a_task_agree() -> None:
    independent = {"a": [1.0, 0.0], "b": [1.0, 0.0], "c": [1.0, 0.0], "d": [1.0, 0.0]}
    clustered = {"a": [1.0, 1.0], "b": [1.0, 1.0], "c": [0.0, 0.0], "d": [0.0, 0.0]}
    plain = math.sqrt(sum((x - 0.5) ** 2 for x in [1.0, 0.0] * 4) / 7 / 8)
    assert clustered_se(independent) < plain
    assert clustered_se(clustered) > plain


def test_clustered_se_of_one_trial_per_task_is_the_plain_se() -> None:
    scores = {"a": [1.0], "b": [0.0], "c": [1.0], "d": [0.0]}
    assert clustered_se(scores) == pytest.approx(math.sqrt(1 / 3 / 4))


def test_paired_difference_reproduces_the_hand_computed_mean_and_se() -> None:
    # Per-task means a = 1, 1, 0, 1 and b = 1, 0, 0, 0; differences 0, 1, 0, 1.
    # mean 0.5; sample variance (4 * 0.25) / 3; SE = sqrt(variance / 4) = 0.288675.
    a = {"t1@1": [1.0], "t2@1": [1.0, 1.0], "t3@1": [0.0], "t4@1": [1.0]}
    b = {"t1@1": [1.0], "t2@1": [0.0, 0.0], "t3@1": [0.0], "t4@1": [0.0]}
    result = paired_difference(a, b)
    assert result.mean == pytest.approx(0.5)
    assert result.se == pytest.approx(0.288675, abs=1e-6)
    assert result.ci[0] == pytest.approx(0.5 - 1.96 * 0.288675, abs=1e-5)
    assert result.ci[1] == pytest.approx(0.5 + 1.96 * 0.288675, abs=1e-5)
    # Pearson of (1,1,0,1) with (1,0,0,0): sum of products 0.25 over sqrt(0.75 * 0.75) is 1/3.
    assert result.correlation == pytest.approx(1 / 3)
    assert result.matched == ["t1@1", "t2@1", "t3@1", "t4@1"]


def test_paired_difference_lists_unmatched_tasks_apart() -> None:
    result = paired_difference({"x@1": [1.0], "y@2": [1.0]}, {"x@1": [0.0], "y@1": [1.0]})
    assert result.matched == ["x@1"]
    assert result.only_a == ["y@2"]
    assert result.only_b == ["y@1"]


def test_an_infra_trial_does_not_lower_pass_at_1() -> None:
    records = [
        trial("t@1", True),
        trial("t@1", True),
        trial("t@1", False, "infra"),
        trial("u@1", False, "harness"),
        trial("u@1", False, "model"),
    ]
    assert scores_by_task(records) == {"t@1": [1.0, 1.0], "u@1": [0.0]}
    assert len(counted(records)) == 3


def test_a_failure_with_no_class_still_counts() -> None:
    assert scores_by_task([trial("t@1", False)]) == {"t@1": [0.0]}
