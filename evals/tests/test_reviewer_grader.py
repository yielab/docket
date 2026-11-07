"""SUBJECT: evals/evaluator/graders/reviewer.py -- `reviewer.verdict_matches` compares the verdict the
Reviewer's hop recorded with the hidden label of the diff it was given.

Doctored frozen traces for the grader, three trials against `FakeModel` for the trace docket
writes, the task loader's refusal of an unlabelled case, `check-solutions` as the label's proof, the
report's table, and a census of the committed cases (no model, no execution).
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
import yaml  # type: ignore[import-untyped]
from typer.testing import CliRunner

from evals.evaluator.graders import GradeContext, grade_one
from evals.evaluator.graders.reviewer import judge
from evals.evaluator.metrics import wilson
from evals.evaluator.report import render_markdown, reviewer_table, summarize
from evals.evaluator.run import DEFAULT_ROOT, app
from evals.evaluator.task import Grader, TaskError, discover, load_task
from evals.evaluator.trial import run_task
from evals.tests.lines import trial

# isort: split
# evals.evaluator.trial imports the world, which puts the repository root on sys.path.
from tests.support.model_server import FakeModel, say

runner = CliRunner()
VERDICT = Grader(name="reviewer.verdict_matches")
LABELLED_BY = "integrator (maintainer's delegation, 2026-11-07), confirmed by check-solutions"

BASE = "def add(a, b):\n    return a - b\n"
VISIBLE = "from calc import add\n\n\ndef test_visible():\n    assert add(0, 0) == 0\n    assert add(1, 2) == 3\n"
HIDDEN = "import calc\n\n\ndef test_hidden():\n    assert calc.add(2, 3) == 5\n    assert calc.add(7, 1) == 8\n"
PIPELINE = (
    "name: review-one-diff\nsteps:\n  - review: reviewer\n    verdict: [APPROVE, REQUEST-CHANGES]\n"
    "    on: {REQUEST-CHANGES: stop}\n"
)


def _patch(after: str) -> str:
    return (
        "--- a/calc.py\n+++ b/calc.py\n@@ -1,2 +1,2 @@\n def add(a, b):\n"
        f"-    return a - b\n+{after}\n"
    )


GOOD_PATCH = _patch("    return a + b")
BAD_PATCH = _patch("    return a + b + (a == 7)")  # passes the visible test, fails the hidden one
BROKEN_PATCH = _patch("    return a * b")  # fails the visible test as well


def make_case(
    root: Path,
    name: str,
    label: str | None,
    patch: str,
    *,
    shown: str | None = None,
    keys: dict[str, str] | None = None,
) -> Path:
    """A reviewer case under `root/reviewer/<name>`: base repo, the diff, hidden test, label."""
    case = root / "reviewer" / name
    for sub in ("repo/tests", "hidden", "solution"):
        (case / sub).mkdir(parents=True)
    (case / "repo" / "calc.py").write_text(BASE, encoding="utf-8")
    (case / "repo" / "tests" / "test_calc.py").write_text(VISIBLE, encoding="utf-8")
    (case / "repo" / "REQUEST.md").write_text("Make add() add.\n", encoding="utf-8")
    (case / "repo" / "change.diff").write_text(patch if shown is None else shown, encoding="utf-8")
    (case / "hidden" / "test_change.py").write_text(HIDDEN, encoding="utf-8")
    (case / "solution" / "change.patch").write_text(patch, encoding="utf-8")
    (case / "pipeline.yaml").write_text(PIPELINE, encoding="utf-8")
    task = {
        "id": name,
        "version": 1,
        "suite": "reviewer",
        "shape": "build",
        "origin": "a fixture: add() subtracts",
        "instruction": "Review change.diff against REQUEST.md; end with APPROVE or REQUEST-CHANGES.",
        "pipeline": "pipeline.yaml",
        "pod": {"blueprint": "build", "isolation": False},
        "operator": {"approval": "approve_once"},
        "graders": {"required": ["reviewer.verdict_matches"], "report": ["process.tokens"]},
        "limits": {"wall_seconds": 120},
    }
    (case / "task.yaml").write_text(yaml.safe_dump(task), encoding="utf-8")
    if label is not None:
        why = {"label": label, "why": "a fixture", "labelled_by": LABELLED_BY}
        (case / "label.yaml").write_text(yaml.safe_dump({**why, **(keys or {})}), encoding="utf-8")
    return case


# -- the grader -----------------------------------------------------------------------------------


def _hop(verdict: str | None, role: str = "reviewer") -> dict[str, Any]:
    payload = {"role": role, "verdict": verdict, "ok": True}
    return {"event_type": "hop_finished", "agent_role": role, "payload": payload}


def _frozen(root: Path, events: Sequence[dict[str, Any]]) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "trace.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events), "utf-8")
    return root


def _grade(tmp_path: Path, label: str | None, events: Sequence[dict[str, Any]]) -> Any:
    return grade_one(VERDICT, GradeContext(frozen=_frozen(tmp_path / "f", events), label=label))


@pytest.mark.parametrize(
    ("label", "verdict", "status", "words"),
    [
        ("bad", "approve", "fail", "false approval"),
        ("good", "request-changes", "fail", "false rejection"),
        ("bad", "request-changes", "pass", "correct rejection"),
        ("good", "approve", "pass", "correct approval"),
        ("good", None, "fail", "no verdict"),
        ("bad", None, "fail", "no verdict"),
    ],
)
def test_the_verdict_is_compared_with_the_label(
    tmp_path: Path, label: str, verdict: str | None, status: str, words: str
) -> None:
    result = _grade(tmp_path, label, [_hop(verdict)])

    assert result.status == status
    assert words in result.reason


def test_the_last_reviewer_hop_decides_and_other_roles_are_ignored(tmp_path: Path) -> None:
    events = [_hop("request-changes"), _hop("approve", role="implementer"), _hop("approve")]

    assert _grade(tmp_path, "good", events).status == "pass"


def test_without_a_trace_a_reviewer_hop_or_a_label_the_grader_errors(tmp_path: Path) -> None:
    assert grade_one(VERDICT, GradeContext(label="bad")).status == "error"
    assert _grade(tmp_path / "a", "bad", []).status == "error"
    assert _grade(tmp_path / "b", None, [_hop("approve")]).status == "error"
    assert _grade(tmp_path / "c", "maybe", [_hop("approve")]).status == "error"


def test_judge_names_the_label_and_the_verdict() -> None:
    result = judge("bad", "approve")

    assert (result.status, result.reason) == ("fail", "bad diff, verdict approve: false approval")


# -- the loader -----------------------------------------------------------------------------------


def test_a_reviewer_case_without_a_label_is_refused_naming_the_file(tmp_path: Path) -> None:
    case = make_case(tmp_path, "r-unlabelled", None, GOOD_PATCH)

    with pytest.raises(TaskError, match=r"label\.yaml"):
        load_task(case)


@pytest.mark.parametrize(
    ("keys", "named"),
    [
        ({"label": "fine"}, "label"),
        ({"why": ""}, "why"),
        ({"labelled_by": ""}, "labelled_by"),
    ],
)
def test_a_label_must_be_good_or_bad_with_a_reason_and_a_labeller(
    tmp_path: Path, keys: dict[str, str], named: str
) -> None:
    case = make_case(tmp_path, "r-odd", "good", GOOD_PATCH, keys=keys)

    with pytest.raises(TaskError, match=named):
        load_task(case)


def test_a_labelled_case_loads(tmp_path: Path) -> None:
    (task,) = discover(make_case(tmp_path, "r-ok", "bad", BAD_PATCH).parents[1], "reviewer")

    assert task.id == "r-ok"


# -- check-solutions is the label's proof ---------------------------------------------------------


def check(root: Path, *selector: str) -> tuple[int, str]:
    result = runner.invoke(app, ["check-solutions", *selector, "--root", str(root)])
    return result.exit_code, result.output


def test_a_good_diff_that_passes_and_a_bad_one_that_fails_the_hidden_test_exit_zero(
    tmp_path: Path,
) -> None:
    make_case(tmp_path, "r-good", "good", GOOD_PATCH)
    make_case(tmp_path, "r-bad", "bad", BAD_PATCH)

    code, output = check(tmp_path, "reviewer")

    assert code == 0, output
    assert "ok   r-good" in output and "ok   r-bad" in output


def test_a_bad_label_on_a_diff_that_passes_the_hidden_test_exits_one(tmp_path: Path) -> None:
    make_case(tmp_path, "r-wrong", "bad", GOOD_PATCH)

    code, output = check(tmp_path, "reviewer")

    assert code == 1
    assert "r-wrong" in output and "bad" in output and "hidden" in output


def test_a_good_label_on_a_diff_that_fails_the_hidden_test_exits_one(tmp_path: Path) -> None:
    make_case(tmp_path, "r-wrong", "good", BAD_PATCH)

    code, output = check(tmp_path, "reviewer")

    assert code == 1
    assert "r-wrong" in output and "good" in output


def test_a_bad_diff_must_pass_the_visible_tests_to_be_a_mutant(tmp_path: Path) -> None:
    make_case(tmp_path, "r-loud", "bad", BROKEN_PATCH)

    code, output = check(tmp_path, "reviewer")

    assert code == 1
    assert "r-loud" in output and "visible" in output


def test_the_diff_the_reviewer_reads_is_the_diff_that_was_proven(tmp_path: Path) -> None:
    make_case(tmp_path, "r-swapped", "good", GOOD_PATCH, shown=BAD_PATCH)

    code, output = check(tmp_path, "reviewer")

    assert code == 1
    assert "r-swapped" in output and "change.diff" in output


# -- trials against FakeModel ---------------------------------------------------------------------


def _trial(tmp_path: Path, label: str, replies: list[Any]) -> Any:
    patch = GOOD_PATCH if label == "good" else BAD_PATCH
    task = load_task(make_case(tmp_path, f"r-{label}", label, patch))
    with FakeModel(script={"reviewer": replies}) as model:
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
    return record


@pytest.mark.parametrize(
    ("label", "reply", "passed", "words"),
    [
        ("bad", "Looks right.\n\nAPPROVE", False, "false approval"),
        ("good", "It drops the sign.\n\nREQUEST-CHANGES", False, "false rejection"),
        ("bad", "The 7 case is wrong.\n\nREQUEST-CHANGES", True, "correct rejection"),
    ],
)
def test_one_reviewer_hop_on_the_diff_is_graded_against_the_label(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    label: str,
    reply: str,
    passed: bool,
    words: str,
) -> None:
    monkeypatch.chdir(tmp_path)

    record = _trial(tmp_path, label, [say(reply)])

    graded = record.graders["reviewer.verdict_matches"]
    assert words in graded["reason"]
    assert record.passed is passed
    assert [s for s in record.trace_skeleton if s[0] == "hop_started"] == [
        ["hop_started", "reviewer", "review"]
    ]
    if passed:
        assert record.failure_class is None
    else:
        assert record.failure_class == "model"


def test_a_reply_without_a_verdict_is_a_model_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    record = _trial(tmp_path, "good", [say("Seems fine to me."), say("Yes, fine.")])

    assert "no verdict" in record.graders["reviewer.verdict_matches"]["reason"]
    assert record.passed is False
    assert record.failure_class == "model"


# -- the report -----------------------------------------------------------------------------------


def _record(model: str, label: str, verdict: str | None, **extra: Any) -> dict[str, Any]:
    result = judge(label, verdict)
    line = trial(f"r-{label}@1", result.status == "pass", "model", suite="reviewer", model=model)
    graded = {"status": result.status, "reason": result.reason, "required": True}
    line["graders"] = {"reviewer.verdict_matches": graded}
    line.update(extra)
    return line


def test_the_table_has_false_approval_and_rejection_rates_per_model_with_wilson_intervals() -> None:
    lines = (
        [_record("p/a", "bad", "approve")] * 3
        + [_record("p/a", "bad", "request-changes")] * 7
        + [_record("p/a", "good", "request-changes")] * 2
        + [_record("p/a", "good", "approve")] * 8
        + [_record("p/b", "bad", "request-changes")] * 4
        + [_record("p/b", "good", "approve")] * 4
    )

    table = reviewer_table(lines)

    a, b = table["p/a"], table["p/b"]
    assert (a["bad"], a["false_approvals"], a["good"], a["false_rejections"]) == (10, 3, 10, 2)
    assert a["false_approval_rate"] == pytest.approx(0.3)
    assert a["false_approval_ci"] == pytest.approx(list(wilson(0.3, 10)))
    assert a["false_rejection_rate"] == pytest.approx(0.2)
    assert a["false_rejection_ci"] == pytest.approx(list(wilson(0.2, 10)))
    assert a["accuracy"] == pytest.approx(0.75)
    assert (b["false_approvals"], b["false_rejections"], b["accuracy"]) == (0, 0, 1.0)
    assert summarize(lines)["reviewer"] == table


def test_a_reply_with_no_verdict_is_shown_and_left_out_of_the_rates() -> None:
    lines = [_record("m", "bad", "approve"), _record("m", "bad", None), _record("m", "good", None)]

    row = reviewer_table(lines)["m"]

    assert (row["bad"], row["good"], row["no_verdict"]) == (1, 0, 2)
    assert row["false_approval_rate"] == 1.0


def test_harness_trials_and_errored_graders_are_not_counted() -> None:
    harness = _record("m", "bad", "approve", failure_class="harness", passed=False)
    errored = _record("m", "bad", "approve")
    errored["graders"]["reviewer.verdict_matches"]["status"] = "error"

    assert (
        reviewer_table([harness, errored, _record("m", "bad", "request-changes")])["m"]["bad"] == 1
    )


def test_a_run_without_reviewer_trials_has_no_table() -> None:
    assert reviewer_table([trial("t@1", True)]) == {}


def test_the_summary_prints_one_table_with_both_rates_and_the_intervals() -> None:
    lines = [_record("p/a", "bad", "approve"), _record("p/a", "good", "approve")]

    text = render_markdown(summarize(lines))

    rows = [x for x in text.splitlines() if x.startswith("| model ")]
    assert len(rows) == 1
    assert "false approval" in rows[0] and "false rejection" in rows[0]
    assert "| p/a |" in text and "(n=1," in text


# -- the committed cases --------------------------------------------------------------------------


def _cases() -> list[Path]:
    return sorted(p for p in (DEFAULT_ROOT / "reviewer").iterdir() if p.is_dir())


def test_there_are_thirty_good_and_thirty_bad_cases_each_labelled_by_the_integrator() -> None:
    labels = [yaml.safe_load((c / "label.yaml").read_text("utf-8")) for c in _cases()]

    assert sorted(x["label"] for x in labels).count("good") == 30
    assert sorted(x["label"] for x in labels).count("bad") == 30
    assert all(x["labelled_by"] == LABELLED_BY and x["why"].strip() for x in labels)


def test_every_committed_case_loads_and_names_its_one_grader() -> None:
    tasks = discover(DEFAULT_ROOT, "reviewer")

    assert len(tasks) == 60
    assert all(
        [g.name for g in t.spec.graders.required] == ["reviewer.verdict_matches"] for t in tasks
    )
    assert all(len(t.spec.instruction) <= 500 for t in tasks)
