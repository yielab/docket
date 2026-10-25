#!/usr/bin/env python3
"""metrics.py — on-demand counts of the tree (lines, commands, tests, specs).

A report for when someone wants the scale of the codebase. No document quotes these
numbers and nothing checks them, so a change never has to update them.

  ./scripts/metrics.py            # human-readable report
  ./scripts/metrics.py --json     # machine-readable
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "docket"
SPECS = ROOT / "specs"


# --- compute -----------------------------------------------------------------


def count_loc() -> int:
    """Lines of Python in the shipped `docket` package."""
    total = 0
    for path in sorted(SRC.rglob("*.py")):
        total += len(path.read_text().splitlines())
    return total


def count_specs() -> int:
    """Specifications under specs/, counted the way the blocking gate counts them.

    Deliberately *not* `rglob("*.spec.md")`. `scripts/validate-specs.sh` — the
    CI-blocking authority on what a specification is — globs each category
    directory, and for `specs/acceptance/` it globs `*.md` rather than
    `*.spec.md`. A suffix filter therefore silently misses
    `specs/acceptance/user-stories.md`, which the validator does check, and the
    two scripts disagreed by one for as long as that file has existed (README
    followed the weaker one and claimed 20 where the gate said 21).

    Counting every `*.md` one level below `specs/` reproduces the validator's
    set exactly, and skips the two top-level files that live outside any
    category and which the validator likewise ignores (`specs/README.md`, the
    index, and `specs/test-framework.md`). A new category directory is picked
    up automatically by both.
    """
    return len([p for p in SPECS.glob("*/*.md") if p.is_file()])


def count_commands() -> int:
    """Top-level commands registered on the Typer `app`, introspected live.

    Hidden commands don't count as part of the public surface, so they're excluded.
    """
    sys.path.insert(0, str(ROOT / "src"))
    import typer.main

    from docket.interfaces.cli.app import app

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


# --- CLI -----------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)

    metrics = compute()

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
