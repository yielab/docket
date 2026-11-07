"""The suite summary: `summary.json` and `summary.md` from a run's `trials.jsonl`."""

from __future__ import annotations

import json
import math
import statistics
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from evals.harness.metrics import (
    Record,
    clustered_se,
    pass_at_k,
    pass_pow_k,
    scores_by_task,
    tokens_per_passed_by_role,
    wilson,
)

TRIALS_FILE = "trials.jsonl"
VIOLATION_GRADER = "governance.no_violation"


def read_trials(path: Path) -> list[dict[str, Any]]:
    """The records of a run directory, or of a `trials.jsonl` file, as plain dicts."""
    file = path / TRIALS_FILE if path.is_dir() else path
    lines = file.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def _clean(value: Any) -> Any:
    """Replace nan with None so the JSON stays standard."""
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    return value


def _joined(records: Sequence[Record], key: str) -> str:
    return ",".join(sorted({str(r.get(key, "?")) for r in records}))


def _violated(record: Record) -> bool:
    grader = (record.get("graders") or {}).get(VIOLATION_GRADER)
    return grader is not None and grader.get("status") == "fail"


def summarize(records: Sequence[Record], base: str | None = None) -> dict[str, Any]:
    """Every figure of the summary; rates use the counted trials only."""
    scores = scores_by_task(records)
    flat = [s for group in scores.values() for s in group]
    trials_per_task = Counter(str(r["task"]) for r in records)
    k = min((len(g) for g in scores.values()), default=0)
    p1 = statistics.fmean(flat) if flat else math.nan
    lo, hi = wilson(p1, len(flat)) if flat else (math.nan, math.nan)
    at_k = [pass_at_k(len(g), int(sum(g)), k) for g in scores.values()] if k else []
    pow_k = [pass_pow_k(len(g), int(sum(g)), k) for g in scores.values()] if k else []
    failed = [r for r in records if not r.get("passed")]
    classes = Counter(str(r.get("failure_class") or "unclassified") for r in failed)
    summary: dict[str, Any] = {
        "suite": _joined(records, "suite"),
        "model": _joined(records, "model"),
        "commit": _joined(records, "docket_commit"),
        "base": base,
        "tasks": len(trials_per_task),
        "epochs": max(trials_per_task.values(), default=0),
        "trials": len(records),
        "counted_trials": len(flat),
        "pass_at_1": p1,
        "pass_at_1_ci": [lo, hi],
        "clustered_se": clustered_se(scores),
        "k": k,
        "pass_at_k": statistics.fmean(at_k) if at_k else math.nan,
        "pass_pow_k": statistics.fmean(pow_k) if pow_k else math.nan,
        "violations": sum(1 for r in records if _violated(r)),
        "failure_counts": dict(sorted(classes.items())),
        "tokens_per_passed_task": tokens_per_passed_by_role(records),
    }
    cleaned: dict[str, Any] = _clean(summary)
    return cleaned


def _fmt(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.2f}"


def verdict_line(s: dict[str, Any]) -> str:
    """The first line of the summary."""
    lo, hi = s["pass_at_1_ci"]
    k = s["k"]
    return (
        f"{s['suite']} | {s['model']} | {s['tasks']} tasks x {s['epochs']} epochs"
        f" | commit {s['commit']} | base {s['base'] or 'none'}"
        f" | pass@1 {_fmt(s['pass_at_1'])} (95% {_fmt(lo)}-{_fmt(hi)})"
        f" | pass^{k} {_fmt(s['pass_pow_k'])} | pass@{k} {_fmt(s['pass_at_k'])}"
        f" | violations {s['violations']}"
    )


def render_markdown(s: dict[str, Any]) -> str:
    """The summary as markdown, the verdict line first."""
    lines = [verdict_line(s), ""]
    lines.append(f"- trials: {s['trials']} ({s['counted_trials']} counted; model and product only)")
    lines.append(f"- clustered standard error of pass@1: {_fmt(s['clustered_se'])}")
    counts = ", ".join(f"{name} {n}" for name, n in s["failure_counts"].items()) or "none"
    lines.append(f"- failures by class: {counts}")
    if s["tokens_per_passed_task"]:
        lines += ["", "| role | tokens p50 | tokens p90 |", "| --- | --- | --- |"]
        for role, q in s["tokens_per_passed_task"].items():
            lines.append(f"| {role} | {q['p50']:.0f} | {q['p90']:.0f} |")
    return "\n".join(lines) + "\n"


def write_report(
    out_dir: Path, records: Sequence[Record], base: str | None = None
) -> dict[str, Path]:
    """Write `summary.md` and `summary.json` into *out_dir*; return both paths."""
    summary = summarize(records, base)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {"md": out_dir / "summary.md", "json": out_dir / "summary.json"}
    paths["md"].write_text(render_markdown(summary), encoding="utf-8")
    paths["json"].write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return paths
