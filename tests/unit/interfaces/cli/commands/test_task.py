"""docket task: show, list, add, trace and the cancel rendering."""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from tests.support.pods import bind_ask_pipeline as _bind_ask_pipeline
from tests.support.pods import seed_pod_isolation_off as _seed_pod
from tests.support.task_unit_harness import (
    _runner,
)
from tests.support.tasks import put_task, put_tasks, task

from docket.governance import approval as _approval
from docket.hops.application import interruptions as _interruptions
from docket.interfaces.cli.app import app
from docket.kernel.home import current_home
from docket.kernel.operator_contract import (
    Escalation,
    Option,
    QuestionV11,
    Recommendation,
    new_escalation_id,
    new_question_id,
)
from docket.platform import read_escalation, write_escalation
from docket.tasks.application import escalations as _escalations
from docket.tasks.application import lifecycle as _lifecycle
from docket.tasks.application.repository import TaskRepository
from docket.tasks.domain.parts import Worktree

SUBJECT = "docket.interfaces.cli.commands.task"


_GATED_PIPELINE_YAML = """\
name: gated
steps:
  - lead: lead
  - implementer: implementer
    approval: true
"""


def _settled_escalation() -> Escalation:
    """An escalation the pod decided alone: stored settled, with no live work behind it."""
    return Escalation(
        id=new_escalation_id(),
        task="task-x",
        pod="demo",
        step="lead",
        role="lead",
        kind="consult",
        caused_by="lead",
        prompt="Which store?",
        asked_at="2026-10-01T00:00:00Z",
        on_expiry="block",
        state="expired",
    )


@contextmanager
def _seed_worktree_task(
    tmp_path: Path,
) -> Iterator[dict[str, Any]]:
    """A pod whose done task carries a recorded worktree directory."""
    with _seed_pod(tmp_path):
        wt = tmp_path / "wt"
        wt.mkdir()
        base = "0123abc"
        record = task(
            status="done",
            worktree=Worktree(dir=str(wt), branch="docket/demo/t1", base_commit=base),
        )
        put_task("demo", record)
        yield {"id": record.id, "wt": wt, "base": base, "record": record}


def _write_trace(task_id: str, *events: tuple[str, dict[str, Any]]) -> None:
    from docket.observability import trace as _trace

    for etype, payload in events:
        _trace.trace_event("demo", f"agent:demo:{task_id}", "lead", etype, json.dumps(payload))


