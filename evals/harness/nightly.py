"""Run a suite and raise the per-task alarm against a base (specs/test-framework.md "Alarm rule").

`run_suite` is what both `run` and `nightly` do with a model; `alarms` and `unpaired` are pure
functions over `trials.jsonl` records, so the alarm is tested without one.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from evals.harness.metrics import Record, counted
from evals.harness.report import read_trials, write_report
from evals.harness.task import Task
from evals.harness.trial import run_task

LOCAL_PROVIDER = "local"
LOCAL_MODEL = "qwen3.6-35b-a3b"
LOCAL_BASE_URL = "http://127.0.0.1:8081/v1"
LOCAL_CREDENTIAL = "local-endpoint"
NIGHTLY_SUITE = "regression"
NIGHTLY_EPOCHS = 3
DEFAULT_MAX_TOKENS = 8192
BASE_MIN_TRIALS = 3
ALARM_FAILS = 2


@dataclass(frozen=True)
class Alarm:
    """A task that was perfect in the base and now fails."""

    task: str
    base_passes: int
    base_n: int
    head_passes: int
    head_n: int

    def __str__(self) -> str:
        return (
            f"ALARM {self.task}: {self.base_passes}/{self.base_n} in the base,"
            f" {self.head_passes}/{self.head_n} now"
        )


def stamped_out() -> Path:
    """The default output directory, `evals-out/<utc stamp>/`."""
    return Path("evals-out") / datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _tally(records: Sequence[Record]) -> dict[str, tuple[int, int]]:
    """`{task@version: (passes, counted trials)}`; harness and infra trials are not counted."""
    found: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for r in counted(records):
        found[str(r["task"])][0] += 1 if r["passed"] else 0
        found[str(r["task"])][1] += 1
    return {task: (passes, n) for task, (passes, n) in found.items()}


def alarms(head_records: Sequence[Record], base_records: Sequence[Record]) -> list[Alarm]:
    """Tasks that passed every one of at least 3 counted base trials and now fail 2 or more
    counted trials with at most 1 pass; only a `task@version` present on both sides can alarm."""
    head, base = _tally(head_records), _tally(base_records)
    raised: list[Alarm] = []
    for task in sorted(set(head) & set(base)):
        (base_passes, base_n), (head_passes, head_n) = base[task], head[task]
        perfect = base_n >= BASE_MIN_TRIALS and base_passes == base_n
        if perfect and head_n - head_passes >= ALARM_FAILS and head_passes <= 1:
            raised.append(Alarm(task, base_passes, base_n, head_passes, head_n))
    return raised


def _split(key: str) -> tuple[str, str]:
    task, _, version = key.partition("@")
    return task, version


def unpaired(head_records: Sequence[Record], base_records: Sequence[Record]) -> list[str]:
    """Lines for the tasks the alarm leaves out: a changed version, a new task, no counted trial."""
    head, base = _tally(head_records), _tally(base_records)
    seen = {str(r["task"]) for r in head_records}
    base_versions = dict(_split(key) for key in base)
    notes: list[str] = []
    for key in sorted(seen - set(head)):
        notes.append(f"left out: {key} has no counted trial (harness or infra only)")
    for key in sorted(set(head) - set(base)):
        task, version = _split(key)
        if task in base_versions:
            notes.append(f"left out: {task}: version {base_versions[task]} -> {version}")
        else:
            notes.append(f"left out: {key} is not in the base")
    return notes


def run_suite(
    tasks: Sequence[Task],
    out: Path,
    *,
    epochs: int,
    provider: str,
    model: str,
    max_tokens: int,
    base_url: str = "",
    credential: str = "",
    credential_env: Mapping[str, str] | None = None,
    base: str | None = None,
) -> list[dict[str, Any]]:
    """Run each task for *epochs* epochs into `out/trials.jsonl`, write the summary beside it and
    return the run's records. A key reaches the trial only through *credential_env*."""
    for task in tasks:
        run_task(
            task,
            out,
            epochs=epochs,
            provider=provider,
            model=model,
            max_tokens=max_tokens,
            base_url=base_url,
            credential=credential,
            credential_env=credential_env,
        )
    records = read_trials(out)
    write_report(out, records, base)
    return records
