#!/usr/bin/env python3
"""Report (and optionally remove) archaeology in comments and docstrings.

Archaeology is text that describes *when* or *from where* code arrived rather than *why* it is
shaped the way it is: card ids, phase numbers, dates, "previously", "renamed from", and so on.
Rationale words ("because", "so that", "otherwise", "must", "never") mark a comment as
load-bearing; those lines are only ever reported, never removed.

Also reports docstrings that exceed the length budget: module docstrings over --module-max
lines and function/class docstrings over --def-max lines.

Exit status 1 under --check when any archaeology is found in the given paths.
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from dataclasses import dataclass
from pathlib import Path

ARCHAEOLOGY = re.compile(
    r"\b[WP]\d{2}-[A-Z]?\d+\b|\bD-\d{1,3}\b|\bCL-[A-Z]\b|\bPhase \d+\b|\bWave \d+\b"
    r"|\b20\d{2}-\d{2}-\d{2}\b"
    r"|\b(previously|formerly|used to|renamed from|migrated from|was removed outright|"
    r"was deleted|has been removed|before this change|after this change|in the old)\b",
    re.I,
)
# "legacy" and "no longer" are ordinary domain words here (on-disk compatibility, state checks);
# they only count as archaeology under --strict.
STRICT_EXTRA = re.compile(r"\b(legacy|no longer)\b", re.I)
RATIONALE = re.compile(
    r"\b(because|so that|otherwise|must|never|why|invariant|fail[- ]closed|load-bearing)\b", re.I
)


@dataclass
class Finding:
    path: Path
    line: int
    kind: str  # archaeology | archaeology-rationale | long-module-doc | long-def-doc
    text: str


def _renders_user_help(node: ast.AST) -> bool:
    """True for a Typer command or callback, whose docstring is printed to the user.

    That docstring is product surface -- `docket <cmd> --help` and the generated
    reference both render it -- so the internal-commentary budget does not bind it.
    Archaeology still does: it would be archaeology in the user's terminal.
    """
    for dec in getattr(node, "decorator_list", []):
        target = dec.func if isinstance(dec, ast.Call) else dec
        name = target.attr if isinstance(target, ast.Attribute) else getattr(target, "id", "")
        if name in {"command", "callback"}:
            return True
    return False


def scan_file(path: Path, module_max: int, def_max: int, strict: bool = False) -> list[Finding]:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    out: list[Finding] = []
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return out

    docstring_ranges: list[tuple[int, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if not node.body:
                continue
            first = node.body[0]
            if (
                isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)
            ):
                start, end = first.lineno, first.end_lineno or first.lineno
                docstring_ranges.append((start, end))
                length = end - start + 1
                if isinstance(node, ast.Module) and length > module_max:
                    out.append(
                        Finding(
                            path, start, "long-module-doc", f"{length} lines (max {module_max})"
                        )
                    )
                elif (
                    not isinstance(node, ast.Module)
                    and length > def_max
                    and not _renders_user_help(node)
                ):
                    name = getattr(node, "name", "?")
                    out.append(
                        Finding(
                            path, start, "long-def-doc", f"{name}: {length} lines (max {def_max})"
                        )
                    )

    def in_docstring(n: int) -> bool:
        return any(s <= n <= e for s, e in docstring_ranges)

    for i, line in enumerate(lines, start=1):
        stripped = line.strip()
        is_comment = stripped.startswith("#")
        if not (is_comment or in_docstring(i)):
            continue
        if ARCHAEOLOGY.search(stripped) or (strict and STRICT_EXTRA.search(stripped)):
            kind = "archaeology-rationale" if RATIONALE.search(stripped) else "archaeology"
            out.append(Finding(path, i, kind, stripped[:120]))
    return out


def remove_safe_comment_lines(path: Path, findings: list[Finding]) -> int:
    """Delete whole-line comments flagged as plain archaeology. Docstring lines are never touched."""
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    doomed = {
        f.line
        for f in findings
        if f.kind == "archaeology" and lines[f.line - 1].strip().startswith("#")
    }
    if not doomed:
        return 0
    kept = [ln for n, ln in enumerate(lines, start=1) if n not in doomed]
    path.write_text("".join(kept), encoding="utf-8")
    return len(doomed)


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("paths", nargs="+", type=Path)
    ap.add_argument("--module-max", type=int, default=12)
    ap.add_argument("--def-max", type=int, default=3)
    ap.add_argument("--check", action="store_true", help="exit 1 if any archaeology is found")
    ap.add_argument(
        "--fix", action="store_true", help="remove whole-line comments that are plain archaeology"
    )
    ap.add_argument("--summary", action="store_true", help="per-file counts only")
    ap.add_argument("--strict", action="store_true", help="also flag 'legacy' and 'no longer'")
    args = ap.parse_args()

    files: list[Path] = []
    for p in args.paths:
        files.extend(sorted(p.rglob("*.py")) if p.is_dir() else [p])

    total: dict[str, int] = {}
    removed = 0
    for f in files:
        findings = scan_file(f, args.module_max, args.def_max, args.strict)
        if not findings:
            continue
        if args.fix:
            removed += remove_safe_comment_lines(f, findings)
            findings = scan_file(f, args.module_max, args.def_max, args.strict)
        counts: dict[str, int] = {}
        for x in findings:
            counts[x.kind] = counts.get(x.kind, 0) + 1
            total[x.kind] = total.get(x.kind, 0) + 1
        if args.summary:
            print(f"{f}: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
        else:
            for x in findings:
                print(f"{x.path}:{x.line}: [{x.kind}] {x.text}")

    print("\ntotal: " + (", ".join(f"{k}={v}" for k, v in sorted(total.items())) or "clean"))
    if args.fix:
        print(f"removed {removed} whole-line archaeology comments")
    if args.check and (total.get("archaeology", 0) or total.get("archaeology-rationale", 0)):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
