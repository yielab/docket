"""SUBJECT: evals/evaluator/{world,operator,record}.py -- a trial runs in a clean world, a scripted
operator answers its pauses, and the run leaves one scrubbed record.

The model is `FakeModel`; the world, the CLI, the audit log and the worktree are real.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from evals.evaluator.record import TrialRecord, TrialSpec, append_record, docket_commit, run_trial
from evals.evaluator.world import TrialWorld, build_world, provider_command, without_virtualenvs

# isort: split
# evals.evaluator.world puts the repository root on sys.path, so `tests` imports after it.
from tests.support.model_server import FakeModel, Step, call, say, truncated, write_file

PIPELINE = "name: trial\nsteps:\n  - plan: lead\n  - implement: implementer\n"
CHECK = "from pathlib import Path\n\ndef test_answer():\n    assert Path('answer.txt').read_text() == '42\\n'\n"
QUESTION = {
    "message": "Which answer should the file hold?",
    "kind": "decision",
    "options": [
        {"id": "42", "label": "42", "description": "the one"},
        {"id": "43", "label": "43", "description": "the other"},
    ],
    "recommendation": {"optionId": "42", "rationale": "it is the answer"},
}
KEY = "sk-ant-api03-" + "Zq" * 20


@contextmanager
def _model(implementer: Sequence[Step]) -> Iterator[FakeModel]:
    script: dict[str, Sequence[Step]] = {
        "lead": [say("Plan: write 42 into answer.txt.")],
        "implementer": list(implementer),
    }
    with FakeModel(script=script) as model:
        yield model


def _spec(tmp_path: Path, model: FakeModel, operator: Mapping[str, str] | None = None) -> TrialSpec:
    seed = tmp_path / "seed"
    seed.mkdir()
    (seed / "answer.txt").write_text("0\n", encoding="utf-8")
    hidden = tmp_path / "hidden"
    hidden.mkdir()
    (hidden / "test_answer.py").write_text(CHECK, encoding="utf-8")
    return TrialSpec(
        task="answer-file",
        version=3,
        suite="smoke",
        seed=seed,
        hidden=hidden,
        instruction="Make answer.txt hold 42",
        isolation=False,
        provider="lab",
        model="m",
        max_tokens=4000,
        operator=operator or {"approval": "approve_once"},
        limits={"wall_s": 120, "turn_s": 60},
        pipeline=PIPELINE,
        base_url=model.base_url,
        credential="lab-secret-value-1234",
    )


def _trial(
    tmp_path: Path, implementer: Sequence[Step], operator: Mapping[str, str] | None = None
) -> tuple[TrialSpec, FakeModel, TrialRecord]:
    with _model(implementer) as model:
        spec = _spec(tmp_path, model, operator)
        record = run_trial(spec, tmp_path / "out")
    return spec, model, record


def _lines(tmp_path: Path) -> list[dict[str, object]]:
    text = (tmp_path / "out" / "trials.jsonl").read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines()]


def test_a_done_task_leaves_a_record_with_what_ran(tmp_path: Path) -> None:
    spec, model, record = _trial(
        tmp_path, [write_file("answer.txt", "42\n"), say("answer.txt holds 42.")]
    )

    assert record.status == "done" and record.failure_class is None
    assert (record.task, record.suite, record.model, record.schema) == (
        "answer-file@3",
        "smoke",
        "lab/m",
        1,
    )
    assert record.docket_commit == docket_commit() != "unknown"
    assert set(record.prompt_hashes) == {"lead", "implementer"}
    assert all(
        len(sha) == 64 for layers in record.prompt_hashes.values() for sha in layers.values()
    )
    assert record.verifier["status"] == "pass"
    assert record.tokens["implementer"]["input"] > 0
    assert ["session_end", "lead", "done"] in record.trace_skeleton
    assert (Path(record.transcript_path).parent / "trace.jsonl").is_file()
    assert [m.role for m in model.requests if m.role] == ["lead", "implementer", "implementer"]
    (line,) = _lines(tmp_path)
    assert line["schema"] == 1 and line["verifier"] == record.verifier
    assert not list((tmp_path / "out").glob("trial-*")), "the world is removed after the trial"
    assert spec.hidden.joinpath("test_answer.py").read_text(encoding="utf-8") == CHECK


def test_a_gated_command_parks_and_the_script_resumes_it(tmp_path: Path) -> None:
    _, _, record = _trial(
        tmp_path,
        [
            write_file("build/out.txt", "artifact\n"),
            call("bash", "c2", command="rm -rf build"),
            write_file("answer.txt", "42\n"),
            say("build removed, answer written."),
        ],
    )

    assert record.status == "done" and record.failure_class is None
    assert [(a["kind"], a["answer"]) for a in record.asks] == [("approval", "approve_once")]
    assert ["approval_required", "implementer", ""] in record.trace_skeleton
    assert ["approval_resumed", "lead", ""] in record.trace_skeleton
    assert record.verifier["status"] == "pass"


def test_a_model_writing_into_hidden_changes_nothing_in_the_verdict(tmp_path: Path) -> None:
    real = tmp_path / "hidden" / "test_answer.py"
    easy = "def test_answer():\n    assert True\n"
    spec, _, record = _trial(
        tmp_path,
        [
            write_file("hidden/test_answer.py", easy),
            write_file("conftest.py", "collect_ignore_glob = ['*']\n"),
            call("write", "c3", path=str(real), content=easy),
            say("done."),
        ],
    )

    assert record.status == "done"
    assert record.verifier["status"] == "fail"
    assert spec.hidden.joinpath("test_answer.py").read_text(encoding="utf-8") == CHECK


def test_a_question_the_script_does_not_answer_ends_the_trial_as_harness(tmp_path: Path) -> None:
    _, model, record = _trial(
        tmp_path, [call("consult", "k1", questions=[QUESTION]), say("unreachable")]
    )

    assert record.failure_class == "harness"
    assert record.status == "waiting_input" and "consult" in record.reason
    assert record.asks == []
    assert len(model.by_role("implementer")) == 1


def test_a_reply_cut_at_the_output_cap_is_a_harness_failure(tmp_path: Path) -> None:
    _, _, record = _trial(
        tmp_path, [truncated("cut off"), write_file("answer.txt", "42\n"), say("done.")]
    )

    assert record.failure_class == "harness"


def test_a_planted_key_in_the_model_text_is_absent_from_the_record(tmp_path: Path) -> None:
    _, _, record = _trial(
        tmp_path,
        [write_file("answer.txt", "42\n"), say(f"my key is {KEY} and lab-secret-value-1234")],
    )

    assert record.status == "done"
    for path in (tmp_path / "out").rglob("*"):
        if path.is_file():
            text = path.read_text(encoding="utf-8")
            assert KEY not in text and "lab-secret-value-1234" not in text, path


def test_the_record_writer_scrubs_every_string(tmp_path: Path) -> None:
    record = TrialRecord(
        task="t@1",
        suite="s",
        model="lab/m",
        docket_commit="abc",
        epoch=0,
        prompt_hashes={},
        graders={},
        failure_class=None,
        tokens={},
        wall_s=1.0,
        asks=[{"kind": "consult", "prompt": f"use {KEY}", "answer": "exact-secret-value-99"}],
        denials=0,
        trace_skeleton=[],
        transcript_path="",
        verifier={},
        status="done",
        reason="API_KEY=abcdefghijklmnopqrstuvwxyz0123",
    )
    out = tmp_path / "trials.jsonl"

    append_record(out, record, ("exact-secret-value-99",))

    text = out.read_text(encoding="utf-8")
    assert KEY not in text and "exact-secret-value-99" not in text and "abcdefghij" not in text
    assert json.loads(text)["schema"] == 1


def test_a_cap_under_four_thousand_tokens_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="4000"):
        build_world(
            tmp_path / "w",
            seed=tmp_path,
            provider="lab",
            model="m",
            max_tokens=700,
            isolation=False,
        )


def test_the_seed_is_committed_before_the_pod_exists(tmp_path: Path) -> None:
    with FakeModel() as model:
        seed = tmp_path / "seed"
        seed.mkdir()
        (seed / "answer.txt").write_text("0\n", encoding="utf-8")
        world = build_world(
            tmp_path / "w",
            seed=seed,
            provider="lab",
            model="m",
            max_tokens=4000,
            isolation=False,
            base_url=model.base_url,
            credential="lab-secret-value-1234",
        )
        count = subprocess.run(
            ["git", "-C", str(world.repo), "rev-list", "--count", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            env=world.env,
        ).stdout.strip()

        assert count == "1"
        assert world.sentinel.read_text(encoding="utf-8") == "untouched\n"
        assert "DOCKET_LLM_BASE_URL" not in world.env


class _QueuedWorld(TrialWorld):
    def __init__(self, root: Path, task: dict[str, Any]) -> None:
        super().__init__(root, root, base_url="http://127.0.0.1:9")
        self._queued = task

    def task(self, task_id: str) -> dict[str, Any]:
        return {"task": self._queued}


def test_a_folder_pod_task_is_verified_in_the_seed_repository(tmp_path: Path) -> None:
    # Seen in the first real regression run: a routine pod's task has no worktree, and the trial
    # crashed reading one; such a pod works in the seed repository it was given as workDir.
    folder = _QueuedWorld(tmp_path / "a", {"status": "done", "worktree": None})
    built = _QueuedWorld(tmp_path / "b", {"status": "done", "worktree": {"path": "/w/t"}})

    assert folder.worktree("t") == tmp_path / "a" / "repo"
    assert built.worktree("t") == Path("/w/t")


def test_a_catalog_provider_is_registered_with_its_model() -> None:
    # Seen in the first Haiku run: a catalog provider got no `--model` and `provider add` refused.
    catalog = provider_command("anthropic", "claude-haiku-5-5", ("", ""), (8192, 32768))
    custom = provider_command("lab", "m", ("http://h/v1", "k"), (4000, 32768))

    assert catalog == [
        "setup", "provider", "add", "anthropic", "--model", "claude-haiku-5-5",
        "--max-tokens", "8192", "--no-preset",
    ]  # fmt: skip
    assert custom[:5] == ["setup", "provider", "add", "lab", "http://h/v1"]
    assert custom[custom.index("--model") + 1] == "m" and "--ctx" in custom


def test_the_runners_virtualenv_does_not_reach_the_trial(tmp_path: Path) -> None:
    # Seen in the first Haiku run: with isolation on, `python` resolved to the runner's venv,
    # which the jail cannot read, so every test command failed at interpreter startup.
    venv = tmp_path / "venv"
    (venv / "bin").mkdir(parents=True)
    (venv / "pyvenv.cfg").write_text("home = /usr/bin\n", encoding="utf-8")
    other = tmp_path / "tools"
    other.mkdir()

    assert without_virtualenvs(f"{venv / 'bin'}:{other}:/usr/bin") == f"{other}:/usr/bin"


def test_an_answer_naming_no_option_takes_the_recommendation_with_the_text_as_a_note(
    tmp_path: Path,
) -> None:
    # Seen in the first Haiku capability run: the Lead asked for a code with options
    # `provide-code`/`hold`; the script's code named neither and the trial ended as harness.
    _, model, record = _trial(
        tmp_path,
        [
            call("consult", "k1", questions=[QUESTION]),
            write_file("answer.txt", "42\n"),
            say("done."),
        ],
        {"approval": "approve_once", "consult": "use the ledger value LEDGER-7"},
    )

    assert record.status == "done" and record.failure_class is None
    assert [(a["kind"], a["answer"]) for a in record.asks] == [
        ("consult", "use the ledger value LEDGER-7")
    ]
    resumed = json.dumps(model.by_role("implementer")[1].messages)
    assert "option 42" in resumed and "LEDGER-7" in resumed
