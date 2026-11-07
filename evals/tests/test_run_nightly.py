"""SUBJECT: evals/evaluator/nightly.py -- the per-task alarm against a base, and the `run` and
`nightly` commands: synthetic `trials.jsonl` lines for the alarm, `FakeModel` for the commands."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from evals.evaluator.nightly import alarms, unpaired
from evals.evaluator.run import app
from evals.tests.conftest import FIXED, TaskBuilder
from evals.tests.lines import trial

# isort: split
# evals.evaluator.trial imports the world, which puts the repository root on sys.path.
from tests.support.model_server import FakeModel, Step, say, write_file

runner = CliRunner()


def epochs(task: str, passes: int, total: int = 3) -> list[dict[str, Any]]:
    return [trial(task, i < passes, "model", epoch=i) for i in range(total)]


def tasks(passes: dict[str, int]) -> list[dict[str, Any]]:
    return [line for task, count in passes.items() for line in epochs(task, count)]


def write_run(directory: Path, lines: list[dict[str, Any]]) -> Path:
    directory.mkdir(parents=True)
    text = "".join(json.dumps(line) + "\n" for line in lines)
    (directory / "trials.jsonl").write_text(text, encoding="utf-8")
    return directory


def test_a_task_that_was_three_of_three_and_is_now_one_of_three_alarms() -> None:
    base = tasks({"a@1": 3, "b@1": 3})
    head = tasks({"a@1": 1, "b@1": 3})

    (alarm,) = alarms(head, base)

    assert alarm.task == "a@1"
    assert (alarm.base_passes, alarm.base_n, alarm.head_passes, alarm.head_n) == (3, 3, 1, 3)
    assert "a@1" in str(alarm) and "3/3" in str(alarm) and "1/3" in str(alarm)


def test_two_of_three_does_not_alarm_nor_does_a_base_that_was_not_perfect() -> None:
    assert alarms(tasks({"a@1": 2}), tasks({"a@1": 3})) == []
    assert alarms(tasks({"a@1": 0}), tasks({"a@1": 2})) == []


def test_infra_and_harness_failures_are_excluded_before_counting() -> None:
    head = [trial("a@1", True), trial("a@1", False, "infra"), trial("a@1", False, "harness")]
    assert alarms(head, tasks({"a@1": 3})) == []
    model = [
        trial("a@1", False, "infra"),
        trial("a@1", False, "model"),
        trial("a@1", False, "model"),
    ]
    assert [a.task for a in alarms(model, tasks({"a@1": 3}))] == ["a@1"]
    base = [*epochs("a@1", 2), trial("a@1", False, "infra", epoch=2)]
    assert alarms(tasks({"a@1": 0}), base) == [], "an infra trial must not make a perfect base"


def test_a_task_new_or_changed_in_version_is_listed_never_alarmed() -> None:
    base = tasks({"a@1": 3, "gone@1": 3})
    head = tasks({"a@2": 0, "new@1": 0})

    assert alarms(head, base) == []
    notes = unpaired(head, base)
    assert any("a: version 1 -> 2" in n for n in notes)
    assert any("new@1" in n and "not in the base" in n for n in notes)


def test_a_task_with_no_counted_trial_is_listed_as_unscored() -> None:
    head = [trial("a@1", False, "infra", epoch=i) for i in range(3)]
    assert any("a@1" in n and "no counted" in n for n in unpaired(head, tasks({"a@1": 3})))


def _tree(make_task: TaskBuilder) -> Path:
    return make_task().parent.parent


def _lazy_script() -> dict[str, list[Step]]:
    return {
        "lead": [say("Plan: leave it.")],
        "implementer": [say("done")],
        "reviewer": [say("APPROVE")],
    }


def test_nightly_exits_one_and_names_the_task_that_regressed(
    make_task: TaskBuilder, tmp_path: Path
) -> None:
    root = _tree(make_task)
    base = write_run(tmp_path / "base", tasks({"fix-add@1": 3}))
    out = tmp_path / "out"
    with FakeModel(script=_lazy_script(), repeat_last=True) as model:
        done = runner.invoke(
            app,
            [
                "nightly",
                "--root",
                str(root),
                "--base",
                str(base),
                "--out",
                str(out),
                "--base-url",
                model.base_url,
                "--epochs",
                "2",
            ],
        )

    assert done.exit_code == 1, done.output
    assert "ALARM fix-add@1" in done.output
    lines = (out / "trials.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2 and not json.loads(lines[0])["passed"]


def test_nightly_with_no_base_reports_and_exits_zero(
    make_task: TaskBuilder, tmp_path: Path
) -> None:
    root = _tree(make_task)
    with FakeModel(script=_lazy_script(), repeat_last=True) as model:
        done = runner.invoke(
            app,
            [
                "nightly",
                "--root",
                str(root),
                "--out",
                str(tmp_path / "out"),
                "--base-url",
                model.base_url,
                "--epochs",
                "1",
            ],
        )

    assert done.exit_code == 0, done.output
    assert "no base" in done.output and "ALARM" not in done.output


def test_nightly_with_a_base_that_cannot_be_found_fails_before_running(tmp_path: Path) -> None:
    out = tmp_path / "o"
    done = runner.invoke(app, ["nightly", "--base", str(tmp_path / "nope"), "--out", str(out)])

    assert done.exit_code == 1 and done.output.startswith("FAIL")
    assert not out.exists()


def test_nightly_with_no_regression_tasks_says_so_and_exits_zero(tmp_path: Path) -> None:
    (tmp_path / "tasks" / "regression").mkdir(parents=True)
    done = runner.invoke(
        app, ["nightly", "--root", str(tmp_path / "tasks"), "--out", str(tmp_path / "o")]
    )

    assert done.exit_code == 0 and "no tasks" in done.output


def test_run_writes_the_trials_and_a_summary_with_the_verdict_line_first(
    make_task: TaskBuilder, tmp_path: Path
) -> None:
    root = _tree(make_task)
    script = {
        "lead": [say("Plan: fix add().")],
        "implementer": [write_file("calc.py", FIXED), say("add() adds.")],
        "reviewer": [say("APPROVE")],
    }
    out = tmp_path / "out"
    with FakeModel(script=script) as model:
        done = runner.invoke(
            app,
            [
                "run",
                "regression",
                "--root",
                str(root),
                "--provider",
                "lab",
                "--model",
                "m",
                "--epochs",
                "1",
                "--out",
                str(out),
                "--base-url",
                model.base_url,
            ],
        )

    assert done.exit_code == 0, done.output
    (line,) = (out / "trials.jsonl").read_text(encoding="utf-8").splitlines()
    assert json.loads(line)["task"] == "fix-add@1"
    first = (out / "summary.md").read_text(encoding="utf-8").splitlines()[0]
    assert first.startswith("regression | lab/m | 1 tasks x 1 epochs")
    assert done.output.splitlines()[0] == first
    assert json.loads((out / "summary.json").read_text(encoding="utf-8"))["trials"] == 1


def test_run_refuses_a_remote_key_variable_that_is_not_set(
    make_task: TaskBuilder, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _tree(make_task)
    out = tmp_path / "o"
    monkeypatch.delenv("EVAL_TEST_KEY", raising=False)

    done = runner.invoke(
        app,
        [
            "run",
            "regression",
            "--root",
            str(root),
            "--provider",
            "p",
            "--model",
            "m",
            "--credential-env",
            "EVAL_TEST_KEY",
            "--out",
            str(out),
        ],
    )

    assert done.exit_code == 1 and "EVAL_TEST_KEY" in done.output
    assert not out.exists()
