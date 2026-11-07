"""The acceptance the agent never sees: the Lead's durable decisions, applied to the checkout."""

import ast
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(os.environ["EVAL_REPO"])
sys.path.insert(0, str(REPO / "src"))

from checkout import invoice_total, receipt_metadata  # noqa: E402


def test_half_up_boundary_is_preserved() -> None:
    assert invoice_total(1_001, 825) == 1_084


def test_half_up_rounding_edge_is_not_bankers() -> None:
    assert invoice_total(500, 1_250) == 563


def test_receipt_carries_the_current_tenant_not_the_superseded_one() -> None:
    assert receipt_metadata("order-17") == {"order_id": "order-17", "tenant": "cobalt-7"}


def test_arithmetic_is_integer_only() -> None:
    tree = ast.parse((REPO / "src" / "checkout.py").read_text(encoding="utf-8"))
    assert not any(isinstance(node, ast.Div) for node in ast.walk(tree)), "true division"
    assert not any(
        isinstance(node, ast.Constant) and isinstance(node.value, float) for node in ast.walk(tree)
    ), "a float literal"


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
