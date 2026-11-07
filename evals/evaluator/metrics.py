"""Pure metrics over trial records read as plain dicts; no I/O.

Only `model` and `product` failures count against a rate: `COUNTED_CLASSES` is the one filter.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

Record = Mapping[str, Any]
COUNTED_CLASSES = frozenset({"model", "product"})
Z95 = 1.96


def pass_at_k(n: int, c: int, k: int) -> float:
    """At least one pass in `k` of `n` trials with `c` passes: `1 - C(n-c,k)/C(n,k)`."""
    if k > n:
        raise ValueError(f"k={k} exceeds the {n} trials")
    return 1.0 - math.comb(n - c, k) / math.comb(n, k)


def pass_pow_k(n: int, c: int, k: int) -> float:
    """All `k` trials pass: `C(c,k)/C(n,k)`."""
    if k > n:
        raise ValueError(f"k={k} exceeds the {n} trials")
    return math.comb(c, k) / math.comb(n, k)


def wilson(p: float, n: int, z: float = Z95) -> tuple[float, float]:
    """The Wilson score interval for a proportion `p` over `n` trials."""
    if n <= 0:
        return (0.0, 1.0)
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def clustered_se(scores: Mapping[str, Sequence[float]]) -> float:
    """Standard error of the mean score with trials clustered by task (Miller 2024)."""
    flat = [s for group in scores.values() for s in group]
    total = len(flat)
    if total < 2:
        return math.nan
    mean = statistics.fmean(flat)
    plain = statistics.variance(flat) / total
    cross = 0.0
    for group in scores.values():
        dev = [s - mean for s in group]
        cross += sum(dev) ** 2 - sum(d * d for d in dev)
    return math.sqrt(max(0.0, plain + cross / (total * total)))


@dataclass(frozen=True)
class Paired:
    """A per-task paired difference of means, `a` minus `b`."""

    mean: float
    se: float
    ci: tuple[float, float]
    correlation: float
    matched: list[str]
    only_a: list[str]
    only_b: list[str]


def _pearson(xs: Sequence[float], ys: Sequence[float]) -> float:
    if len(xs) < 2:
        return math.nan
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if sx == 0 or sy == 0:
        return math.nan
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)) / (sx * sy)


def paired_difference(a: Mapping[str, Sequence[float]], b: Mapping[str, Sequence[float]]) -> Paired:
    """Pair the tasks of `a` and `b` by `task@version`; difference of per-task means with its SE."""
    matched = sorted(set(a) & set(b))
    mean_a = [statistics.fmean(a[t]) for t in matched]
    mean_b = [statistics.fmean(b[t]) for t in matched]
    diffs = [x - y for x, y in zip(mean_a, mean_b, strict=True)]
    only_a, only_b = sorted(set(a) - set(b)), sorted(set(b) - set(a))
    nan2 = (math.nan, math.nan)
    if not diffs:
        return Paired(math.nan, math.nan, nan2, math.nan, [], only_a, only_b)
    mean = statistics.fmean(diffs)
    if len(diffs) < 2:
        return Paired(mean, math.nan, nan2, math.nan, matched, only_a, only_b)
    se = math.sqrt(statistics.variance(diffs) / len(diffs))
    ci = (mean - Z95 * se, mean + Z95 * se)
    return Paired(mean, se, ci, _pearson(mean_a, mean_b), matched, only_a, only_b)


def counted(records: Iterable[Record]) -> list[Record]:
    """The trials that count: passes, and failures of class `model`, `product` or none."""
    return [
        r
        for r in records
        if r.get("passed")
        or r.get("failure_class") is None
        or r["failure_class"] in COUNTED_CLASSES
    ]


def scores_by_task(records: Iterable[Record]) -> dict[str, list[float]]:
    """`{task@version: [1.0 or 0.0 per counted trial]}`."""
    out: dict[str, list[float]] = {}
    for r in counted(records):
        out.setdefault(str(r["task"]), []).append(1.0 if r["passed"] else 0.0)
    return out


def percentile(values: Sequence[float], q: float) -> float:
    """The `q` quantile (0-1) by linear interpolation; nan for no values."""
    if not values:
        return math.nan
    ordered = sorted(values)
    pos = q * (len(ordered) - 1)
    lo, hi = math.floor(pos), math.ceil(pos)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo)


def tokens_per_passed_by_role(records: Iterable[Record]) -> dict[str, dict[str, float]]:
    """Per role, the p50 and p90 of input plus output tokens over the passed trials."""
    per_role: dict[str, list[float]] = {}
    for r in records:
        if not r.get("passed"):
            continue
        for role, used in (r.get("tokens") or {}).items():
            total = float(used.get("input", 0) + used.get("output", 0))
            per_role.setdefault(role, []).append(total)
    return {
        role: {"p50": percentile(vals, 0.5), "p90": percentile(vals, 0.9)}
        for role, vals in sorted(per_role.items())
    }
