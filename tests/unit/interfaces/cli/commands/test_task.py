"""docket task: show, list, add, trace and the cancel rendering."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from tests.support.pods import bind_ask_pipeline as _bind_ask_pipeline
from tests.support.pods import seed_pod_4 as _seed_pod
from tests.support.task_unit_harness import (
    _runner,
)

from docket.hops.application import interruptions as _interruptions
from docket.interfaces.cli.app import app
from docket.kernel.home import current_home
from docket.tasks.application import lifecycle as _lifecycle
from docket.tasks.application import queue as _queue
from docket.teams import settings as _settings

SUBJECT = "docket.interfaces.cli.commands.task"


_GATED_PIPELINE_YAML = """\
name: gated
steps:
  - lead: lead
  - implementer: implementer
    approval: true
"""


@contextmanager
def _seed_worktree_task(
    tmp_path: Path,
) -> Iterator[dict[str, Any]]:
    """A pod whose done task carries a recorded worktree directory."""
    with _seed_pod(tmp_path):
        wt = tmp_path / "wt"
        wt.mkdir()
        base = "0123abc"
        task = _queue.enqueue_task_once("demo", "bump x", channel="cli")[0]
        path = _settings.pod_task_list_path("demo")
        from docket.platform import store as _store

        doc = _store.read_json(path)
        for t in doc["tasks"]:
            t["status"] = "done"
            t["worktree"] = {"dir": str(wt), "branch": "docket/demo/t1", "baseCommit": base}
        _store.write_json(path, doc)
        yield {"id": task["id"], "wt": wt, "base": base}


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
            task = _queue.enqueue_task_once("demo", "plain", channel="cli")[0]

            result = _runner.invoke(app, ["task", "show", task["id"], "--pod", "demo"])

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
            first = _queue.enqueue_task_once("demo", "one", channel="cli")[0]
            second = _queue.enqueue_task_once("demo", "two", channel="cli")[0]

            result = _runner.invoke(app, ["task", "show", "task-"])

            assert result.exit_code == 1
            assert str(first["id"]) in result.output
            assert str(second["id"]) in result.output

    def test_an_unknown_ref_exits_one(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            assert _runner.invoke(app, ["task", "show", "task-nope"]).exit_code == 1


class TestShowRunExitCode:
    def _run_for(self, status: str) -> str:
        from docket.tasks.application import runs as _runs

        task = _queue.enqueue_task_once("demo", "x", channel="cli")[0]

        class _Result:
            task_id = task["id"]

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
            _queue.enqueue_task_once("demo", "second", channel="cli")

            result = _runner.invoke(app, ["task", "list", "--json", "--pod", "demo"])

            items = json.loads(result.output)["tasks"]
            assert [i["worktree"] for i in items] == [str(seeded["wt"]), None]

    def test_the_table_prints_the_short_id(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            task = _queue.enqueue_task_once("demo", "visible", channel="cli")[0]

            result = _runner.invoke(app, ["task", "list", "--pod", "demo"])

            assert str(task["id"])[:18] in result.output
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
            task = _queue.enqueue_task_once("demo", "work", channel="cli")[0]
            seen: dict[str, Any] = {}

            def _cancel(project: str, task_id: str, **kwargs: Any) -> _lifecycle.TaskCancelOutcome:
                seen.update(project=project, task_id=task_id, **kwargs)
                return _lifecycle.TaskCancelOutcome(
                    status="cancelled", parked_from="waiting_input", messages=("run asked",)
                )

            monkeypatch.setattr(_lifecycle, "cancel_task", _cancel)
            result = _runner.invoke(app, ["task", "cancel", task["id"], "--pod", "demo"])

            assert result.exit_code == 0, result.output
            assert "run asked" in result.output and "it was waiting_input" in result.output
            assert seen["channel"] == "cli" and seen["task_id"] == task["id"]

    def test_nothing_in_flight_exits_one(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            task = _queue.enqueue_task_once("demo", "work", channel="cli")[0]
            result = _runner.invoke(app, ["task", "cancel", task["id"], "--pod", "demo"])
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
            assert [t["description"] for t in _queue.read_tasks("demo")] == ["fix the redirect"]

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
            assert _queue.read_tasks("demo") == []

    def test_bracketed_text_prints_literally(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            result = _runner.invoke(
                app, ["task", "add", "Fix [/bold] in [red] mode", "--pod", "demo"]
            )

            task_id = _queue.read_tasks("demo")[0]["id"]
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
            assert _queue.read_tasks("demo") == []

    def test_a_valid_brief_is_stored_on_the_task(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            brief = tmp_path / "brief.json"
            brief.write_text(json.dumps({"objective": "fix the flaky test"}))

            result = _runner.invoke(
                app, ["task", "add", "x", "--brief", str(brief), "--pod", "demo"]
            )

            assert result.exit_code == 0, result.output
            assert _queue.read_tasks("demo")[0]["brief"]["objective"] == "fix the flaky test"

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

            task = _queue.read_tasks("demo")[0]
            assert result.exit_code == 0, result.output
            assert task["externalRef"] == "TACK-1"
            assert task["idempotencyKey"] == "k-1"
            assert task["baseRef"] == "main"
            assert task["pipeline"] == "tdd"
            assert task["gate"] == {"command": "make test"}
            assert task["maxTokens"] == 5000

    def test_a_repeated_idempotency_key_says_already_queued(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            args = ["task", "add", "x", "--idempotency-key", "k-1", "--pod", "demo"]

            first = _runner.invoke(app, args)
            second = _runner.invoke(app, args)

            tasks = _queue.read_tasks("demo")
            assert (first.exit_code, second.exit_code) == (0, 0)
            assert len(tasks) == 1
            assert "already queued" in second.output
            assert tasks[0]["id"] in second.output

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
            assert _queue.read_tasks("demo") == []


class TestTaskTrace:
    def test_prints_the_tool_name_on_tool_call_lines(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            task = _queue.enqueue_task_once("demo", "x", channel="cli")[0]
            _write_trace(task["id"], ("tool_call", {"tool": "grep", "callId": "c1"}))

            result = _runner.invoke(app, ["task", "trace", task["id"], "--pod", "demo"])

            assert result.exit_code == 0, result.output
            assert "tool=grep" in result.output

    def test_model_text_with_markup_tags_prints_literally(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            task = _queue.enqueue_task_once("demo", "x", channel="cli")[0]
            text = "ok [/bold] then [red]x[/red] for [task-1]"
            _write_trace(task["id"], ("tool_result", {"text": text}))

            result = _runner.invoke(app, ["task", "trace", task["id"], "--pod", "demo"])

            assert f"text={text}" in result.output

    def test_tail_returns_once_the_session_has_ended(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            task = _queue.enqueue_task_once("demo", "x", channel="cli")[0]
            _write_trace(task["id"], ("session_start", {}), ("session_end", {"status": "done"}))

            result = _runner.invoke(app, ["task", "trace", task["id"], "--tail", "--pod", "demo"])

            assert result.exit_code == 0, result.output
            assert "session_end" in result.output

    def test_export_is_the_raw_jsonl(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            task = _queue.enqueue_task_once("demo", "x", channel="cli")[0]
            _write_trace(task["id"], ("session_start", {}))

            result = _runner.invoke(app, ["task", "trace", task["id"], "--export", "--pod", "demo"])

            assert json.loads(result.output.splitlines()[0])["event_type"] == "session_start"

    def test_json_lists_the_events(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            task = _queue.enqueue_task_once("demo", "x", channel="cli")[0]
            _write_trace(task["id"], ("session_start", {}))

            result = _runner.invoke(app, ["task", "trace", task["id"], "--json", "--pod", "demo"])

            assert json.loads(result.output)["events"][0]["event_type"] == "session_start"

    def test_a_task_that_never_ran_has_no_trace(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            task = _queue.enqueue_task_once("demo", "x", channel="cli")[0]
            assert (
                _runner.invoke(app, ["task", "trace", task["id"], "--pod", "demo"]).exit_code == 1
            )


class TestGroup:
    def test_an_unknown_verb_is_a_usage_error(self) -> None:
        assert _runner.invoke(app, ["task", "nonesuch"]).exit_code == 2


class TestTaskDiff:
    def test_a_task_that_ran_in_place_has_nothing_to_diff(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            task = _queue.enqueue_task_once("demo", "plain", channel="cli")[0]
            assert _runner.invoke(app, ["task", "diff", task["id"], "--pod", "demo"]).exit_code == 1


class TestTaskDiffJson:
    def test_json_prints_the_whole_object(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        with _seed_pod(tmp_path):
            task = _queue.enqueue_task_once("demo", "work", channel="cli")[0]
            doc = {"task": task["id"], "patch": "diff --git a/x b/x\n", "worktreePresent": False}
            monkeypatch.setattr(_lifecycle, "task_diff", lambda project, task_id: doc)

            shown = _runner.invoke(app, ["task", "diff", task["id"], "--pod", "demo", "--json"])
            plain = _runner.invoke(app, ["task", "diff", task["id"], "--pod", "demo"])

            assert json.loads(shown.output) == doc
            assert plain.output == doc["patch"]


@pytest.mark.parametrize("verb", ["approve", "deny", "answer", "retry", "cancel"])
def test_task_verb_help_example_uses_a_task_id(verb: str) -> None:
    """The Example line of each task verb passes a task id, not a timestamp."""
    result = _runner.invoke(app, ["task", verb, "--help"])

    flat = " ".join(result.output.replace("\u2502", " ").split())
    assert f"docket task {verb} task-04ff" in flat
    assert "2026-10-08T10-00" not in flat


class TestShowForecast:
    def test_a_pipeline_gate_is_listed_with_the_park_posture(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            _bind_ask_pipeline("demo", _GATED_PIPELINE_YAML)
            task = _queue.enqueue_task_once("demo", "x", channel="cli")[0]

            result = _runner.invoke(app, ["task", "show", task["id"], "--pod", "demo"])

            assert "step 'implementer' has an approval gate" in result.output
            assert "approvalMode resolves to" in result.output

    def test_json_lists_the_interruption_kinds(self, tmp_path: Path) -> None:
        with _seed_pod(tmp_path):
            _bind_ask_pipeline("demo", _GATED_PIPELINE_YAML)
            task = _queue.enqueue_task_once("demo", "x", channel="cli")[0]

            result = _runner.invoke(app, ["task", "show", task["id"], "--json", "--pod", "demo"])

            kinds = {i["kind"] for i in json.loads(result.output)["interruptions"]}
            assert {"pipeline_gate", "mode"} <= kinds


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
