#!/usr/bin/env python3
"""Measure functions under src/docket whose line span exceeds a ceiling.

A function's span runs from its ``def`` line to its last line, nested functions included,
because a closure-heavy function is still read as one unit. ``function_span_baseline.txt``
records every function currently over the ceiling with its span. The guard fails when a
listed function grows or an unlisted one appears; only ``--write``, run by the integrator
after a split lands, lowers the file.
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src" / "docket"
BASELINE_FILE = REPO_ROOT / "tests" / "guards" / "function_span_baseline.txt"
SPAN_MAX = 150

Hit = tuple[str, str, int]  # (module_rel_path, qualified_name, span)


def _walk(node: ast.AST, prefix: str, rel: str, span_max: int, out: list[Hit]) -> None:
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            name = f"{prefix}{child.name}"
            span = (child.end_lineno or child.lineno) - child.lineno + 1
            if span > span_max:
                out.append((rel, name, span))
            _walk(child, f"{name}.", rel, span_max, out)
        elif isinstance(child, ast.ClassDef):
            _walk(child, f"{prefix}{child.name}.", rel, span_max, out)
        else:
            _walk(child, prefix, rel, span_max, out)


def find_long_functions(paths: list[Path] | None = None, span_max: int = SPAN_MAX) -> list[Hit]:
    files: list[Path] = []
    for p in paths or [SRC_ROOT]:
        files.extend(sorted(p.rglob("*.py")) if p.is_dir() else [p])
    hits: list[Hit] = []
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        rel = path.resolve().relative_to(REPO_ROOT).as_posix()
        _walk(tree, "", rel, span_max, hits)
    return hits


def read_baseline(path: Path = BASELINE_FILE) -> dict[tuple[str, str], int]:
    out: dict[tuple[str, str], int] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        locator, span = line.rsplit(" ", 1)
        rel, name = locator.split("::", 1)
        out[(rel, name)] = int(span)
    return out


def format_baseline(hits: list[Hit]) -> str:
    lines = [f"# functions over {SPAN_MAX} lines; shrink-only, regenerate with --write"]
    lines += [f"{rel}::{name} {span}" for rel, name, span in sorted(hits)]
    return "\n".join(lines) + "\n"


def regressions(hits: list[Hit], baseline: dict[tuple[str, str], int]) -> list[str]:
    bad: list[str] = []
    for rel, name, span in hits:
        recorded = baseline.get((rel, name))
        if recorded is None:
            bad.append(f"{rel}::{name} spans {span} lines and is not in the baseline")
        elif span > recorded:
            bad.append(f"{rel}::{name} grew from {recorded} to {span} lines")
    return bad


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "paths", nargs="*", type=Path, help="files or directories (default: src/docket)"
    )
    parser.add_argument("--max", type=int, default=SPAN_MAX, help="span ceiling in lines")
    parser.add_argument(
        "--check", action="store_true", help="exit 1 on any regression against the baseline"
    )
    parser.add_argument("--write", action="store_true", help="overwrite the committed baseline")
    args = parser.parse_args(argv)
    hits = find_long_functions(args.paths or None, args.max)
    for rel, name, span in sorted(hits, key=lambda h: -h[2]):
        print(f"{span:5d}  {rel}::{name}")
    if args.write:
        BASELINE_FILE.write_text(format_baseline(hits), encoding="utf-8")
        print(f"\nwrote {len(hits)} entries to {BASELINE_FILE.relative_to(REPO_ROOT)}")
        return 0
    if args.check:
        bad = regressions(hits, read_baseline())
        for line in bad:
            print(f"FAIL: {line}")
        print(
            f"\n{'FAIL' if bad else 'OK'}: {len(hits)} over {args.max} lines, baseline {len(read_baseline())}"
        )
        return 1 if bad else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
