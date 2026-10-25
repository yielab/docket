#!/usr/bin/env python3
"""Repeat a live scenario of ``scripts/smoke_workflow.py`` N times and compare the runs by skeleton.

Each run is one smoke subprocess with ``--workdir`` inside ``--out``; its trace is read from the
JSONL files docket wrote under ``<world>/.docket/traces/`` (what ``docket task trace --json``
prints), and ``tests/support/e2e_oracles.py::skeleton_of`` gives the skeleton. Tokens are the
endpoint's measured counts from ``hop_finished``; there is no cost figure. The trace has no typed
stop reason, so a turn that hit a bound is read from the hop's error text. Writes ``run-NN.json``,
``run-NN.log``, ``summary.json``, ``summary.md`` and ``skeletons.json`` (a ``--baseline`` file).
Exit 1 on any governance violation, a skeleton the baseline lacks, or a run not evaluated.

    live_eval.py -n 3 --out DIR [--baseline FILE] [--dry-run]
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import shlex
import shutil
import statistics
import subprocess
import sys
import time
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
SMOKE = REPO / "scripts" / "smoke_workflow.py"

sys.path.insert(0, str(REPO))
from tests.support.e2e_oracles import skeleton_of  # noqa: E402

Skeleton = tuple[tuple[str, ...], ...]

# The smoke names a disqualifying private-path tool use as this one line, in a failure message.
_VIOLATION = re.compile(
    r"source=(?:approval|trace|session) role=\S+ tool=\S+ callId=\S+ "
    r"verdict=(?:confirmed_private|opaque) marker=\S+"
)
_FAILURE = re.compile(r"^SMOKE FAIL.*$", re.MULTILINE)
_STOPS = (
    ("no_progress", "no progress:"),
    ("token_budget", "token budget:"),
    ("token_budget", "exceeded token_budget="),
    ("max_iterations", "exceeded max_iterations="),
    ("max_tool_calls", "exceeded max_tool_calls="),
)


def stop_kind(error: str) -> str | None:
    """The bound a hop's turn ended on, from its error text; ``None`` for any other ending."""
    for kind, marker in _STOPS:
        if marker in error:
            return kind
    return None


def violations_in(output: str) -> list[str]:
    """The smoke's private-path diagnostics in its output, once each, in the order printed."""
    return list(dict.fromkeys(_VIOLATION.findall(output)))


