"""Architecture: function-local ``docket.*`` imports only shrink (ADR 0030).

An import inside a function body hides a dependency from the import graph's cycle check: the
module imports cleanly, and the cycle only shows when the function runs. The rule is none; the
count recorded in ``local_imports_baseline.txt`` is what is left to remove. Hoist the import to
module level (or break the cycle) and lower the baseline in the same commit. Imports under
``if TYPE_CHECKING:`` never run and are not counted.
"""

from __future__ import annotations

import ast
from pathlib import Path

SUBJECT = "docket"

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "src"
BASELINE = Path(__file__).with_name("local_imports_baseline.txt")
PACKAGE = "docket"


def _is_type_checking(test: ast.expr) -> bool:
    name = test.id if isinstance(test, ast.Name) else getattr(test, "attr", "")
    return name == "TYPE_CHECKING"


def _targets_package(node: ast.Import | ast.ImportFrom) -> bool:
    if isinstance(node, ast.Import):
        return any(a.name == PACKAGE or a.name.startswith(PACKAGE + ".") for a in node.names)
    if node.level:
        return True  # a relative import inside src/docket always stays in the package
    mod = node.module or ""
    return mod == PACKAGE or mod.startswith(PACKAGE + ".")


def local_imports(source: str) -> list[int]:
    """Line numbers of docket imports nested in a function body, outside TYPE_CHECKING."""
    found: list[int] = []

    def walk(node: ast.AST, in_func: bool, type_checking: bool) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.Import | ast.ImportFrom):
                if in_func and not type_checking and _targets_package(child):
                    found.append(child.lineno)
                continue
            if isinstance(child, ast.If) and _is_type_checking(child.test):
                for part in child.body:
                    walk_one(part, in_func, True)
                for part in child.orelse:
                    walk_one(part, in_func, type_checking)
                continue
            inner = in_func or isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef)
            walk(child, inner, type_checking)

    def walk_one(node: ast.AST, in_func: bool, type_checking: bool) -> None:
        holder = ast.Module(body=[node], type_ignores=[])
        walk(holder, in_func, type_checking)

    walk(ast.parse(source), False, False)
    return found


def count_local_imports() -> int:
    total = 0
    for path in sorted((SRC / PACKAGE).rglob("*.py")):
        total += len(local_imports(path.read_text(encoding="utf-8")))
    return total


def read_baseline() -> int:
    for raw in BASELINE.read_text(encoding="utf-8").splitlines():
        if raw.startswith("local_imports "):
            return int(raw.split()[1])
    raise AssertionError("local_imports_baseline.txt has no `local_imports N` line")


def test_the_count_equals_the_baseline() -> None:
    count, baseline = count_local_imports(), read_baseline()
    assert count <= baseline, (
        f"function-local docket imports rose to {count}, above baseline {baseline}: "
        "import at module level, or break the cycle that made it local"
    )
    assert count >= baseline, (
        f"function-local docket imports fell to {count}, below baseline {baseline}: "
        f"lower the baseline to {count} in tests/architecture/local_imports_baseline.txt"
    )


def test_the_detector_sees_what_it_exists_for() -> None:
    # Without these a detector that matched nothing would hold any baseline.
    bites = {
        "def f():\n    import docket.x\n": 1,
        "def f():\n    from docket.a import b\n": 1,
        "def f():\n    from . import b\n": 1,
        "class C:\n    def m(self):\n        from docket import a\n": 1,
        "def f():\n    def g():\n        from docket.a import b\n": 1,
        "def f():\n    if y:\n        from docket.a import b\n": 1,
        "import docket.x\nfrom docket.a import b\n": 0,
        "def f():\n    import os\n    from json import loads\n": 0,
        "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    from docket.a import b\n": 0,
        "def f():\n    if TYPE_CHECKING:\n        from docket.a import b\n": 0,
        "def f():\n    if TYPE_CHECKING:\n        pass\n    else:\n        import docket.a\n": 1,
    }
    for source, expected in bites.items():
        assert len(local_imports(source)) == expected, source
