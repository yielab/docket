"""The Lead's LATE-FEE-31 decision, which only the Lead's handoff carried."""

import os
import sys
from pathlib import Path

import pytest

REPO = Path(os.environ["EVAL_REPO"])
sys.path.insert(0, str(REPO / "src"))

from billing import late_fee  # noqa: E402


@pytest.mark.parametrize(
    ("balance", "days", "fee"),
    [
        (10_000, 0, 0),
        (10_000, 6, 0),
        (10_000, 7, 200),
        (10_000, 13, 200),
        (10_000, 20, 400),
        (10_000, 70, 1_000),
        (10_000, 700, 1_000),
        (12_345, 14, 493),
        (12_345, 700, 1_234),
        (500, 7, 10),
        (499, 70, 0),
    ],
)
def test_the_fee_follows_the_leads_decision(balance: int, days: int, fee: int) -> None:
    assert late_fee(balance, days) == fee


def test_the_fee_is_whole_cents() -> None:
    assert isinstance(late_fee(12_345, 14), int)
