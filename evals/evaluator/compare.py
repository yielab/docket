"""Pair a run with a base by `task@version` and say what the difference is, or that none shows."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

from evals.evaluator.metrics import Paired, paired_difference, scores_by_task
from evals.evaluator.report import TRIALS_FILE, read_trials

REPO_ROOT = Path(__file__).resolve().parents[2]
BASELINES = REPO_ROOT / "internal-docs" / "baselines" / "evals-v2"
SMALL_SUITE = 30
MIN_DETECTABLE = 0.20


class ComparisonError(Exception):
    """A run to compare cannot be found."""


@dataclass(frozen=True)
class Comparison:
    paired: Paired
    version_changed: list[tuple[str, str, str]]
    only_head: list[str]
    only_base: list[str]
    head_scores: dict[str, list[float]]
    base_scores: dict[str, list[float]]


def resolve_run(spec: str, baselines: Path = BASELINES) -> Path:
    """A run directory by path, else a base sha under `baselines`."""
    direct = Path(spec)
    if (direct / TRIALS_FILE).is_file():
        return direct
    if direct.is_file() and direct.name == TRIALS_FILE:
        return direct.parent
    saved = baselines / spec
    if (saved / TRIALS_FILE).is_file():
        return saved
    raise ComparisonError(f"no {TRIALS_FILE} for {spec!r} (looked in {direct} and {saved})")


def _split(key: str) -> tuple[str, str]:
    task, _, version = key.partition("@")
    return task, version


def compare_runs(head: Path, base: Path) -> Comparison:
    """Pair the counted trials of *head* against *base*; head minus base."""
    head_scores = scores_by_task(read_trials(head))
    base_scores = scores_by_task(read_trials(base))
    paired = paired_difference(head_scores, base_scores)
    base_versions = dict(_split(k) for k in paired.only_b)
    changed: list[tuple[str, str, str]] = []
    only_head: list[str] = []
    for key in paired.only_a:
        task, version = _split(key)
        if task in base_versions:
            changed.append((task, base_versions[task], version))
        else:
            only_head.append(key)
    changed_tasks = {c[0] for c in changed}
    only_base = [k for k in paired.only_b if _split(k)[0] not in changed_tasks]
    return Comparison(paired, sorted(changed), only_head, only_base, head_scores, base_scores)


def _points(value: float) -> str:
    return f"{value * 100:+.1f}"


def _verdict(result: Comparison) -> str:
    p = result.paired
    n = len(p.matched)
    if n < 2 or math.isnan(p.se):
        return "not detectable: fewer than 2 paired tasks"
    low, high = p.ci
    if low <= 0 <= high:
        return "no detectable difference: the 95% interval crosses 0"
    if n <= SMALL_SUITE and abs(p.mean) < MIN_DETECTABLE:
        return f"not detectable: under 20 points with {n} tasks the suite cannot tell it from noise"
    direction = "above" if p.mean > 0 else "below"
    return f"detectable: head is {abs(p.mean) * 100:.1f} points {direction} base"


def render(result: Comparison) -> str:
    """The paired table, the verdict and the tasks left out."""
    p = result.paired
    out = ["| task | base | head | diff (points) |", "| --- | --- | --- | --- |"]
    for key in p.matched:
        b, h = result.base_scores[key], result.head_scores[key]
        diff = sum(h) / len(h) - sum(b) / len(b)
        out.append(f"| {key} | {int(sum(b))}/{len(b)} | {int(sum(h))}/{len(h)} | {_points(diff)} |")
    if p.matched:
        stats = f"{len(p.matched)} paired tasks: difference {_points(p.mean)} points"
        if not math.isnan(p.se):
            lo, hi = p.ci
            stats += f", SE {p.se * 100:.1f}, 95% [{_points(lo)}, {_points(hi)}]"
            if not math.isnan(p.correlation):
                stats += f", correlation {p.correlation:.2f}"
        out += ["", stats]
    out += ["", f"verdict: {_verdict(result)}"]
    for task, was, now in result.version_changed:
        out.append(f"left out: {task}: version {was} -> {now}")
    for key in result.only_head:
        out.append(f"left out: {key} only in head")
    for key in result.only_base:
        out.append(f"left out: {key} only in base")
    return "\n".join(out) + "\n"