def load_events(traces_dir: Path) -> list[dict[str, Any]]:
    """Every record of every trace file under *traces_dir*, oldest first; torn lines are skipped."""
    events: list[dict[str, Any]] = []
    for path in sorted(traces_dir.glob("*/*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict):
                events.append(record)
    return sorted(events, key=lambda e: str(e.get("ts", "")))


def hops_of(events: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """One row per finished hop: its role and step, measured tokens and the bound it hit, if any."""
    hops: list[dict[str, Any]] = []
    for event in events:
        if event.get("event_type") != "hop_finished":
            continue
        payload = event.get("payload") or {}
        usage = payload.get("usage") or {}
        error = str(payload.get("error") or "")
        hops.append(
            {
                "role": str(payload.get("role") or event.get("agent_role") or ""),
                "step": str(payload.get("step") or ""),
                "ok": bool(payload.get("ok")),
                "verdict": payload.get("verdict"),
                "inputTokens": usage.get("input"),
                "outputTokens": usage.get("output"),
                "cachedTokens": usage.get("cached"),
                "stop": stop_kind(error),
            }
        )
    return hops


def evaluate_run(
    index: int, code: int | None, output: str, events: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    """One run's record; ``error`` is a run not evaluated: a timeout, a usage error or no trace."""
    outcome = {0: "pass", 1: "fail"}.get(code if code is not None else -1, "error")
    if not events:
        outcome = "error"
    failures = _FAILURE.findall(output)
    hops = hops_of(events)
    return {
        "run": index,
        "outcome": outcome,
        "exitCode": code,
        "failure": failures[-1] if failures and outcome != "pass" else None,
        "skeleton": [list(step) for step in skeleton_of(events)],
        "hops": hops,
        "boundStops": [h for h in hops if h["stop"]],
        "violations": violations_in(output),
        "traceEvents": len(events),
    }


def _stats(values: Sequence[int]) -> dict[str, float] | None:
    return {"median": statistics.median(values), "max": max(values)} if values else None


def summarise(runs: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Across-run figures: pass rate, distinct skeletons with counts, tokens per role, violations."""
    by_skeleton: dict[str, list[int]] = {}
    for run in runs:
        if run["traceEvents"]:
            by_skeleton.setdefault(json.dumps(run["skeleton"]), []).append(run["run"])
    distinct = [
        {"count": len(ids), "runs": ids, "skeleton": json.loads(key)}
        for key, ids in sorted(by_skeleton.items(), key=lambda kv: (-len(kv[1]), kv[1]))
    ]
    tokens: dict[str, dict[str, Any]] = {}
    for role in sorted({h["role"] for run in runs for h in run["hops"]}):
        rows = [h for run in runs for h in run["hops"] if h["role"] == role]
        tokens[role] = {
            "hops": len(rows),
            "input": _stats([h["inputTokens"] for h in rows if h["inputTokens"] is not None]),
            "output": _stats([h["outputTokens"] for h in rows if h["outputTokens"] is not None]),
        }
    passed = sum(1 for run in runs if run["outcome"] == "pass")
    return {
        "runs": len(runs),
        "outcomes": dict(Counter(run["outcome"] for run in runs)),
        "passed": passed,
        "passRate": passed / len(runs) if runs else 0.0,
        "distinctSkeletons": distinct,
        "tokensByRole": tokens,
        "boundStops": sum(len(run["boundStops"]) for run in runs),
        "violations": sum(len(run["violations"]) for run in runs),
        "runsWithViolations": [run["run"] for run in runs if run["violations"]],
    }


def _lines(skeleton: Iterable[Sequence[str]]) -> list[str]:
    return [" | ".join(step) for step in skeleton]


def skeleton_diff(
    observed: Sequence[Sequence[Sequence[str]]], baseline: Sequence[Sequence[Sequence[str]]]
) -> list[dict[str, Any]]:
    """Each observed skeleton the baseline lacks, with a diff against the baseline's closest one."""
    known = {json.dumps([list(s) for s in sk]) for sk in baseline}
    new: list[dict[str, Any]] = []
    for skeleton in observed:
        if json.dumps([list(s) for s in skeleton]) in known:
            continue
        lines = _lines(skeleton)
        closest = max(
            (_lines(b) for b in baseline),
            key=lambda b: difflib.SequenceMatcher(None, b, lines).ratio(),
            default=[],
        )
        diff = difflib.unified_diff(closest, lines, "baseline", "observed", lineterm="", n=2)
        new.append({"skeleton": [list(s) for s in skeleton], "diff": list(diff)})
    return new


def load_baseline(path: Path) -> list[list[list[str]]]:
    """A baseline file: a JSON list of skeletons, each a list of ``[event_type, role, outcome]``."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list) or not all(isinstance(sk, list) for sk in data):
        raise ValueError(f"{path}: a baseline is a JSON list of skeletons")
    return data


def _cell(stats: Mapping[str, float] | None) -> str:
    return "-" if stats is None else f"{stats['median']:g} / {stats['max']:g}"


def render_markdown(
    summary: Mapping[str, Any],
    runs: Sequence[Mapping[str, Any]],
    new: Sequence[Mapping[str, Any]] | None,
) -> str:
    """The human summary: the verdict first, then per-run rows, skeletons and tokens."""
    out = [
        "# Live evaluation",
        "",
        f"- runs: {summary['runs']}, passed: {summary['passed']} "
        f"(pass rate {summary['passRate']:.0%}), outcomes: {summary['outcomes']}",
        f"- governance violations: {summary['violations']} (must be 0 in every run)",
        f"- turns ended on a bound (budget, iterations, tool calls, no progress): {summary['boundStops']}",
        f"- distinct skeletons: {len(summary['distinctSkeletons'])}",
        "- tokens are measured by the endpoint; no cost is computed",
        "",
        "## Runs",
        "",
        "| run | outcome | hops | bound stops | violations | skeleton |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    ids = {
        tuple(map(tuple, d["skeleton"])): n for n, d in enumerate(summary["distinctSkeletons"], 1)
    }
    for run in runs:
        label = ids.get(tuple(map(tuple, run["skeleton"])), 0) if run["traceEvents"] else 0
        stops = ", ".join(f"{h['role']}:{h['stop']}" for h in run["boundStops"]) or "-"
        out.append(
            f"| {run['run']} | {run['outcome']} | {len(run['hops'])} | {stops} | "
            f"{len(run['violations'])} | {f'S{label}' if label else '-'} |"
        )
    for run in runs:
        if run["failure"] or run["violations"]:
            out += ["", f"Run {run['run']}: {run['failure'] or ''}"]
            out += [f"- violation: `{v}`" for v in run["violations"]]
    out += [
        "",
        "## Tokens per hop",
        "",
        "| run | step | role | input | output | stop |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for run in runs:
        for h in run["hops"]:
            out.append(
                f"| {run['run']} | {h['step']} | {h['role']} | {h['inputTokens']} | "
                f"{h['outputTokens']} | {h['stop'] or '-'} |"
            )
    out += [
        "",
        "## Tokens per role (median / max over every hop of every run)",
        "",
        "| role | hops | input | output |",
        "| --- | --- | --- | --- |",
    ]
    for role, t in summary["tokensByRole"].items():
        out.append(f"| {role} | {t['hops']} | {_cell(t['input'])} | {_cell(t['output'])} |")
    out += ["", "## Distinct skeletons"]
    for n, d in enumerate(summary["distinctSkeletons"], 1):
        out += [
            "",
            f"S{n}: {d['count']} run(s) {d['runs']}",
            "",
            "```",
            *_lines(d["skeleton"]),
            "```",
        ]
    if new is not None:
        out += ["", "## Baseline", "", f"{len(new)} skeleton(s) not in the baseline."]
        for item in new:
            out += ["", "```diff", *item["diff"], "```"]
    return "\n".join(out) + "\n"


def smoke_command(args: argparse.Namespace, world: Path) -> list[str]:
    """The command of one run: the smoke, live, in a world it preserves for the read-back."""
    command = [sys.executable, str(SMOKE), "--live-model", "--workdir", str(world)]
    for flag, value in (
        ("--scenario", args.scenario),
        ("--endpoint", args.endpoint),
        ("--model", args.model),
    ):
        if value:
            command += [flag, value]
    return command


def run_once(args: argparse.Namespace, index: int) -> dict[str, Any]:
    """Run the smoke once and evaluate what it left; the log is kept beside the record."""
    run_dir = args.out / f"run-{index:02d}"
    world = run_dir / "world"
    run_dir.mkdir(parents=True)
    log_path = args.out / f"run-{index:02d}.log"
    started = time.monotonic()
    code: int | None
    with log_path.open("w", encoding="utf-8") as log:
        try:
            code = subprocess.run(
                smoke_command(args, world),
                cwd=REPO,
                env=os.environ.copy(),
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=args.run_timeout,
                check=False,
            ).returncode
        except subprocess.TimeoutExpired:
            code = None
            log.write(f"\nlive_eval: run exceeded {args.run_timeout}s and was stopped\n")
    output = log_path.read_text(encoding="utf-8", errors="replace")
    events = load_events(world / ".docket" / "traces") if world.is_dir() else []
    record = evaluate_run(index, code, output, events)
    record["seconds"] = round(time.monotonic() - started, 1)
    if not args.keep_worlds:
        shutil.rmtree(run_dir, ignore_errors=True)
    (args.out / f"run-{index:02d}.json").write_text(
        json.dumps(record, indent=2) + "\n", encoding="utf-8"
    )
    return record


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("-n", "--runs", type=int, default=3, help="Number of runs (default: 3).")
    parser.add_argument(
        "--out", type=Path, required=True, help="Directory for the records and the summary."
    )
    parser.add_argument("--baseline", type=Path, help="JSON list of skeletons; a new one exits 1.")
    parser.add_argument("--dry-run", action="store_true", help="Print the commands and exit 0.")
    parser.add_argument("--scenario", help="Smoke scenario (default: the smoke's own default).")
    parser.add_argument(
        "--endpoint", help="Loopback base URL for the smoke (default: the smoke's)."
    )
    parser.add_argument("--model", help="Loaded model id for the smoke (default: discovered).")
    parser.add_argument(
        "--run-timeout", type=float, default=3600.0, help="Seconds per run (default: 3600)."
    )
    parser.add_argument(
        "--keep-worlds", action="store_true", help="Keep each run's smoke world under --out."
    )
    args = parser.parse_args(argv)
    if args.runs < 1:
        parser.error("-n/--runs must be at least 1")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.dry_run:
        for index in range(1, args.runs + 1):
            print(shlex.join(smoke_command(args, args.out / f"run-{index:02d}" / "world")))
        return 0
    if args.out.exists() and any(args.out.iterdir()):
        print(f"live_eval: --out must be new or empty: {args.out}", file=sys.stderr)
        return 2
    baseline = load_baseline(args.baseline) if args.baseline else None
    args.out.mkdir(parents=True, exist_ok=True)
    runs = []
    for index in range(1, args.runs + 1):
        runs.append(run_once(args, index))
        print(f"run {index}/{args.runs}: {runs[-1]['outcome']}", flush=True)
    summary = summarise(runs)
    distinct = [d["skeleton"] for d in summary["distinctSkeletons"]]
    new = skeleton_diff(distinct, baseline) if baseline is not None else None
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    (args.out / "skeletons.json").write_text(
        json.dumps(distinct, indent=2) + "\n", encoding="utf-8"
    )
    markdown = render_markdown(summary, runs, new)
    (args.out / "summary.md").write_text(markdown, encoding="utf-8")
    print(
        f"pass rate {summary['passRate']:.0%}; skeletons {len(distinct)}; "
        f"violations {summary['violations']}; summary in {args.out / 'summary.md'}"
    )
    for item in new or []:
        print("NEW SKELETON\n" + "\n".join(item["diff"]), file=sys.stderr)
    bad = summary["violations"] or new or summary["outcomes"].get("error")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
