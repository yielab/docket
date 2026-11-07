"""The task loader: every key of `task.yaml` is checked and a refusal names the key."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml  # type: ignore[import-untyped]

from evals.evaluator.task import TaskError, discover, load_task
from evals.tests.conftest import TaskBuilder, task_yaml


def test_a_valid_task_loads(make_task: TaskBuilder) -> None:
    task = load_task(make_task())
    assert task.id == "fix-add"
    assert task.spec.version == 1
    assert [g.name for g in task.spec.graders.required] == ["outcome.hidden_tests"]
    assert task.hidden.is_dir() and task.repo.is_dir() and task.solution.is_dir()


def test_a_task_without_hidden_is_refused_naming_it(make_task: TaskBuilder) -> None:
    with pytest.raises(TaskError, match="hidden"):
        load_task(make_task(hidden=False))


def test_a_task_without_solution_is_refused(make_task: TaskBuilder) -> None:
    with pytest.raises(TaskError, match="solution"):
        load_task(make_task(solution="none"))


def test_a_501_character_instruction_is_refused_naming_it(make_task: TaskBuilder) -> None:
    with pytest.raises(TaskError, match="instruction"):
        load_task(make_task(instruction="x" * 501))


def test_a_500_character_instruction_is_accepted(make_task: TaskBuilder) -> None:
    load_task(make_task(instruction="x" * 500))


@pytest.mark.parametrize("version", [0, -1, "2", 1.5])
def test_version_must_be_a_positive_integer(make_task: TaskBuilder, version: object) -> None:
    with pytest.raises(TaskError, match="version"):
        load_task(make_task(version=version))


def test_required_graders_must_not_be_empty(make_task: TaskBuilder) -> None:
    with pytest.raises(TaskError, match=r"graders\.required"):
        load_task(make_task(graders={"required": [], "report": []}))


def test_an_unknown_grader_is_refused_by_name(make_task: TaskBuilder) -> None:
    graders = {"required": ["outcome.vibes"], "report": []}
    with pytest.raises(TaskError, match=r"outcome\.vibes"):
        load_task(make_task(graders=graders))


@pytest.mark.parametrize(
    "name", ["judge.scope_creep", "process.tokens", "reviewer.verdict_matches"]
)
def test_the_grader_families_of_the_spec_are_known(make_task: TaskBuilder, name: str) -> None:
    graders = {"required": ["outcome.hidden_tests"], "report": [name]}
    load_task(make_task(graders=graders))


def test_a_file_exact_grader_names_its_file_and_bytes(make_task: TaskBuilder) -> None:
    graders = {"required": [{"outcome.file_exact": {"path": "out.txt"}}]}
    with pytest.raises(TaskError, match="content"):
        load_task(make_task(graders=graders))


def test_an_unknown_key_is_refused(make_task: TaskBuilder) -> None:
    with pytest.raises(TaskError, match="surprise"):
        load_task(make_task(surprise=1))


def test_a_missing_key_is_refused_naming_it(make_task: TaskBuilder) -> None:
    path = make_task()
    data = task_yaml("fix-add", "regression")
    del data["origin"]
    (path / "task.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(TaskError, match="origin"):
        load_task(path)


def test_id_must_equal_the_directory_name(make_task: TaskBuilder) -> None:
    with pytest.raises(TaskError, match="id"):
        load_task(make_task("fix-add", id="other"))


def test_suite_must_be_known_and_match_the_parent_directory(make_task: TaskBuilder) -> None:
    with pytest.raises(TaskError, match="suite"):
        load_task(make_task(suite="mystery"))


def test_shape_must_be_known(make_task: TaskBuilder) -> None:
    with pytest.raises(TaskError, match="shape"):
        load_task(make_task(shape="dance"))


def test_discover_by_suite_id_or_everything(make_task: TaskBuilder, tmp_path: Path) -> None:
    make_task("a-one", "regression")
    make_task("b-two", "capability")
    root = tmp_path / "tasks"
    assert [t.id for t in discover(root, None)] == ["b-two", "a-one"]
    assert [t.id for t in discover(root, "capability")] == ["b-two"]
    assert [t.id for t in discover(root, "a-one")] == ["a-one"]
    with pytest.raises(TaskError, match="nothing"):
        discover(root, "nothing")


def test_discover_on_an_empty_or_missing_root_is_empty(tmp_path: Path) -> None:
    assert discover(tmp_path / "absent", None) == []
