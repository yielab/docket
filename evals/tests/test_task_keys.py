"""SUBJECT: evals/evaluator/task.py and trial.py -- `pipeline`, `pod.memory` and `limits.max_tokens`
reach the trial: a refused file names its key, and `spec_for` fills the TrialSpec fields.

Nothing here runs docket or a model; the task directories are built by `make_task`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from evals.evaluator.record import TrialSpec, run_trial
from evals.evaluator.task import TaskError, load_task
from evals.evaluator.trial import spec_for
from evals.tests.conftest import TaskBuilder

# isort: split
# evals.evaluator.record imports the world, which puts the repository root on sys.path.
from tests.support.model_server import FakeModel, say, write_file

PIPELINE = "name: trial\nsteps:\n  - plan: lead\n  - implement: implementer\n"
NOTES = "# Lead notes\n\n- MONEY-104: integer cents.\n"
POD = {"blueprint": "build", "isolation": False}


def test_a_pipeline_file_that_is_absent_is_refused_naming_the_key(make_task: TaskBuilder) -> None:
    with pytest.raises(TaskError, match="pipeline"):
        load_task(make_task(pipeline="missing.yaml"))


def test_a_memory_file_that_is_absent_is_refused_naming_the_key(make_task: TaskBuilder) -> None:
    with pytest.raises(TaskError, match="memory"):
        load_task(make_task(pod={**POD, "memory": {"lead": "lead/MEMORY.md"}}))


def test_limits_max_tokens_must_be_a_positive_integer(make_task: TaskBuilder) -> None:
    with pytest.raises(TaskError, match="max_tokens"):
        load_task(make_task(limits={"wall_seconds": 60, "max_tokens": 0}))


def test_a_grader_that_needs_role_and_tool_is_refused_without_one(make_task: TaskBuilder) -> None:
    graders = {"required": [{"governance.no_tool": {"role": "writer"}}]}
    with pytest.raises(TaskError, match="tool"):
        load_task(make_task(graders=graders))


def test_spec_for_fills_the_pipeline_memory_and_budget(make_task: TaskBuilder) -> None:
    path = make_task(
        pipeline="pipeline.yaml",
        pod={**POD, "memory": {"lead": "lead/MEMORY.md"}},
        limits={"wall_seconds": 60, "max_tokens": 9000, "turn_seconds": 600},
    )
    (path / "pipeline.yaml").write_text(PIPELINE, encoding="utf-8")
    (path / "lead").mkdir()
    (path / "lead" / "MEMORY.md").write_text(NOTES, encoding="utf-8")

    spec = spec_for(load_task(path), provider="lab", model="m", max_tokens=4000, epoch=0)

    assert spec.pipeline == PIPELINE
    assert dict(spec.memory) == {"lead": NOTES}
    assert spec.task_max_tokens == 9000
    assert spec.limits["turn_s"] == 600


def test_spec_for_leaves_the_new_keys_empty_when_the_task_sets_none(make_task: TaskBuilder) -> None:
    spec = spec_for(load_task(make_task()), provider="lab", model="m", max_tokens=4000, epoch=0)

    assert spec.pipeline is None
    assert dict(spec.memory) == {}
    assert spec.task_max_tokens is None


def test_a_seeded_memory_is_the_members_file_in_the_kept_world(tmp_path: Path) -> None:
    seed = tmp_path / "seed"
    seed.mkdir()
    (seed / "answer.txt").write_text("0\n", encoding="utf-8")
    hidden = tmp_path / "hidden"
    hidden.mkdir()
    (hidden / "test_answer.py").write_text(
        "def test_answer():\n    assert True\n", encoding="utf-8"
    )
    script = {
        "lead": [say("Plan: write 42.")],
        "implementer": [write_file("answer.txt", "42\n"), say("answer.txt holds 42.")],
        "reviewer": [say("APPROVE")],
    }
    out = tmp_path / "out"
    with FakeModel(script=script) as model:
        spec = TrialSpec(
            task="memory-seed",
            version=1,
            suite="regression",
            seed=seed,
            hidden=hidden,
            instruction="Make answer.txt hold 42",
            isolation=False,
            provider="lab",
            model="m",
            max_tokens=4000,
            operator={"approval": "approve_once"},
            limits={"wall_s": 120, "turn_s": 60},
            base_url=model.base_url,
            credential="lab-secret-value-1234",
            memory={"lead": NOTES},
            task_max_tokens=9000,
        )
        record = run_trial(spec, out, keep_world=True)

    assert record.status == "done", record.reason
    (world,) = out.glob("trial-*")
    seeded = world / "world" / "docket-home" / "state" / "workspaces" / "projects" / "trial-lead"
    assert (seeded / "MEMORY.md").read_text(encoding="utf-8") == NOTES
