#!/usr/bin/env python3
"""Insert SUBJECT (unit/integration) and LANE/REASON/RETIRE_WHEN (agent) header skeletons.

Placement follows the test-framework lane contract: unit/<pkg>/test_<module>.py names its
module exactly; integration files get a best-effort SUBJECT from their dominant docket import
or, failing that, a humanized filename; agent files get a LANE derived from their directory and
placeholder REASON/RETIRE_WHEN for a human to fill in. Idempotent: a file that already declares
the constant it is asked for is left untouched.
"""

from __future__ import annotations

import argparse
import ast
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "docket"
TESTS = ROOT / "tests"


def _insertion_line(tree: ast.Module) -> int:
    """1-indexed line to insert a new module-level statement after."""
    last = 0
    body = list(tree.body)
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
        last = body[0].end_lineno or body[0].lineno
        body = body[1:]
    for node in body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            last = node.end_lineno or node.lineno
        else:
            break
    return last


def _has_constant(tree: ast.Module, name: str) -> bool:
    for node in tree.body:
        target = node.target if isinstance(node, ast.AnnAssign) else None
        targets = node.targets if isinstance(node, ast.Assign) else ([target] if target else [])
        if any(isinstance(t, ast.Name) and t.id == name for t in targets):
            return True
    return False


def _insert(path: Path, lines: list[str]) -> None:
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text)
    at = _insertion_line(tree)
    body = text.splitlines(keepends=True)
    block = "\n\n" + "\n".join(lines) + "\n"
    new_text = "".join(body[:at]) + block + "".join(body[at:])
    path.write_text(new_text, encoding="utf-8")


def _module_for_unit(path: Path, unit_root: Path) -> str:
    rel_pkg = path.relative_to(unit_root).parent
    stem = path.stem.removeprefix("test_").split("__", 1)[0]
    return "docket." + ".".join([*rel_pkg.parts, stem])


def _dominant_docket_import(tree: ast.Module) -> str | None:
    counts: Counter[str] = Counter()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("docket"):
            counts[node.module] += len(node.names)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("docket"):
                    counts[alias.name] += 1
    return counts.most_common(1)[0][0] if counts else None


def do_unit(check: bool) -> int:
    changed = 0
    for path in sorted((TESTS / "unit").rglob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        if _has_constant(tree, "SUBJECT"):
            continue
        subject = _module_for_unit(path, TESTS / "unit")
        if not check:
            _insert(path, [f'SUBJECT = "{subject}"'])
        changed += 1
    return changed


def do_integration(check: bool) -> int:
    changed = 0
    for path in sorted((TESTS / "integration").rglob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        if _has_constant(tree, "SUBJECT"):
            continue
        dominant = _dominant_docket_import(tree)
        subject = dominant if dominant else path.stem.removeprefix("test_").replace("_", " ")
        if not check:
            _insert(path, [f'SUBJECT = "{subject}"'])
        changed += 1
    return changed


def do_agent(check: bool) -> int:
    changed = 0
    for path in sorted((TESTS / "agent").rglob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        missing = [n for n in ("LANE", "REASON", "RETIRE_WHEN") if not _has_constant(tree, n)]
        if not missing:
            continue
        lane = path.relative_to(TESTS / "agent").parts[0]
        skeleton = {
            "LANE": f'LANE = "{lane}"',
            "REASON": 'REASON = "TODO: fill in"',
            "RETIRE_WHEN": 'RETIRE_WHEN = "TODO: fill in"',
        }
        if not check:
            _insert(path, [skeleton[n] for n in missing])
        changed += 1
    return changed


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="report only, write nothing")
    args = ap.parse_args()
    u = do_unit(args.check)
    i = do_integration(args.check)
    a = do_agent(args.check)
    verb = "would touch" if args.check else "touched"
    print(f"unit: {verb} {u} file(s)")
    print(f"integration: {verb} {i} file(s)")
    print(f"agent: {verb} {a} file(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
