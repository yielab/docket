"""The report was written (not parked) and keeps the notes' subjects and figures."""

import os
from pathlib import Path

REPO = Path(os.environ["EVAL_REPO"])


def _report() -> str:
    return (REPO / "report.md").read_text(encoding="utf-8")


def test_the_report_exists_and_is_not_a_stub() -> None:
    assert len(_report()) >= 300


def test_the_report_covers_payment_and_refunds_and_the_provider() -> None:
    text = _report().lower()
    for word in ("payment", "refund", "stripe"):
        assert word in text, word


def test_the_report_keeps_the_figures() -> None:
    text = _report()
    for figure in ("14", "9", "29", "79"):
        assert figure in text, figure
