#!/usr/bin/env python3
"""metrics.py — single source of truth for project metrics.

Successor to the Bash-era scripts/metrics.sh, which counted `lib/commands/*.sh`
and `lib/core/router.sh` — both deleted at the Bash→Python cutover (M6) — so
every number it produced silently resolved to (near) zero. This version counts
the real Python tree.

The README quotes line counts, command counts, test counts, and spec counts.
Hand-maintained, these drift and contradict each other. This script computes
them from the tree so there is exactly one authority.

  ./scripts/metrics.py            # human-readable report
  ./scripts/metrics.py --json     # machine-readable (CI / badges)
  ./scripts/metrics.py --check    # verify README numbers match (exit 1 on drift)

Add new metrics here, not in prose.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "docket"
SPECS = ROOT / "specs"
DEFAULT_README = ROOT / "README.md"


# --- compute -----------------------------------------------------------------


def count_loc() -> int:
    """Lines of Python in the shipped `docket` package."""
    total = 0
    for path in sorted(SRC.rglob("*.py")):
        total += len(path.read_text().splitlines())
    return total


def count_specs() -> int:
    """Spec files under specs/, of any category."""
    return len(list(SPECS.rglob("*.spec.md")))


def count_commands() -> int:
    """Top-level commands registered on the Typer `app`, introspected live.

    Hidden commands (internal plumbing like `_json`) don't count as part of
    the public surface, so they're excluded.
    """
    sys.path.insert(0, str(ROOT / "src"))
    import typer.main

    from docket.cli import app

    click_command = typer.main.get_command(app)
    commands = getattr(click_command, "commands", {})
    return sum(1 for cmd in commands.values() if not getattr(cmd, "hidden", False))


_COLLECT_SUMMARY_RE = re.compile(r"^(\d+)\s+tests?\s+collected", re.MULTILINE)
_COLLECT_PER_FILE_RE = re.compile(r"^\S+\.py:\s+(\d+)\s*$", re.MULTILINE)


def count_tests() -> int:
    """Pytest collection count — how many tests the suite actually runs.

    Newer pytest (used here) prints one "<path>: <n>" line per file for
    `--collect-only -q` instead of a single "N tests collected" summary line;
    older pytest prints the summary line instead. Handle both.
    """
    proc = subprocess.run(
        ["uv", "run", "pytest", "--collect-only", "-q"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    output = proc.stdout

    summary = _COLLECT_SUMMARY_RE.search(output)
    if summary:
        return int(summary.group(1))

    per_file = _COLLECT_PER_FILE_RE.findall(output)
    if per_file:
        return sum(int(n) for n in per_file)

    raise RuntimeError(
        "could not parse `uv run pytest --collect-only -q` output:\n" + output + proc.stderr
    )


def compute() -> dict[str, int]:
    return {
        "loc": count_loc(),
        "commands": count_commands(),
        "tests": count_tests(),
        "specs": count_specs(),
    }


# --- check ---------------------------------------------------------------------


@dataclass(frozen=True)
class Claim:
    """A number the README quotes, and how to verify it against the tree."""

    label: str
    pattern: re.Pattern[str]
    metric: str
    # Approximate claims (README writes "~12,700") are compared rounded to the
    # nearest `round_to`; exact claims (round_to=0) must match exactly.
    round_to: int = 0


CLAIMS: list[Claim] = [
    Claim("tests (by-the-numbers bullet)", re.compile(r"\*\*(\d+)\s+tests\*\*"), "tests"),
    Claim("tests (pytest command comment)", re.compile(r"#\s*(\d+)-test Python suite"), "tests"),
    Claim(
        "lines of Python",
        re.compile(r"\*\*~?([\d,]+)\s+lines\*\*\s+of Python"),
        "loc",
        round_to=100,
    ),
    Claim("specifications", re.compile(r"\*\*(\d+)\s+specifications\*\*"), "specs"),
]


def check_readme(readme_path: Path, metrics: dict[str, int]) -> list[str]:
    """Diff every quoted claim found in `readme_path` against `metrics`.

    Returns a list of human-readable drift messages (empty = in sync). A
    claim whose pattern isn't found is skipped rather than failed — it means
    the surrounding prose was reworded, which is a docs concern, not a number
    drift this gate is responsible for.
    """
    text = readme_path.read_text()
    problems: list[str] = []

    for claim in CLAIMS:
        match = claim.pattern.search(text)
        if not match:
            continue
        claimed = int(match.group(1).replace(",", ""))
        actual = metrics[claim.metric]
        if claim.round_to:
            drift = round(claimed / claim.round_to) != round(actual / claim.round_to)
        else:
            drift = claimed != actual
        if drift:
            problems.append(
                f"DRIFT: README claims {claimed} for '{claim.label}', tree has {actual}"
            )
    return problems


# --- CLI -----------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--check", action="store_true", help="verify README numbers match the tree")
    parser.add_argument(
        "--readme",
        type=Path,
        default=DEFAULT_README,
        help="README path to check against (default: repo README.md; tests point this at a fixture)",
    )
    args = parser.parse_args(argv)

    metrics = compute()

    if args.check:
        problems = check_readme(args.readme, metrics)
        if problems:
            for p in problems:
                print(p)
            return 1
        print(
            "metrics: README in sync "
            f"(tests={metrics['tests']}, loc={metrics['loc']}, "
            f"commands={metrics['commands']}, specs={metrics['specs']})"
        )
        return 0

    if args.json:
        print(json.dumps(metrics, indent=2, sort_keys=True))
        return 0

    print(f"{'Commands:':<26} {metrics['commands']}")
    print(f"{'Lines of Python:':<26} {metrics['loc']}")
    print(f"{'Tests:':<26} {metrics['tests']}")
    print(f"{'Spec files:':<26} {metrics['specs']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
