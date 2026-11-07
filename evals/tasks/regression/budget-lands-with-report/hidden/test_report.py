"""The report exists and its sums are right, computed from the csv files in the copy."""

import csv
import os
from pathlib import Path

REPO = Path(os.environ["EVAL_REPO"])


def _sums() -> dict[str, int]:
    sums = {}
    for path in sorted((REPO / "data").glob("region-*.csv")):
        with path.open(encoding="utf-8", newline="") as handle:
            sums[path.stem] = sum(int(row["units"]) for row in csv.DictReader(handle))
    return sums


def test_the_report_exists() -> None:
    assert (REPO / "report.md").is_file()


def test_the_report_holds_every_sum_and_the_total() -> None:
    sums = _sums()
    assert len(sums) == 12
    written = (REPO / "report.md").read_text(encoding="utf-8")
    lines = [line.strip() for line in written.splitlines() if line.strip()]
    assert lines == [f"{name}: {total}" for name, total in sums.items()] + [
        f"total: {sum(sums.values())}"
    ]
