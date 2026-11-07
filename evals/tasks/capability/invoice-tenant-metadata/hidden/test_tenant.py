"""Every receipt carries the tenant configured when it is issued, however often it changes."""

import os
import subprocess
import sys
from pathlib import Path

REPO = Path(os.environ["EVAL_REPO"])
sys.path.insert(0, str(REPO / "src"))

import tenancy  # noqa: E402
from checkout import invoice_total, receipt_metadata  # noqa: E402


def test_the_receipt_follows_each_new_configuration() -> None:
    for name in ("cobalt-7", "amber-2", "juniper-9"):
        tenancy.configure_tenant(name)
        assert receipt_metadata("order-1") == {"order_id": "order-1", "tenant": name}


def test_the_order_id_is_kept() -> None:
    tenancy.configure_tenant("cobalt-7")
    assert receipt_metadata("order-17")["order_id"] == "order-17"


def test_the_tenancy_api_is_unchanged() -> None:
    tenancy.configure_tenant("x-1")
    assert tenancy.current_tenant() == "x-1"


def test_the_total_is_unchanged() -> None:
    assert invoice_total(500, 1_250) == 563
    assert invoice_total(10_000, 500) == 10_500


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
