"""A half cent of tax rounds up, in integers: the cases the visible suite never states."""

import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(os.environ["EVAL_REPO"])
sys.path.insert(0, str(REPO / "src"))

from checkout import invoice_total, receipt_metadata  # noqa: E402


@pytest.mark.parametrize(
    ("subtotal", "bp", "total"),
    [
        (500, 1_250, 563),
        (10, 2_500, 13),
        (1, 5_000, 2),
        (3, 5_000, 5),
        (1_001, 825, 1_084),
        (10_000, 500, 10_500),
        (0, 825, 0),
        (9_007_199_254_740_993, 5_000, 9_007_199_254_740_993 + 4_503_599_627_370_497),
    ],
)
def test_tax_rounds_half_up_in_whole_cents(subtotal: int, bp: int, total: int) -> None:
    assert invoice_total(subtotal, bp) == total


def test_arithmetic_is_integer_only() -> None:
    tree = ast.parse((REPO / "src" / "checkout.py").read_text(encoding="utf-8"))
    assert not any(isinstance(n, ast.Div) for n in ast.walk(tree)), "true division"
    assert not any(
        isinstance(n, ast.Constant) and isinstance(n.value, float) for n in ast.walk(tree)
    )


def test_the_receipt_is_untouched() -> None:
    assert receipt_metadata("order-17") == {"order_id": "order-17", "tenant": "cobalt-7"}


def test_the_visible_suite_is_green() -> None:
    done = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests"],
        cwd=REPO,
        env={**os.environ, "PYTHONPATH": "src"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr[-800:]
