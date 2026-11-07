"""Per-region unit counts."""

import csv
from pathlib import Path


def region_total(path: Path) -> int:
    """The units of one region file: a `day,units` header, then one row per day."""
    with Path(path).open(encoding="utf-8", newline="") as handle:
        return sum(int(row["units"]) for row in csv.DictReader(handle))
