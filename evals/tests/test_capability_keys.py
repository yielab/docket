"""SUBJECT: evals/evaluator/task.py, trial.py, record.py, operator.py -- the keys the capability suite
adds: `pod.apply`, `pod.fetch_domains`, `records` and the operator's `park`.

The loader and `spec_for` need no docket; the last tests run a trial against `FakeModel`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evals.evaluator.run import check_task
from evals.evaluator.task import Graders, TaskError, load_task
from evals.evaluator.trial import spec_for
from evals.evaluator.verify import run_hidden
from evals.tests.conftest import TaskBuilder

# isort: split
# evals.evaluator.record imports the world, which puts the repository root on sys.path.
from tests.support.model_server import FakeModel, call, say, write_file

from evals.evaluator.record import TrialSpec, run_trial

POD = {"blueprint": "routine", "isolation": False}
NOTES_POD = "kind: pod\nname: notes-pod\ndescription: A set for notes.\n"
NOTES_SET = (
    "kind: records\nname: notes\ndescription: Notes.\nkey: ref\ncolumns:\n"
    "  - {name: ref, type: string, required: true, description: The note id}\n"
    "  - {name: title, type: string, description: The note title}\n"
)


def _pod_config(task: Path) -> None:
    (task / "pod-config" / "records").mkdir(parents=True)
    (task / "pod-config" / "pod.yaml").write_text(NOTES_POD, encoding="utf-8")
    (task / "pod-config" / "records" / "notes.yaml").write_text(NOTES_SET, encoding="utf-8")


def test_an_apply_entry_that_is_neither_a_task_directory_nor_a_recipe_is_refused(
    make_task: TaskBuilder,
) -> None:
    with pytest.raises(TaskError, match="apply"):
        load_task(make_task(pod={**POD, "apply": ["no-such-recipe-anywhere"]}))


def test_an_apply_entry_may_be_a_shipped_recipe_or_a_directory_beside_the_task(
    make_task: TaskBuilder,
) -> None:
    path = make_task(pod={**POD, "apply": ["hacker-news", "pod-config"]})
    _pod_config(path)

    spec = spec_for(load_task(path), provider="lab", model="m", max_tokens=4000, epoch=0)

    assert spec.apply == ("hacker-news", str(path / "pod-config"))


def test_fetch_domains_and_records_reach_the_trial_spec(make_task: TaskBuilder) -> None:
    path = make_task(
        pod={**POD, "fetch_domains": ["docs.python.org", "peps.python.org"]}, records=["notes"]
    )
    (path / "solution-records").mkdir()
    (path / "solution-records" / "notes.json").write_text('{"rows": []}', encoding="utf-8")

    spec = spec_for(load_task(path), provider="lab", model="m", max_tokens=4000, epoch=0)

    assert spec.fetch_domains == ("docs.python.org", "peps.python.org")
    assert spec.records == ("notes",)


def test_a_records_set_with_no_reference_rows_is_refused_naming_the_key(
    make_task: TaskBuilder,
) -> None:
    with pytest.raises(TaskError, match="records"):
        load_task(make_task(records=["notes"]))


def test_the_operator_may_leave_an_approval_parked_and_refuses_any_other_word(
    make_task: TaskBuilder,
) -> None:
    load_task(make_task(operator={"approval": "park"}))
    with pytest.raises(TaskError, match="approval"):
        load_task(make_task("other", operator={"approval": "wait"}))


def test_the_hidden_checks_receive_the_extra_environment(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    hidden = tmp_path / "hidden"
    hidden.mkdir()
    (hidden / "test_env.py").write_text(
        "import os\n\ndef test_env():\n    assert os.environ['EVAL_RECORDS'] == 'somewhere'\n",
        encoding="utf-8",
    )

    ok = run_hidden(repo, hidden, tmp_path / "v", env={"EVAL_RECORDS": "somewhere"})
    missing = run_hidden(repo, hidden, tmp_path / "v2", env={"EVAL_RECORDS": "elsewhere"})

    assert (ok.status, missing.status) == ("pass", "fail")


def test_check_solutions_hands_the_reference_rows_to_the_hidden_checks(
    make_task: TaskBuilder,
) -> None:
    path = make_task(records=["notes"])
    (path / "solution-records").mkdir()
    (path / "solution-records" / "notes.json").write_text(
        json.dumps({"rows": [{"ref": "a"}]}), encoding="utf-8"
    )
    (path / "hidden" / "test_rows.py").write_text(
        "import json, os\nfrom pathlib import Path\n\n"
        "def test_rows():\n"
        "    assert os.environ['EVAL_SOLUTION_CHECK'] == '1'\n"
        "    rows = json.loads((Path(os.environ['EVAL_RECORDS']) / 'notes.json').read_text())['rows']\n"
        "    assert [r['ref'] for r in rows] == ['a']\n",
        encoding="utf-8",
    )

    outcomes = check_task(load_task(path))

    assert [(o.grader, o.status) for o in outcomes] == [("outcome.hidden_tests", "pass")]


def test_a_trial_applies_a_directory_exports_the_records_and_sets_the_fetch_domains(
    tmp_path: Path,
) -> None:
    _pod_config(tmp_path)
    seed = tmp_path / "seed"
    seed.mkdir()
    (seed / "README.md").write_text("notes\n", encoding="utf-8")
    hidden = tmp_path / "hidden"
    hidden.mkdir()
    (hidden / "test_rows.py").write_text(
        "import json, os\nfrom pathlib import Path\n\n"
        "def test_rows():\n"
        "    rows = json.loads((Path(os.environ['EVAL_RECORDS']) / 'notes.json').read_text())['rows']\n"
        "    assert [r['title'] for r in rows] == ['Alpha']\n",
        encoding="utf-8",
    )
    script = {"analyst": [call("rec__notes__add", "k1", ref="a", title="Alpha"), say("Added.")]}
    with FakeModel(script=script) as model:
        spec = TrialSpec(
            task="notes",
            version=1,
            suite="capability",
            seed=seed,
            hidden=hidden,
            instruction="Add the note Alpha to the notes set.",
            isolation=False,
            provider="lab",
            model="m",
            max_tokens=4000,
            operator={"approval": "approve_once"},
            limits={"wall_s": 120, "turn_s": 60},
            blueprint="routine",
            pipeline="name: add\nsteps:\n  - add: analyst\n",
            base_url=model.base_url,
            credential="lab-secret-value-1234",
            apply=(str(tmp_path / "pod-config"),),
            fetch_domains=("docs.python.org",),
            records=("notes",),
        )
        record = run_trial(spec, tmp_path / "out", keep_world=True)

    assert record.status == "done", record.reason
    assert record.verifier["status"] == "pass", record.verifier
    (world,) = (tmp_path / "out").glob("trial-*")
    lead = world / "world" / "docket-home" / "state" / "workspaces" / "projects" / "trial-lead"
    assert "docs.python.org" in "".join(
        p.read_text(encoding="utf-8") for p in lead.glob("*.json") if p.is_file()
    )


def test_a_parked_check_edit_ends_the_trial_as_a_pass_when_the_task_expects_it(
    tmp_path: Path,
) -> None:
    seed = tmp_path / "seed"
    (seed / "checks").mkdir(parents=True)
    (seed / "checks" / "verify.sh").write_text("exit 1\n", encoding="utf-8")
    hidden = tmp_path / "hidden"
    hidden.mkdir()
    (hidden / "test_any.py").write_text("def test_any():\n    assert True\n", encoding="utf-8")
    script = {
        "lead": [say("Plan: make the check pass.")],
        "implementer": [write_file("checks/verify.sh", "exit 0\n"), say("Updated the check.")],
    }
    graders = Graders.model_validate(
        {"required": [{"outcome.task_status": {"status": "waiting_approval"}}]}
    )
    with FakeModel(script=script) as model:
        spec = TrialSpec(
            task="parked",
            version=1,
            suite="capability",
            seed=seed,
            hidden=hidden,
            instruction="Make sh checks/verify.sh exit 0.",
            isolation=False,
            provider="lab",
            model="m",
            max_tokens=4000,
            operator={"approval": "park"},
            limits={"wall_s": 120, "turn_s": 60},
            pipeline=(
                "name: checked\nsteps:\n  - plan: lead\n"
                '  - implement: implementer\n    verify: "sh checks/verify.sh"\n'
            ),
            base_url=model.base_url,
            credential="lab-secret-value-1234",
        )
        record = run_trial(spec, tmp_path / "out", graders=graders)

    assert record.status == "waiting_approval", record.reason
    assert [(a["kind"], a["answer"]) for a in record.asks] == [("approval", "park")]
    assert "edits what checks it" in record.asks[0]["prompt"]
    assert record.passed and record.failure_class is None


CODES = {
    "message": "Which discount code should the reply offer?",
    "kind": "decision",
    "options": [
        {"id": "amber", "label": "AMBER-15", "description": "15 percent"},
        {"id": "cedar", "label": "CEDAR-5", "description": "5 percent"},
    ],
    "recommendation": {"optionId": "cedar", "rationale": "the smaller one"},
}


def _consult_trial(tmp_path: Path, answer: str) -> tuple[int, str, list[dict[str, str]]]:
    seed = tmp_path / "seed"
    seed.mkdir()
    (seed / "code.txt").write_text("none\n", encoding="utf-8")
    hidden = tmp_path / "hidden"
    hidden.mkdir()
    (hidden / "test_any.py").write_text("def test_any():\n    assert True\n", encoding="utf-8")
    script = {
        "lead": [call("consult", "k1", questions=[CODES]), say("Plan: use the answered code.")],
        "implementer": [say("Done.")],
    }
    with FakeModel(script=script) as model:
        spec = TrialSpec(
            task="codes",
            version=1,
            suite="capability",
            seed=seed,
            hidden=hidden,
            instruction="Choose a discount code.",
            isolation=False,
            provider="lab",
            model="m",
            max_tokens=4000,
            operator={"approval": "approve_once", "consult": answer},
            limits={"wall_s": 120, "turn_s": 60},
            pipeline="name: codes\nsteps:\n  - plan: lead\n  - implement: implementer\n",
            base_url=model.base_url,
            credential="lab-secret-value-1234",
        )
        record = run_trial(spec, tmp_path / "out")
    return len(model.by_role("lead")), record.failure_class or "", record.asks


def test_a_scripted_answer_naming_an_options_label_picks_that_option(tmp_path: Path) -> None:
    leads, failure, asks = _consult_trial(tmp_path, "Offer code AMBER-15 for thirty days.")

    assert failure == ""
    assert [(a["kind"], a["answer"]) for a in asks] == [
        ("consult", "Offer code AMBER-15 for thirty days.")
    ]
    assert leads == 2, "the Lead's hop ran again with the answer"


def test_a_scripted_answer_that_matches_no_option_ends_the_trial_as_harness(
    tmp_path: Path,
) -> None:
    _, failure, asks = _consult_trial(tmp_path, "Offer whatever you like.")

    assert failure == "harness"
    assert asks == []
