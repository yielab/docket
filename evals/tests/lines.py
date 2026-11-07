"""A synthetic `trials.jsonl` line, built to the fixed schema."""

from __future__ import annotations

from typing import Any


def trial(
    task: str, passed: bool, failure_class: str | None = None, **extra: Any
) -> dict[str, Any]:
    """One trial line, built to the fixed `trials.jsonl` schema."""
    line: dict[str, Any] = {
        "task": task,
        "suite": "regression",
        "model": "m",
        "docket_commit": "abc1234",
        "epoch": 0,
        "graders": {},
        "passed": passed,
        "failure_class": None if passed else failure_class,
        "tokens": {},
        "status": "done",
        "wall_s": 1.0,
        "denials": 0,
        "asks": [],
        "schema": 1,
    }
    line.update(extra)
    return line
