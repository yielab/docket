"""Guard: tests/unit/** mirrors src/docket/**, and large modules stay covered.

Every tests/unit/**/test_X.py declares SUBJECT naming the src/docket module it exercises;
a small allowlist predates that convention (cross-cutting checks, not module mirrors) and
declares a real SUBJECT anyway. Coverage of every src/ module over 150 lines is checked
against a committed baseline that may only shrink -- see layout_baseline.txt.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "src" / "docket"
UNIT = REPO / "tests" / "unit"
LARGE_MODULE_LINES = 150

# Predate the filename-mirrors-module convention: each checks an invariant that spans
# multiple modules or a non-src contract, so its SUBJECT is asserted verbatim, not derived.
_STRUCTURAL_EXEMPT = {
    "test_cli_stubs.py": "docket.cli",
    "test_store_writer.py": "docket.edges.store",
    "test_runtime_adapter_fixture_contract.py": "tests.fixtures.runtime_adapters.scenarios",
}


def _read_subject(path: Path) -> str | None:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == "SUBJECT"
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            return node.value.value
    return None


def _expected_subject(path: Path) -> str:
    rel_pkg = path.relative_to(UNIT).parent
    stem = path.stem.removeprefix("test_").split("__", 1)[0]
    return "docket." + ".".join([*rel_pkg.parts, stem])


def _resolve_module(dotted: str) -> Path | None:
    parts = dotted.split(".")[1:]  # drop the leading "docket"
    as_module = SRC.joinpath(*parts).with_suffix(".py")
    if as_module.is_file():
        return as_module
    as_package = SRC.joinpath(*parts, "__init__.py")
    return as_package if as_package.is_file() else None


def _unit_files() -> list[Path]:
    return sorted(UNIT.rglob("test_*.py"))


def test_every_unit_file_declares_a_matching_subject() -> None:
    problems = []
    for path in _unit_files():
        subject = _read_subject(path)
        if subject is None:
            problems.append(f"{path}: no SUBJECT constant declared")
            continue
        exempt = _STRUCTURAL_EXEMPT.get(path.name)
        if exempt is not None:
            if subject != exempt:
                problems.append(f"{path}: SUBJECT {subject!r} != exempt value {exempt!r}")
        else:
            expected = _expected_subject(path)
            if subject != expected:
                problems.append(f"{path}: SUBJECT {subject!r} != expected {expected!r}")
        if subject.startswith("docket.") and _resolve_module(subject) is None:
            problems.append(f"{path}: SUBJECT {subject!r} names a module that does not exist")
    assert not problems, "\n".join(problems)


def _covered_modules() -> set[str]:
    covered = set()
    for path in _unit_files():
        subject = _read_subject(path)
        if subject and subject.startswith("docket."):
            covered.add(subject)
    return covered


def _baseline() -> set[str]:
    lines = (Path(__file__).parent / "layout_baseline.txt").read_text().splitlines()
    return {line.strip() for line in lines if line.strip() and not line.startswith("#")}


def test_every_large_src_module_is_unit_covered_or_baselined() -> None:
    covered = _covered_modules()
    baseline = _baseline()
    missing = []
    for path in sorted(SRC.rglob("*.py")):
        if sum(1 for _ in path.open(encoding="utf-8")) <= LARGE_MODULE_LINES:
            continue
        parts = path.relative_to(SRC).with_suffix("").parts
        if parts[-1] == "__init__":
            parts = parts[:-1]
        dotted = "docket." + ".".join(parts)
        if dotted not in covered and dotted not in baseline:
            missing.append(dotted)
    assert not missing, (
        f"module(s) over {LARGE_MODULE_LINES} lines lack a unit file and are not in "
        f"layout_baseline.txt: {missing}"
    )
