"""Guard: scripts/maint/refactor_gate.sh names its nine checks and never passes a missing one.

The heavy checks (lint, types, lanes, golden, docs) run the repository's own commands and are not
repeated here; the checks that decide something on their own are exercised in a scratch git repo.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
GATE = REPO / "scripts" / "maint" / "refactor_gate.sh"
NAMES = [
    "lint",
    "types",
    "import-contracts",
    "test-ids",
    "lanes",
    "golden",
    "docs",
    "specs-diff",
    "metrics",
]


def _gate(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(GATE), "--root", str(root), *args], capture_output=True, text=True, check=False
    )


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.test", *args],
        cwd=root,
        check=True,
        capture_output=True,
    )


@pytest.fixture
def scratch(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q")
    spec = tmp_path / "specs" / "functional" / "a.spec.md"
    spec.parent.mkdir(parents=True)
    spec.write_text(
        "# A\n\n1. A trace is kept.\n\n## Implementation\n\n"
        "- `src/docket/core/trace.py::record` and `core/trace.py`\n- `docket.core.trace.EVENTS`\n"
    )
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-q", "-m", "Add: spec")
    return tmp_path


def test_the_nine_checks_are_listed_in_the_order_of_the_adr() -> None:
    out = _gate(REPO, "--list").stdout.split("\n")
    assert [line.split(" ", 1)[1] for line in out if line] == NAMES
    assert [line.split(" ", 1)[0] for line in out if line] == [str(i) for i in range(1, 10)]


def test_the_script_runs_the_commands_the_adr_names() -> None:
    text = GATE.read_text()
    for command in (
        "ruff check .",
        "ruff format --check .",
        "mypy src",
        "pytest-without-sandbox.sh",
        "tests/integration/test_escape_matrix.py",
        "tests/golden/run.sh verify-all",
        "scripts/validate-specs.sh",
        "gen_cli_docs.py --check",
        "gen_recipe_docs.py --check",
        "tests/architecture/test_import_contracts.py",
        "tests/architecture/test_ids.py",
        "--metrics",
    ):
        assert command in text, command


@pytest.mark.parametrize("check", ["import-contracts", "test-ids", "metrics"])
def test_a_check_whose_test_or_tool_is_absent_fails_and_names_itself(
    check: str, scratch: Path
) -> None:
    result = _gate(scratch, "--only", check)
    assert result.returncode == 1
    assert "GATE MISSING: check" in result.stderr
    assert check in result.stderr
    assert "GATE FAILED: check" in result.stderr


def test_metrics_without_a_baseline_is_missing_even_when_the_tool_exists(scratch: Path) -> None:
    tool = scratch / "scripts" / "maint" / "refactor" / "analyze.py"
    tool.parent.mkdir(parents=True)
    tool.write_text("print('largest_cycle: 3')\n")
    result = _gate(scratch, "--only", "metrics")
    assert result.returncode == 1
    assert "metrics-baseline.txt does not exist" in result.stderr


def test_a_path_only_change_to_a_spec_passes(scratch: Path) -> None:
    spec = scratch / "specs" / "functional" / "a.spec.md"
    spec.write_text(
        spec.read_text()
        .replace("src/docket/observability/trace.py", "src/docket/observe/trace.py")
        .replace("`core/trace.py`", "`observe/trace.py`")
        .replace("docket.observability.trace.EVENTS", "docket.observe.trace.EVENTS")
    )
    result = _gate(scratch, "--only", "specs-diff")
    assert result.returncode == 0, result.stderr


def test_a_change_to_the_words_of_a_spec_fails(scratch: Path) -> None:
    spec = scratch / "specs" / "functional" / "a.spec.md"
    spec.write_text(spec.read_text().replace("A trace is kept.", "A trace is never kept."))
    result = _gate(scratch, "--only", "specs-diff")
    assert result.returncode == 1
    assert "specs/functional/a.spec.md" in result.stderr


def test_a_new_spec_file_fails(scratch: Path) -> None:
    (scratch / "specs" / "functional" / "b.spec.md").write_text("# B\n")
    _git(scratch, "add", ".")
    result = _gate(scratch, "--only", "specs-diff")
    assert result.returncode == 1
    assert "b.spec.md" in result.stderr


def test_base_selects_what_specs_are_compared_with(scratch: Path) -> None:
    spec = scratch / "specs" / "functional" / "a.spec.md"
    spec.write_text(spec.read_text().replace("A trace is kept.", "A trace is never kept."))
    _git(scratch, "commit", "-q", "-am", "Fix: words")
    assert _gate(scratch, "--only", "specs-diff").returncode == 0
    assert _gate(scratch, "--only", "specs-diff", "--base", "HEAD~1").returncode == 1
    assert _gate(scratch, "--only", "specs-diff", "--base", "nope").returncode == 1


def test_an_unknown_check_or_argument_is_a_usage_error(scratch: Path) -> None:
    assert _gate(scratch, "--only", "nothing").returncode == 2
    assert _gate(scratch, "--wat").returncode == 2


def _analyze(root: Path, body: str) -> None:
    tool = root / "scripts" / "maint" / "refactor" / "analyze.py"
    tool.parent.mkdir(parents=True, exist_ok=True)
    tool.write_text(body)


def test_metrics_may_stay_or_fall_and_must_not_rise(scratch: Path) -> None:
    _analyze(scratch, "print('largest cycle: 38')\nprint('local imports: 206')\n")
    assert _gate(scratch, "--record-metrics").returncode == 0
    baseline = (scratch / "refactor" / "metrics-baseline.txt").read_text()
    assert baseline == "largest_cycle 38\nlocal_imports 206\n"
    assert _gate(scratch, "--only", "metrics").returncode == 0
    _analyze(scratch, "print('largest cycle: 12')\nprint('local imports: 206')\n")
    assert _gate(scratch, "--only", "metrics").returncode == 0
    _analyze(scratch, "print('largest cycle: 12')\nprint('local imports: 207')\n")
    result = _gate(scratch, "--only", "metrics")
    assert result.returncode == 1
    assert "local_imports: 207 > 206" in result.stderr


def test_metrics_read_from_json_and_a_vanished_metric_fails(scratch: Path) -> None:
    _analyze(scratch, 'import json\nprint(json.dumps({"largest_cycle": 38, "name": "x"}))\n')
    assert _gate(scratch, "--record-metrics").returncode == 0
    _analyze(scratch, "print('{}')\n")
    result = _gate(scratch, "--only", "metrics")
    assert result.returncode == 1