class TestTaskShow:
    def test_prints_the_worktree_path_and_the_exact_diff_command(self, tmp_path: Path) -> None:
        with _seed_worktree_task(tmp_path) as seeded:
            result = _runner.invoke(app, ["task", "show", seeded["id"], "--pod", "demo"])

            assert result.exit_code == 0, result.output
            assert str(seeded["wt"]) in result.output
            assert f"git -C {seeded['wt']} diff {seeded['base']}" in result.output
            assert "merge docket/demo/t1" in result.output

    def test_a_task_without_a_worktree_prints_no_worktree_block(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            record = task(description="plain")
            put_task("demo", record)

            result = _runner.invoke(app, ["task", "show", record.id, "--pod", "demo"])

            assert result.exit_code == 0, result.output
            assert "Worktree" not in result.output

    def test_json_carries_the_worktree(self, tmp_path: Path) -> None:
        with _seed_worktree_task(tmp_path) as seeded:
            result = _runner.invoke(app, ["task", "show", seeded["id"], "--json", "--pod", "demo"])

            body = json.loads(result.output)
            assert body["task"]["worktree"]["path"] == str(seeded["wt"])
            assert body["task"]["worktree"]["baseCommit"] == seeded["base"]

    def test_an_ambiguous_prefix_lists_both_and_exits_one(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            first, second = task(), task()
            put_tasks("demo", first, second)

            result = _runner.invoke(app, ["task", "show", "task-"])

            assert result.exit_code == 1
            assert first.id in result.output
            assert second.id in result.output

    def test_an_unknown_ref_exits_one(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            assert _runner.invoke(app, ["task", "show", "task-nope"]).exit_code == 1


class TestShowRunExitCode:
    def _run_for(self, status: str) -> str:
        from docket.tasks.application import runs as _runs

        record = task()
        put_task("demo", record)

        class _Result:
            task_id = record.id

        _Result.status = status  # type: ignore[attr-defined]
        _Result.reason = "verifyCmd exited 1" if status == "failed" else ""  # type: ignore[attr-defined]
        rec = _runs.create_run("cli", "demo")
        _runs.execute(rec["id"], lambda: [_Result()])
        return str(rec["id"])

    def test_a_failed_run_resolves_to_its_task_and_exits_one(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            run_id = self._run_for("failed")

            result = _runner.invoke(app, ["task", "show", run_id])

            assert result.exit_code == 1
            assert run_id in result.output

    def test_a_succeeded_run_exits_zero(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            assert _runner.invoke(app, ["task", "show", self._run_for("done")]).exit_code == 0


class TestTaskList:
    def test_json_items_carry_the_worktree_path_or_null(self, tmp_path: Path) -> None:
        with _seed_worktree_task(tmp_path) as seeded:
            put_tasks("demo", seeded["record"], task())

            result = _runner.invoke(app, ["task", "list", "--json", "--pod", "demo"])

            items = json.loads(result.output)["tasks"]
            assert [i["worktree"] for i in items] == [str(seeded["wt"]), None]

    def test_the_table_prints_the_short_id(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            record = task(description="visible")
            put_task("demo", record)

            result = _runner.invoke(app, ["task", "list", "--pod", "demo"])

            assert str(record.id)[:18] in result.output
            assert "visible" in result.output

    def test_no_pod_for_the_directory_exits_one(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        with _seed_pod(tmp_path):
            monkeypatch.chdir(tmp_path)
            monkeypatch.delenv("DOCKET_POD", raising=False)
            assert _runner.invoke(app, ["task", "list"]).exit_code == 1


class TestTaskCancelRendering:
    def test_renders_the_outcome_core_returns(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        with _seed_pod(tmp_path):
            record = task(description="work")
            put_task("demo", record)
            seen: dict[str, Any] = {}

            def _cancel(project: str, task_id: str, **kwargs: Any) -> _lifecycle.TaskCancelOutcome:
                seen.update(project=project, task_id=task_id, **kwargs)
                return _lifecycle.TaskCancelOutcome(
                    status="cancelled", parked_from="waiting_input", messages=("run asked",)
                )

            monkeypatch.setattr(_lifecycle, "cancel_task", _cancel)
            result = _runner.invoke(app, ["task", "cancel", record.id, "--pod", "demo"])

            assert result.exit_code == 0, result.output
            assert "run asked" in result.output and "it was waiting_input" in result.output
            assert seen["channel"] == "cli" and seen["task_id"] == record.id

    def test_nothing_in_flight_exits_one(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            record = task(description="work")
            put_task("demo", record)
            result = _runner.invoke(app, ["task", "cancel", record.id, "--pod", "demo"])
            assert result.exit_code == 1
            assert "Nothing is in flight to cancel" in result.output


class TestTaskAdd:
    def test_queues_from_the_pod_in_the_environment(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        with _seed_pod(tmp_path):
            monkeypatch.setenv("DOCKET_POD", "demo")

            result = _runner.invoke(app, ["task", "add", "fix the redirect"])

            assert result.exit_code == 0, result.output
            assert [t.description for t in TaskRepository.for_pod("demo").list()] == [
                "fix the redirect"
            ]

    @pytest.mark.parametrize(
        ("args", "code"),
        [
            (["task", "add", "", "--pod", "demo"], 1),
            (["task", "add", "x", "--priority", "urgent", "--pod", "demo"], 2),
            (["task", "add", "a" * 501, "--pod", "demo"], 1),
        ],
    )
    def test_invalid_input_enqueues_nothing(
        self, tmp_path: Path, args: list[str], code: int
    ) -> None:
        with _seed_pod(tmp_path):
            assert _runner.invoke(app, args).exit_code == code
            assert TaskRepository.for_pod("demo").list() == []

    def test_bracketed_text_prints_literally(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            result = _runner.invoke(
                app, ["task", "add", "Fix [/bold] in [red] mode", "--pod", "demo"]
            )

            task_id = TaskRepository.for_pod("demo").list()[0].id
            assert result.exit_code == 0, result.output
            assert f"[{task_id}] Fix [/bold] in [red] mode" in result.output

    def test_an_invalid_brief_enqueues_nothing(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            brief = tmp_path / "brief.json"
            brief.write_text(json.dumps({"acceptance": ["missing objective"]}))

            result = _runner.invoke(
                app, ["task", "add", "x", "--brief", str(brief), "--pod", "demo"]
            )

            assert result.exit_code == 1
            assert TaskRepository.for_pod("demo").list() == []

    def test_a_valid_brief_is_stored_on_the_task(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            brief = tmp_path / "brief.json"
            brief.write_text(json.dumps({"objective": "fix the flaky test"}))

            result = _runner.invoke(
                app, ["task", "add", "x", "--brief", str(brief), "--pod", "demo"]
            )

            assert result.exit_code == 0, result.output
            stored = TaskRepository.for_pod("demo").list()[0]
            assert stored.brief is not None
            assert stored.brief.objective == "fix the flaky test"

    def test_a_clean_pod_says_nothing_will_ask(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            result = _runner.invoke(app, ["task", "add", "x", "--pod", "demo"])

            assert _interruptions.NOTHING_WILL_ASK in result.output

    def test_a_pipeline_gate_is_named_in_the_summary(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            _bind_ask_pipeline("demo", _GATED_PIPELINE_YAML)

            result = _runner.invoke(app, ["task", "add", "x", "--pod", "demo"])

            assert "May ask you:" in result.output
            assert "docket task show" in result.output

    def test_counts_are_pluralised(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            policies_dir = current_home().pod_config_dir("demo") / "policies"
            policies_dir.mkdir(parents=True)
            for name in ("a", "b"):
                (policies_dir / f"{name}.yaml").write_text(
                    f"kind: policy\nname: {name}\nappliesTo: [implementer]\n"
                    "when:\n  tool: bash\nthen: ask\n"
                )
            _bind_ask_pipeline("demo", _GATED_PIPELINE_YAML)

            result = _runner.invoke(app, ["task", "add", "x", "--pod", "demo"])

            assert "May ask you: 1 pipeline gate, 2 policies -- see" in result.output

    def test_the_six_addressing_flags_are_stored_on_the_task(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            result = _runner.invoke(
                app,
                [
                    *("task", "add", "x", "--pod", "demo"),
                    *("--external-ref", "TACK-1", "--idempotency-key", "k-1"),
                    *("--base-ref", "main", "--pipeline", "tdd"),
                    *("--gate", "make test", "--max-tokens", "5000"),
                ],
            )

            stored = TaskRepository.for_pod("demo").list()[0]
            assert result.exit_code == 0, result.output
            assert stored.external_ref == "TACK-1"
            assert stored.idempotency_key == "k-1"
            assert stored.base_ref == "main"
            assert stored.pipeline == "tdd"
            assert stored.gate is not None and stored.gate.command == "make test"
            assert stored.max_tokens == 5000

    def test_a_repeated_idempotency_key_says_already_queued(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            args = ["task", "add", "x", "--idempotency-key", "k-1", "--pod", "demo"]

            first = _runner.invoke(app, args)
            second = _runner.invoke(app, args)

            tasks = TaskRepository.for_pod("demo").list()
            assert (first.exit_code, second.exit_code) == (0, 0)
            assert len(tasks) == 1
            assert "already queued" in second.output
            assert tasks[0].id in second.output

    @pytest.mark.parametrize(
        "flags",
        [["--gate", " "], ["--max-tokens", "0"], ["--external-ref", "x" * 201]],
    )
    def test_an_invalid_addressing_flag_enqueues_nothing(
        self, tmp_path: Path, flags: list[str]
    ) -> None:
        with _seed_pod(tmp_path):
            result = _runner.invoke(app, ["task", "add", "x", "--pod", "demo", *flags])

            assert result.exit_code == 1
            assert TaskRepository.for_pod("demo").list() == []


class TestTaskTrace:
    def test_prints_the_tool_name_on_tool_call_lines(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            record = task(description="x")
            put_task("demo", record)
            _write_trace(record.id, ("tool_call", {"tool": "grep", "callId": "c1"}))

            result = _runner.invoke(app, ["task", "trace", record.id, "--pod", "demo"])

            assert result.exit_code == 0, result.output
            assert "tool=grep" in result.output

    def test_model_text_with_markup_tags_prints_literally(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            record = task(description="x")
            put_task("demo", record)
            text = "ok [/bold] then [red]x[/red] for [task-1]"
            _write_trace(record.id, ("tool_result", {"text": text}))

            result = _runner.invoke(app, ["task", "trace", record.id, "--pod", "demo"])

            assert f"text={text}" in result.output

    def test_tail_returns_once_the_session_has_ended(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            record = task(description="x")
            put_task("demo", record)
            _write_trace(record.id, ("session_start", {}), ("session_end", {"status": "done"}))

            result = _runner.invoke(app, ["task", "trace", record.id, "--tail", "--pod", "demo"])

            assert result.exit_code == 0, result.output
            assert "session_end" in result.output

    def test_export_is_the_raw_jsonl(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            record = task(description="x")
            put_task("demo", record)
            _write_trace(record.id, ("session_start", {}))

            result = _runner.invoke(app, ["task", "trace", record.id, "--export", "--pod", "demo"])

            assert json.loads(result.output.splitlines()[0])["event_type"] == "session_start"

    def test_json_lists_the_events(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            record = task(description="x")
            put_task("demo", record)
            _write_trace(record.id, ("session_start", {}))

            result = _runner.invoke(app, ["task", "trace", record.id, "--json", "--pod", "demo"])

            assert json.loads(result.output)["events"][0]["event_type"] == "session_start"

    def test_a_task_that_never_ran_has_no_trace(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            record = task(description="x")
            put_task("demo", record)
            assert _runner.invoke(app, ["task", "trace", record.id, "--pod", "demo"]).exit_code == 1


class TestGroup:
    def test_an_unknown_verb_is_a_usage_error(self) -> None:
        assert _runner.invoke(app, ["task", "nonesuch"]).exit_code == 2


class TestTaskDiff:
    def test_a_task_that_ran_in_place_has_nothing_to_diff(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            record = task(description="plain")
            put_task("demo", record)
            assert _runner.invoke(app, ["task", "diff", record.id, "--pod", "demo"]).exit_code == 1


class TestTaskDiffJson:
    def test_json_prints_the_whole_object(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        with _seed_pod(tmp_path):
            record = task(description="work")
            put_task("demo", record)
            doc = {"task": record.id, "patch": "diff --git a/x b/x\n", "worktreePresent": False}
            monkeypatch.setattr(_lifecycle, "task_diff", lambda project, task_id: doc)

            shown = _runner.invoke(app, ["task", "diff", record.id, "--pod", "demo", "--json"])
            plain = _runner.invoke(app, ["task", "diff", record.id, "--pod", "demo"])

            assert json.loads(shown.output) == doc
            assert plain.output == doc["patch"]


@pytest.mark.parametrize(
    ("verb", "example"),
    [
        ("pregrant", "docket task pregrant task-04ff"),
        ("answer", "docket task answer esc-1a2b3c4d5e6f --option approve_once"),
        ("retry", "docket task retry task-04ff"),
        ("cancel", "docket task cancel task-04ff"),
    ],
)
def test_task_verb_help_example_uses_a_record_id(verb: str, example: str) -> None:
    """The Example line of each task verb passes a task or escalation id, not a timestamp."""
    result = _runner.invoke(app, ["task", verb, "--help"])

    flat = " ".join(result.output.replace("\u2502", " ").split())
    assert example in flat
    assert "2026-10-08T10-00" not in flat


@pytest.mark.parametrize("verb", ["approve", "deny"])
def test_the_retired_task_verbs_are_ordinary_unknown_commands(verb: str) -> None:
    result = _runner.invoke(app, ["task", verb, "task-04ff"])

    assert result.exit_code == 2
    assert f"No such command '{verb}'" in result.output


class TestShowForecast:
    def test_a_pipeline_gate_is_listed_with_the_park_posture(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            _bind_ask_pipeline("demo", _GATED_PIPELINE_YAML)
            record = task(description="x")
            put_task("demo", record)

            result = _runner.invoke(app, ["task", "show", record.id, "--pod", "demo"])

            assert "step 'implementer' has an approval gate" in result.output
            assert "approvalMode resolves to" in result.output

    def test_json_lists_the_interruption_kinds(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            _bind_ask_pipeline("demo", _GATED_PIPELINE_YAML)
            record = task(description="x")
            put_task("demo", record)

            result = _runner.invoke(app, ["task", "show", record.id, "--json", "--pod", "demo"])

            kinds = {i["kind"] for i in json.loads(result.output)["interruptions"]}
            assert {"pipeline_gate", "mode"} <= kinds


class TestShowDecidedWithoutYou:
    def _decide(self) -> str:
        question = QuestionV11(
            id=new_question_id(),
            task_id="task-d",
            pod="demo",
            step="implementer",
            message="Which store should the cache use?",
            requested_schema={"type": "object", "properties": {"note": {"type": "string"}}},
            created_at="2026-10-25T00:00:00+00:00",
            kind="decision",
            options=[
                Option(id="redis", label="Redis", description="fast"),
                Option(id="sqlite", label="SQLite", description="simple"),
            ],
            recommendation=Recommendation(option_id="sqlite", rationale="fewer services"),
        )
        put_task("demo", task(id="task-d", status="done"))
        _escalations.decided_consult(question, role="implementer", option_id="sqlite")
        return "task-d"

    def test_each_decision_is_printed_with_its_option_and_who_took_it(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            task_id = self._decide()

            result = _runner.invoke(app, ["task", "show", task_id, "--pod", "demo"])

            assert result.exit_code == 0, result.output
            assert "Decided without you" in result.output
            assert "consultation" in result.output and "sqlite" in result.output
            assert "recommendation" in result.output
            assert "Waiting on you" not in result.output

    def test_json_lists_the_decisions_apart_from_the_waiting_ones(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            task_id = self._decide()

            body = json.loads(
                _runner.invoke(app, ["task", "show", task_id, "--json", "--pod", "demo"]).output
            )

            assert body["escalations"] == []
            (decided,) = body["decided"]
            assert (decided["state"], decided["resolution"]["optionId"]) == ("decided", "sqlite")

    def test_a_task_that_decided_nothing_adds_no_key(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            record = task(description="x")
            put_task("demo", record)

            body = json.loads(
                _runner.invoke(app, ["task", "show", record.id, "--json", "--pod", "demo"]).output
            )

            assert "decided" not in body


class TestShowWaitingOnYou:
    def _park(self) -> str:
        question = QuestionV11(
            id=new_question_id(),
            task_id="task-q",
            pod="demo",
            step="implementer",
            message="Which store should the cache use?",
            requested_schema={"type": "object", "properties": {"note": {"type": "string"}}},
            created_at="2026-10-25T00:00:00+00:00",
            kind="decision",
            options=[
                Option(id="redis", label="Redis", description="fast"),
                Option(id="sqlite", label="SQLite", description="simple"),
            ],
            recommendation=Recommendation(option_id="sqlite", rationale="fewer services"),
        )
        put_task("demo", task(id="task-q", status="waiting_input", question=question))
        _escalations.open_for_question(question, kind="consult", role="implementer", caused_by="c1")
        return "task-q"

    def test_a_parked_question_prints_its_prompt_option_ids_and_the_answer_command(
        self, tmp_path: Path
    ) -> None:
        with _seed_pod(tmp_path):
            task_id = self._park()

            result = _runner.invoke(app, ["task", "show", task_id, "--pod", "demo"])

            assert result.exit_code == 0, result.output
            assert "Waiting on you" in result.output
            assert "Which store should the cache use?" in result.output
            assert (
                "redis (Redis)" in result.output
                and "sqlite (SQLite) (recommended)" in result.output
            )
            assert "docket task answer task-q --option sqlite" in result.output

    def test_a_held_approval_prints_the_action_and_both_decisions(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            token = _approval.approval_create("demo", "implementer", "bash: rm -rf build")
            put_task("demo", task(id="task-a", status="waiting_approval"))
            escalation = _escalations.open_for_approval(
                token, kind="approval", task_id="task-a", caused_by="c1"
            )

            result = _runner.invoke(app, ["task", "show", "task-a", "--pod", "demo"])

            assert "Waiting on you" in result.output
            assert "rm -rf build" in result.output
            assert f"docket task answer {escalation.id} --option approve_once" in result.output
            assert f"docket task answer {escalation.id} --option deny" in result.output

    def test_a_task_that_waits_on_nobody_prints_no_section(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            put_task("demo", task(id="task-n", description="plain"))

            result = _runner.invoke(app, ["task", "show", "task-n", "--pod", "demo"])

            assert "Waiting on you" not in result.output

    def test_json_lists_the_pending_escalations(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            task_id = self._park()

            body = json.loads(
                _runner.invoke(app, ["task", "show", task_id, "--json", "--pod", "demo"]).output
            )

            assert [e["kind"] for e in body["escalations"]] == ["consult"]
            assert body["escalations"][0]["affordances"]["options"] == [
                "redis",
                "sqlite",
                "decline",
            ]


class TestTaskPrune:
    def test_days_without_traces_is_a_usage_error(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            assert (
                _runner.invoke(app, ["task", "prune", "--days", "3", "--pod", "demo"]).exit_code
                == 2
            )

    def test_traces_reports_both_stores(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            result = _runner.invoke(
                app, ["task", "prune", "--traces", "--days", "0", "--dry-run", "--pod", "demo"]
            )

            assert result.exit_code == 0, result.output
            assert "trace file" in result.output
            assert "run record" in result.output

    def test_traces_also_prunes_the_settled_escalations(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            old = write_escalation(_settled_escalation())
            settled_file = current_home().escalations_dir / "settled" / f"{old.id}.json"
            os.utime(settled_file, (0, 0))

            dry = _runner.invoke(
                app, ["task", "prune", "--traces", "--days", "0", "--dry-run", "--pod", "demo"]
            )
            assert dry.exit_code == 0, dry.output
            assert "Would remove 1 settled escalation record(s)" in dry.output
            assert settled_file.exists()

            result = _runner.invoke(
                app, ["task", "prune", "--traces", "--days", "0", "--pod", "demo"]
            )
            assert result.exit_code == 0, result.output
            assert "Removed 1 settled escalation record(s)" in result.output
            assert not settled_file.exists()
            assert read_escalation(old.id) is None
