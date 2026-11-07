"""`check-solutions`: a reference solution is applied in a clean repository and graded with no model."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from evals.harness.run import app
from evals.tests.conftest import TaskBuilder

runner = CliRunner()


def check(root: Path, *selector: str) -> tuple[int, str]:
    result = runner.invoke(app, ["check-solutions", *selector, "--root", str(root)])
    return result.exit_code, result.output


def test_a_correct_file_tree_solution_exits_zero(make_task: TaskBuilder, tmp_path: Path) -> None:
    make_task(solution="fixed")
    code, output = check(tmp_path / "tasks")
    assert code == 0, output
    assert "fix-add" in output


def test_a_correct_patch_solution_exits_zero(make_task: TaskBuilder, tmp_path: Path) -> None:
    make_task(solution="patch")
    code, output = check(tmp_path / "tasks")
    assert code == 0, output


def test_a_solution_that_leaves_a_hidden_test_red_exits_one_naming_it(
    make_task: TaskBuilder, tmp_path: Path
) -> None:
    make_task(solution="buggy")
    code, output = check(tmp_path / "tasks")
    assert code == 1
    assert "fix-add" in output and "outcome.hidden_tests" in output


def test_the_first_failing_task_is_named(make_task: TaskBuilder, tmp_path: Path) -> None:
    make_task("a-ok", solution="fixed")
    make_task("b-broken", solution="buggy")
    code, output = check(tmp_path / "tasks")
    assert code == 1
    assert "b-broken" in output


def test_the_seed_is_not_changed_by_a_check(make_task: TaskBuilder, tmp_path: Path) -> None:
    task = make_task(solution="fixed")
    before = (task / "repo" / "calc.py").read_bytes()
    check(tmp_path / "tasks")
    assert (task / "repo" / "calc.py").read_bytes() == before


def test_file_exact_compares_the_bytes_the_task_names(
    make_task: TaskBuilder, tmp_path: Path
) -> None:
    fixed = "def add(a, b):\n    return a + b\n"
    graders = {
        "required": [
            "outcome.hidden_tests",
            {"outcome.file_exact": {"path": "calc.py", "content": fixed}},
        ]
    }
    make_task(graders=graders)
    code, output = check(tmp_path / "tasks")
    assert code == 0, output
    wrong = {"required": [{"outcome.file_exact": {"path": "calc.py", "content": "nope"}}]}
    make_task("other", graders=wrong)
    code, output = check(tmp_path / "tasks", "other")
    assert code == 1
    assert "outcome.file_exact" in output


def test_task_status_needs_a_trial_and_is_skipped(make_task: TaskBuilder, tmp_path: Path) -> None:
    graders = {"required": ["outcome.hidden_tests", {"outcome.task_status": {"status": "done"}}]}
    make_task(graders=graders)
    code, output = check(tmp_path / "tasks")
    assert code == 0, output
    assert "skipped" in output


def test_a_malformed_task_exits_one_naming_the_key(make_task: TaskBuilder, tmp_path: Path) -> None:
    make_task(instruction="x" * 501)
    code, output = check(tmp_path / "tasks")
    assert code == 1
    assert "instruction" in output


def test_no_tasks_is_nothing_to_check(tmp_path: Path) -> None:
    code, output = check(tmp_path / "absent")
    assert code == 0
    assert "no tasks" in output
