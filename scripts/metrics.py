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


# Every numeric group is `[\d,]+`, never `\d+`: the README writes thousands
# separators ("**1,188 tests**"), and a `\d+` group silently fails to match such
# a claim rather than checking it. That exact bug disarmed the tests claim the
# moment the suite crossed 1,000 cases.
CLAIMS: list[Claim] = [
    Claim("tests (by-the-numbers bullet)", re.compile(r"\*\*([\d,]+)\s+tests\*\*"), "tests"),
    Claim("tests (pytest command comment)", re.compile(r"#\s*([\d,]+)-test Python suite"), "tests"),
    Claim(
        "lines of Python",
        re.compile(r"\*\*~?([\d,]+)\s+lines\*\*\s+of Python"),
        "loc",
        round_to=100,
    ),
    Claim("specifications", re.compile(r"\*\*([\d,]+)\s+specifications\*\*"), "specs"),
    Claim("commands", re.compile(r"\*\*([\d,]+)\s+commands\*\*"), "commands"),
]


def claims_found(readme_path: Path) -> tuple[list[str], list[str]]:
    """Split CLAIMS into (stated in the README, not stated) by label.

    Exposed so `--check` can *report* which guards are live. A claim silently
    dropped from the prose is a disarmed guard; it must be visible, not implied
    by a passing exit code.
    """
    text = readme_path.read_text()
    stated = [c.label for c in CLAIMS if c.pattern.search(text)]
    missing = [c.label for c in CLAIMS if c.label not in stated]
    return stated, missing


def check_readme(readme_path: Path, metrics: dict[str, int]) -> list[str]:
    """Diff every quoted claim found in `readme_path` against `metrics`.

    Returns a list of human-readable drift messages (empty = in sync).

    A claim whose pattern isn't found is skipped rather than failed — the prose
    was reworded, which is a docs concern, not a number drift this gate owns.
    **But if _no_ claim matches at all, that is a hard failure:** the gate
    verified nothing, and a guard that checks nothing must never report success.
    Reporting "in sync" while silently verifying zero claims is the failure mode
    this check exists to prevent.
    """
    text = readme_path.read_text()
    problems: list[str] = []
    matched = 0

    for claim in CLAIMS:
        match = claim.pattern.search(text)
        if not match:
            continue
        matched += 1
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

    if matched == 0:
        problems.append(
            f"UNGUARDED: {readme_path.name} states none of the {len(CLAIMS)} tracked metrics "
            "in a recognized form, so this gate verified nothing. Either restore a quoted "
            "figure or remove the claim from CLAIMS -- a drift guard that checks nothing "
            "must not report success."
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
        # Name the live guards, and any claim the prose no longer states. Without
        # this, a claim quietly dropped from the README looks identical to a
        # claim that passed.
        stated, missing = claims_found(args.readme)
        print(f"  verified: {', '.join(stated)}")
        if missing:
            print(f"  not stated in README (unverifiable): {', '.join(missing)}")
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
