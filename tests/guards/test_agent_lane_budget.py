"""Ratchet: the agent lane's total line count may never exceed its committed baseline.

The long-term target is 4,000 lines; agent_lane_baseline.txt records where the lane stands
today and may only be lowered, never raised, as later cards trim it toward that target.
"""

from __future__ import annotations

from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parents[2] / "tests" / "agent"
BASELINE_FILE = Path(__file__).parent / "agent_lane_baseline.txt"


def _agent_lane_line_count() -> int:
    return sum(sum(1 for _ in path.open(encoding="utf-8")) for path in AGENT_DIR.rglob("*.py"))


def test_agent_lane_line_count_does_not_exceed_baseline() -> None:
    baseline = int(BASELINE_FILE.read_text().strip())
    total = _agent_lane_line_count()
    assert total <= baseline, f"agent lane grew to {total} lines, above baseline {baseline}"
