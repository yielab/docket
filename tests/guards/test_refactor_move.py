"""Guard: scripts/maint/refactor/move.py turns a mapping into exactly the expected tree.

Each case under ``fixtures/refactor/move/<case>/`` holds a ``before`` tree, an ``after`` tree and
a mapping (``refactor/target-map.toml``) that is identical in both. The tool runs on a temporary
copy of ``before`` only, never on this repository.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "maint" / "refactor" / "move.py"
CASES = Path(__file__).parent / "fixtures" / "refactor" / "move"
CASE_NAMES = ("module", "definitions", "tests_split", "package")
IGNORED = {"__pycache__", ".ruff_cache"}


def _load() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("_refactor_move_guard", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


move = _load()


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file() and not IGNORED & set(p.relative_to(root).parts)
    }


def _copy(case: str, side: str, into: Path) -> Path:
    target = into / f"{case}-{side}"
    shutil.copytree(CASES / case / side, target)
    return target


def _diff(got: dict[str, bytes], want: dict[str, bytes]) -> list[str]:
    out = [f"missing: {p}" for p in sorted(set(want) - set(got))]
    out += [f"unexpected: {p}" for p in sorted(set(got) - set(want))]
    out += [
        f"differs: {p}\n--- got\n{got[p].decode()}\n--- want\n{want[p].decode()}"
        for p in sorted(set(got) & set(want))
        if got[p] != want[p]
    ]
    return out


@pytest.mark.parametrize("case", CASE_NAMES)
def test_the_mapping_produces_the_expected_tree_byte_for_byte(case: str, tmp_path: Path) -> None:
    root = _copy(case, "before", tmp_path)
    assert move.main(["--root", str(root)]) == 0
    assert _diff(_snapshot(root), _snapshot(CASES / case / "after")) == []


@pytest.mark.parametrize("case", CASE_NAMES)
def test_check_fails_before_and_passes_after_and_a_second_run_changes_nothing(
    case: str, tmp_path: Path
) -> None:
    root = _copy(case, "before", tmp_path)
    assert move.main(["--root", str(root), "--check"]) == 1
    assert move.main(["--root", str(root)]) == 0
    done = _snapshot(root)
    assert move.main(["--root", str(root), "--check"]) == 0
    assert move.main(["--root", str(root)]) == 0
    assert _snapshot(root) == done


@pytest.mark.parametrize("case", CASE_NAMES)
def test_check_passes_on_the_expected_tree(case: str, tmp_path: Path) -> None:
    root = _copy(case, "after", tmp_path)
    assert move.main(["--root", str(root), "--check"]) == 0


@pytest.mark.parametrize("case", CASE_NAMES)
def test_dry_run_lists_the_changes_and_writes_nothing(
    case: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _copy(case, "before", tmp_path)
    before = _snapshot(root)
    assert move.main(["--root", str(root), "--dry-run"]) == 0
    assert _snapshot(root) == before
    listed = capsys.readouterr().out
    want = _snapshot(CASES / case / "after")
    changed = [p for p, data in want.items() if before.get(p) != data]
    assert changed
    assert all(p in listed for p in changed if p.endswith(".py"))


def test_a_name_missing_from_source_and_destination_is_a_problem_and_nothing_is_written(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _copy("definitions", "before", tmp_path)
    before = _snapshot(root)
    (root / "refactor" / "target-map.toml").write_text(
        '[[definition]]\nfrom = "docket.core.dispatch"\nto = "docket.tasks.claim"\n'
        'names = ["claim_next", "nothing_here"]\n'
    )
    assert move.main(["--root", str(root)]) == 2
    assert "nothing_here" in capsys.readouterr().err
    after = _snapshot(root)
    after.pop("refactor/target-map.toml")
    before.pop("refactor/target-map.toml")
    assert after == before


def test_a_module_missing_everywhere_is_a_problem(tmp_path: Path) -> None:
    root = _copy("module", "before", tmp_path)
    (root / "refactor" / "target-map.toml").write_text(
        '[[module]]\nfrom = "docket.core.nope"\nto = "docket.observe.nope"\n'
    )
    assert move.main(["--root", str(root)]) == 2


def test_a_test_that_touches_two_destinations_is_placed_with_the_first_and_noted(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _copy("tests_split", "before", tmp_path)
    path = root / "tests" / "unit" / "core" / "test_dispatch.py"
    path.write_text(
        path.read_text()
        + "\n\ndef test_both() -> None:\n    assert _dispatch.run_hop(claim_next('a'))\n"
    )
    assert move.main(["--root", str(root)]) == 0
    assert "test_both touches" in capsys.readouterr().err
    claim = (root / "tests" / "unit" / "tasks" / "test_claim.py").read_text()
    assert "def test_both" in claim
    assert "from docket.hops import runner as _runner" in claim


def test_the_report_names_the_file_and_test_id_moves(tmp_path: Path) -> None:
    root = _copy("tests_split", "before", tmp_path)
    report = tmp_path / "report.json"
    assert move.main(["--root", str(root), "--report", str(report)]) == 0
    ids = json.loads(report.read_text())["ids"]
    assert ids["tests/unit/core/test_dispatch.py::test_claim_returns_the_path"] == (
        "tests/unit/tasks/test_claim.py::test_claim_returns_the_path"
    )
    assert ids["tests/unit/core/test_dispatch.py::TestRunHop::test_marks_the_hop"] == (
        "tests/unit/hops/test_runner.py::TestRunHop::test_marks_the_hop"
    )
    assert "tests/unit/core/test_dispatch.py::test_ping" not in ids
    assert not (root / "refactor" / "retired.txt").exists()


def test_a_test_with_no_counterpart_after_the_move_is_recorded_as_retired() -> None:
    before = {"tests/unit/a/test_x.py": {"test_kept", "test_gone", "TestC::test_c"}}
    kept = "def test_kept():\n    pass\n\n\nclass TestC:\n    def test_c(self):\n        pass\n"
    renames = {"tests/unit/a/test_x.py": "tests/unit/b/test_x.py"}
    moves, retired = move.id_moves(before, renames, {"tests/unit/b/test_x.py": kept}, {})
    assert retired == ["retired: tests/unit/a/test_x.py::test_gone -> ?"]
    assert moves == {
        "tests/unit/a/test_x.py::test_kept": "tests/unit/b/test_x.py::test_kept",
        "tests/unit/a/test_x.py::TestC::test_c": "tests/unit/b/test_x.py::TestC::test_c",
    }


@pytest.mark.parametrize(
    "text, message",
    [
        ('[[module]]\nfrom = "docket.a"\n', "keys must be exactly"),
        ('[[module]]\nfrom = "docket.a"\nto = "docket.a"\n', "both docket.a"),
        ('[[module]]\nfrom = "other.a"\nto = "docket.b"\n', "dotted name"),
        ('[[definition]]\nfrom = "docket.a"\nto = "docket.b"\nnames = []\n', "non-empty"),
        (
            '[[definition]]\nfrom = "docket.a"\nto = "docket.b"\nnames = ["x"]\n'
            '[[definition]]\nfrom = "docket.a"\nto = "docket.c"\nnames = ["x"]\n',
            "listed twice",
        ),
        ("[[other]]\nx = 1\n", "unknown table"),
    ],
)
def test_a_malformed_mapping_is_refused(text: str, message: str) -> None:
    with pytest.raises(move.PlanError, match=message):
        move.parse_mapping(text)


def test_the_tool_never_touches_its_own_fixture_trees() -> None:
    assert move._skipped("tests/guards/fixtures/refactor/move/module/before/src/docket/x.py")
    assert not move._skipped("tests/unit/core/test_trace.py")


def test_every_case_has_both_trees_and_the_same_mapping() -> None:
    for case in CASE_NAMES:
        before = CASES / case / "before" / "refactor" / "target-map.toml"
        after = CASES / case / "after" / "refactor" / "target-map.toml"
        assert before.read_text() == after.read_text(), case


def _write(root: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)


_PYPROJECT = (CASES / "module" / "before" / "pyproject.toml").read_text()


def test_definitions_land_in_an_existing_destination_after_its_own_code(tmp_path: Path) -> None:
    _write(
        tmp_path,
        {
            "pyproject.toml": _PYPROJECT,
            "src/docket/__init__.py": "",
            "src/docket/core/__init__.py": "",
            "src/docket/lib/__init__.py": "",
            "src/docket/core/a.py": (
                "from __future__ import annotations\n\nimport os\n\n\n"
                "def keep() -> int:\n    return 1\n\n\n"
                "def go() -> str:\n    return os.sep * keep()\n"
            ),
            "src/docket/lib/b.py": '"""B."""\n\nimport json\n\n\ndef own() -> str:\n    return json.dumps(1)\n',
            "refactor/target-map.toml": (
                '[[definition]]\nfrom = "docket.core.a"\nto = "docket.lib.b"\nnames = ["go"]\n'
            ),
        },
    )
    assert move.main(["--root", str(tmp_path)]) == 0
    assert (tmp_path / "src/docket/lib/b.py").read_text() == (
        '"""B."""\n\nfrom __future__ import annotations\n\nimport json\nimport os\n\n'
        "from docket.core.a import keep\n\n\n"
        "def own() -> str:\n    return json.dumps(1)\n\n\n"
        "def go() -> str:\n    return os.sep * keep()\n"
    )
    assert (tmp_path / "src/docket/core/a.py").read_text() == (
        "from __future__ import annotations\n\n\ndef keep() -> int:\n    return 1\n"
    )
    assert move.main(["--root", str(tmp_path), "--check"]) == 0
