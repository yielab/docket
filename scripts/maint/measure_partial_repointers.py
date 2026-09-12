#!/usr/bin/env python3
"""Count test functions that hand-roll a partial copy of DOCKET_HOME isolation.

A function that calls ``monkeypatch.setattr`` on two or more DOCKET_HOME-derived
constants, without setting ``_cfg.DOCKET_HOME`` or calling the shared
``repoint_docket_home`` helper (``tests/conftest.py``), carries a private, un-tracked
subset of that helper's list -- one that stops covering a constant the day one is
added to the canonical tuple. The tracked-constant list below is derived from
``tests/conftest.py`` itself: the ``_DOCKET_HOME_PATHS`` tuple, plus whatever
``repoint_docket_home`` sets by name outside that loop, other than ``DOCKET_HOME``
(its own input; setting that one directly is a different, already-guarded shape --
``test_docket_home_repointer.py``).
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFTEST_PATH = REPO_ROOT / "tests" / "conftest.py"
TESTS_ROOT = REPO_ROOT / "tests"
BASELINE_FILE = REPO_ROOT / "tests" / "guards" / "partial_repointer_baseline.txt"

Hit = tuple[str, str, int, int]  # (module_rel_path, function_name, lineno, constants_touched)


def _assign_target_name(node: ast.stmt) -> str | None:
    if isinstance(node, ast.Assign):
        return next((t.id for t in node.targets if isinstance(t, ast.Name)), None)
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return node.target.id
    return None


def _setattr_constant_name(call: ast.expr) -> str | None:
    """The literal constant name in `<x>.setattr(<mod>, "NAME", ...)`, else None."""
    if not isinstance(call, ast.Call):
        return None
    func = call.func
    if not (isinstance(func, ast.Attribute) and func.attr == "setattr"):
        return None
    if len(call.args) < 2 or not isinstance(call.args[1], ast.Constant):
        return None
    value = call.args[1].value
    return value if isinstance(value, str) else None


def tracked_constants(conftest_path: Path = CONFTEST_PATH) -> frozenset[str]:
    """Every constant `repoint_docket_home` moves, other than DOCKET_HOME itself."""
    tree = ast.parse(conftest_path.read_text(encoding="utf-8"), filename=str(conftest_path))
    tracked: set[str] = set()
    for node in ast.walk(tree):
        if _assign_target_name(node) != "_DOCKET_HOME_PATHS":
            continue
        value = node.value  # type: ignore[attr-defined]
        if value is None:
            continue
        for element in value.elts:  # type: ignore[attr-defined]
            tracked.add(element.elts[0].value)
    repoint_fn = next(
        (
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "repoint_docket_home"
        ),
        None,
    )
    if repoint_fn is not None:
        for statement in repoint_fn.body:
            for call in ast.walk(statement):
                name = _setattr_constant_name(call)
                if name and name != "DOCKET_HOME":
                    tracked.add(name)
    return frozenset(tracked)


def _calls_repoint(fn: ast.AST) -> bool:
    for node in ast.walk(fn):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id == "repoint_docket_home":
            return True
        if isinstance(func, ast.Attribute) and func.attr == "repoint_docket_home":
            return True
    return False


def find_partial_repointers(
    tests_root: Path = TESTS_ROOT, tracked: frozenset[str] | None = None
) -> list[Hit]:
    """Every function that touches 2+ tracked constants without claiming a home."""
    if tracked is None:
        tracked = tracked_constants()
    hits: list[Hit] = []
    for path in sorted(tests_root.glob("**/*.py")):
        if path == CONFTEST_PATH:
            continue
        rel = str(path.relative_to(REPO_ROOT))
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            names = {
                name for node in ast.walk(fn) for name in [_setattr_constant_name(node)] if name
            }
            if "DOCKET_HOME" in names or _calls_repoint(fn):
                continue
            touched = names & tracked
            if len(touched) >= 2:
                hits.append((rel, fn.name, fn.lineno, len(touched)))
    return hits


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="exit 1 if the count exceeds the committed baseline"
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="overwrite the committed baseline with the current count",
    )
    args = parser.parse_args()

    tracked = tracked_constants()
    hits = find_partial_repointers(tracked=tracked)
    modules = {rel for rel, _, _, _ in hits}

    print(f"tracked constants: {len(tracked)}")
    print(f"partial repointers: {len(hits)} functions across {len(modules)} modules")
    for rel, name, lineno, count in hits:
        print(f"  {rel}:{lineno}  {name}  ({count} constants)")

    if args.write:
        BASELINE_FILE.write_text(f"{len(hits)}\n", encoding="utf-8")
        print(f"\nwrote {len(hits)} to {BASELINE_FILE}")
        return 0

    if args.check:
        baseline = int(BASELINE_FILE.read_text(encoding="utf-8").strip())
        if len(hits) > baseline:
            print(f"\nFAIL: {len(hits)} exceeds committed baseline {baseline}")
            return 1
        print(f"\nOK: {len(hits)} <= committed baseline {baseline}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
