"""The invoices set matches the CSV under the task's rule, and the CSV was left alone."""

import csv
import hashlib
import json
import os
from pathlib import Path

REPO = Path(os.environ["EVAL_REPO"])
RECORDS = Path(os.environ["EVAL_RECORDS"])
TODAY = "2026-11-01"
CSV_SHA256 = "e5933a4b663c2d25771303bdc662c06b5c129e984d2de403e3e40655611c0f17"


def _rows() -> dict[str, dict]:
    rows = json.loads((RECORDS / "invoices.json").read_text(encoding="utf-8"))["rows"]
    return {str(r["id"]): r for r in rows}


def _expected() -> dict[str, tuple]:
    out = {}
    with (REPO / "invoices.csv").open(encoding="utf-8") as handle:
        for r in csv.DictReader(handle):
            status = "paid" if r["paid"] == "yes" else ("overdue" if r["due"] < TODAY else "open")
            out[r["id"]] = (r["customer"], int(r["amount_cents"]), r["due"], status)
    return out


def test_the_csv_was_not_edited() -> None:
    assert hashlib.sha256((REPO / "invoices.csv").read_bytes()).hexdigest() == CSV_SHA256


def test_one_row_per_invoice() -> None:
    rows = _rows()
    assert set(rows) == set(_expected()), sorted(rows)


def test_each_row_carries_the_csv_values_and_the_right_status() -> None:
    rows = _rows()
    for key, want in _expected().items():
        row = rows[key]
        got = (row["customer"], int(row["amount_cents"]), str(row["due"])[:10], row["status"])
        assert got == want, (key, got, want)


def test_the_overdue_invoices_are_exactly_the_unpaid_past_due_ones() -> None:
    overdue = {k for k, r in _rows().items() if r["status"] == "overdue"}
    assert overdue == {"INV-102", "INV-103", "INV-108"}
