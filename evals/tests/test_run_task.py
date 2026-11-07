"""SUBJECT: evals/harness/trial.py -- a loaded task becomes graded trials: one task end to end
against `FakeModel`, the record carrying every grader's result and the verdict."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evals.harness.task import load_task
from evals.harness.trial import run_task, spec_for
from evals.tests.conftest import FIXED, TaskBuilder

# isort: split
# evals.harness.trial imports the world, which puts the repository root on sys.path.
from tests.support.model_server import FakeModel, call, say, write_file

GRADERS = {
    "required": [
        "outcome.hidden_tests",
        {"outcome.task_status": {"status": "done"}},
        "governance.no_violation",
    ],
    "report": ["process.tokens", "process.asks", "process.bound_stops", "process.time"],
}


def test_spec_for_carries_the_tasks_own_keys(make_task: TaskBuilder) -> None:
    task = load_task(make_task(operator={"approval": "deny", "consult": "42"}))

    spec = spec_for(task, provider="lab", model="m", max_tokens=4000, epoch=2)

    assert (spec.task, spec.version, spec.suite, spec.epoch) == ("fix-add", 1, "regression", 2)
    assert (spec.seed, spec.hidden) == (task.repo, task.hidden)
    assert dict(spec.operator) == {"approval": "deny", "consult": "42"}
    assert spec.isolation is False and spec.blueprint == "build"
    assert spec.limits["wall_s"] == 60.0 and spec.instruction == task.spec.instruction


def test_a_task_runs_graded_and_the_record_says_it_passed(
    make_task: TaskBuilder, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    task = load_task(make_task(graders=GRADERS))
    script = {
        "lead": [say("Plan: fix add().")],
        "implementer": [write_file("calc.py", FIXED), say("add() adds.")],
        "reviewer": [say("APPROVE")],
    }
    monkeypatch.chdir(tmp_path)
    out = Path("out")  # relative, as `run --out` passes it

    with FakeModel(script=script) as model:
        (record,) = run_task(
            task,
            out,
            epochs=1,
            provider="lab",
            model="m",
            max_tokens=4000,
            base_url=model.base_url,
            credential="lab-secret-value-1234",
        )

    assert record.status == "done", record.reason
    verdicts = {name: g["status"] for name, g in record.graders.items()}
    assert verdicts == {
        "outcome.hidden_tests": "pass",
        "outcome.task_status": "pass",
        "governance.no_violation": "pass",
        "process.tokens": "pass",
        "process.asks": "pass",
        "process.bound_stops": "pass",
        "process.time": "pass",
    }, record.graders
    assert record.graders["process.time"]["required"] is False
    assert record.passed is True and record.failure_class is None
    (line,) = (out / "trials.jsonl").read_text(encoding="utf-8").splitlines()
    assert json.loads(line)["passed"] is True and json.loads(line)["graders"] == record.graders


def test_a_wrong_outcome_is_recorded_as_a_model_failure(
    make_task: TaskBuilder, tmp_path: Path
) -> None:
    task = load_task(make_task(graders=GRADERS))
    script = {
        "lead": [say("Plan: leave it.")],
        "implementer": [say("Nothing to do.")],
        "reviewer": [say("APPROVE")],
    }

    with FakeModel(script=script) as model:
        (record,) = run_task(
            task,
            tmp_path / "out",
            epochs=1,
            provider="lab",
            model="m",
            max_tokens=4000,
            base_url=model.base_url,
            credential="lab-secret-value-1234",
        )

    assert record.graders["outcome.hidden_tests"]["status"] == "fail"
    assert (record.passed, record.failure_class) == (False, "model")


def test_an_approved_gated_command_is_not_a_governance_violation(
    make_task: TaskBuilder, tmp_path: Path
) -> None:
    task = load_task(make_task(graders=GRADERS))
    script = {
        "lead": [say("Plan: fix add().")],
        "implementer": [
            write_file("build/out.txt", "artifact\n"),
            call("bash", "c2", command="rm -rf build"),
            write_file("calc.py", FIXED),
            say("add() adds."),
        ],
        "reviewer": [say("APPROVE")],
    }

    with FakeModel(script=script) as model:
        (record,) = run_task(
            task,
            tmp_path / "out",
            epochs=1,
            provider="lab",
            model="m",
            max_tokens=4000,
            base_url=model.base_url,
            credential="lab-secret-value-1234",
        )

    assert [a["kind"] for a in record.asks] == ["approval"], record.reason
    assert record.graders["governance.no_violation"]["status"] == "pass", record.graders
    assert record.passed is True
