"""No helper or fixture is defined, with an identical body, in two test files.

A shared helper has one owner under ``tests/support/``; a second file imports it. The check
compares top-level non-test functions by their AST with the docstring removed, name included.
"""

from __future__ import annotations

import ast
import collections
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TESTS = ROOT / "tests"
_SKIPPED_DIRS = {"fixtures", "golden", "__pycache__"}


def _shape(fn: ast.FunctionDef) -> str:
    body = fn.body
    first = body[0] if body else None
    if (
        isinstance(first, ast.Expr)
        and isinstance(first.value, ast.Constant)
        and isinstance(first.value.value, str)
    ):
        fn = ast.FunctionDef(**{**dict(ast.iter_fields(fn)), "body": body[1:] or [ast.Pass()]})
    return ast.dump(fn)


def duplicated_helpers(root: Path) -> list[str]:
    """Return one line per helper or fixture that two or more files define identically."""
    seen: dict[tuple[str, str], list[str]] = collections.defaultdict(list)
    for path in sorted(root.rglob("*.py")):
        if _SKIPPED_DIRS & set(path.relative_to(root).parts):
            continue
        for node in ast.parse(path.read_text(encoding="utf-8")).body:
            if isinstance(node, ast.FunctionDef) and not node.name.startswith("test_"):
                seen[(node.name, _shape(node))].append(str(path.relative_to(root)))
    return [
        f"{name} is defined identically in {', '.join(files)}"
        for (name, _), files in sorted(seen.items())
        if len(set(files)) > 1
    ]


def test_no_helper_or_fixture_is_defined_twice() -> None:
    found = duplicated_helpers(TESTS)
    assert found == [], "move each to tests/support/ and import it:\n" + "\n".join(found)


def test_the_check_sees_a_planted_copy(tmp_path: Path) -> None:
    helper = 'def _seed(tmp_path):\n    """doc"""\n    return tmp_path / "x"\n'
    (tmp_path / "test_a.py").write_text(helper, encoding="utf-8")
    (tmp_path / "test_b.py").write_text(helper.replace('"""doc"""', '"""other doc"""'))
    (tmp_path / "test_c.py").write_text("def _seed(tmp_path):\n    return 1\n", encoding="utf-8")

    found = duplicated_helpers(tmp_path)

    assert len(found) == 1
    assert "test_a.py" in found[0] and "test_b.py" in found[0] and "test_c.py" not in found[0]


def test_a_test_function_defined_twice_is_not_a_helper(tmp_path: Path) -> None:
    body = "def test_x():\n    assert True\n"
    (tmp_path / "test_a.py").write_text(body, encoding="utf-8")
    (tmp_path / "test_b.py").write_text(body, encoding="utf-8")

    assert duplicated_helpers(tmp_path) == []
