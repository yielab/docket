#!/usr/bin/env python3
"""Cut the `## Changelog` section off every document under specs/.

A spec is a current-state contract; its history is `git log -- specs/<file>` and
CHANGELOG.md. The changelog is always the last `##` section, so the cut runs from that
heading to the end of the file, dropping the blank lines and `---` rule before it.

Usage: strip_spec_changelogs.py [--check]  (--check lists files that still carry one, exit 1)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPECS = ROOT / "specs"
HEADING = "## Changelog"


def stripped(text: str) -> str | None:
    """*text* without its changelog section, or None when it has none."""
    lines = text.splitlines()
    cut = next((n for n, line in enumerate(lines) if line.rstrip() == HEADING), None)
    if cut is None:
        return None
    later = [line for line in lines[cut + 1 :] if line.startswith("## ")]
    if later:
        raise ValueError(f"{HEADING} is not the last section (followed by {later[0]!r})")
    head = lines[:cut]
    while head and head[-1].strip() in ("", "---"):
        head.pop()
    return "\n".join(head) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    carrying = []
    for path in sorted(SPECS.rglob("*.md")):
        new = stripped(path.read_text(encoding="utf-8"))
        if new is None:
            continue
        carrying.append(path.relative_to(ROOT).as_posix())
        if not args.check:
            path.write_text(new, encoding="utf-8")
    for rel in carrying:
        print(rel)
    return 1 if args.check and carrying else 0


if __name__ == "__main__":
    sys.exit(main())
