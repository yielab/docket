"""`docket task`: queue, inspect and answer a pod's tasks through one group."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from tests.conftest import record_isolation_off, repoint_docket_home
from tests.fakes import FakeDriver
from typer.testing import CliRunner

from docket.cli import _pod, app
from docket.core import dispatch as _dispatch
from docket.core import fleet as _fleet
from docket.core import interruptions as _interruptions

SUBJECT = "docket.cli._task"

_runner = CliRunner()

_ASK_PIPELINE_YAML = """\
name: ask
steps:
  - id: lead
    role: lead
  - id: ask
    input:
      from: lead
  - id: implementer
    role: implementer
"""


def _seed_pod(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, project: str = "demo") -> Path:
    home = tmp_path / ".docket"
    (home / "workspaces" / "projects").mkdir(parents=True)
    (home / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    repoint_docket_home(monkeypatch, home)
    record_isolation_off(home)
    _pod.build_pod(project, _pod.pod.DEFAULT_POD_ROLES, codebase=f"/src/{project}")
    return home


def _bind_ask_pipeline(project: str) -> None:
    digest = hashlib.sha256(_ASK_PIPELINE_YAML.encode("utf-8")).hexdigest()
    path = _pod.pod.bound_pipeline_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_ASK_PIPELINE_YAML, encoding="utf-8")
    _fleet.meta_set(_pod.pod.member_id(project, "lead"), "pipeline", digest)


def _seed_parked_task(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """A real pod with a real ``waiting_input`` task, reached by dispatching through an
    ``input`` step."""
    _seed_pod(tmp_path, monkeypatch)
    _bind_ask_pipeline("demo")
    _dispatch.enqueue_task("demo", "needs a decision")
    _dispatch.dispatch_pod("demo", runner=FakeDriver())
    return _dispatch.read_tasks("demo")[0]


def _give_options(project: str, task_id: str) -> None:
    """Turn the parked task's question into one with options, as a Lead consult writes."""
    from docket.edges import store as _store

    path = _dispatch.pod_task_list_path(project)
    doc = _store.read_json(path)
    for task in doc["tasks"]:
        if task["id"] == task_id:
            task["question"].update(
                {
                    "kind": "clarification",
                    "options": [
                        {"id": "opt1", "label": "Root", "description": "At the root."},
                        {"id": "opt2", "label": "Search", "description": "Search for it."},
                    ],
                    "recommendation": {"optionId": "opt2", "rationale": "safer"},
                }
            )
    _store.write_json(path, doc)


class TestGroup:
    def test_an_unknown_verb_is_a_usage_error(self) -> None:
        assert _runner.invoke(app, ["task", "nonesuch"]).exit_code == 2


def _seed_worktree_task(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """A pod whose done task carries a recorded worktree directory."""
    _seed_pod(tmp_path, monkeypatch)
    wt = tmp_path / "wt"
    wt.mkdir()
    base = "0123abc"
    task = _dispatch.enqueue_task("demo", "bump x")
    path = _dispatch.pod_task_list_path("demo")
    from docket.edges import store as _store

    doc = _store.read_json(path)
    for t in doc["tasks"]:
        t["status"] = "done"
        t["worktree"] = {"dir": str(wt), "branch": "docket/demo/t1", "baseCommit": base}
    _store.write_json(path, doc)
    return {"id": task["id"], "wt": wt, "base": base}


class TestTaskShow:
    def test_prints_the_worktree_path_and_the_exact_diff_command(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seeded = _seed_worktree_task(tmp_path, monkeypatch)

        result = _runner.invoke(app, ["task", "show", seeded["id"], "--pod", "demo"])

        assert result.exit_code == 0, result.output
        assert str(seeded["wt"]) in result.output
        assert f"git -C {seeded['wt']} diff {seeded['base']}" in result.output
        assert "merge docket/demo/t1" in result.output

    def test_a_task_without_a_worktree_prints_no_worktree_block(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)
        task = _dispatch.enqueue_task("demo", "plain")

        result = _runner.invoke(app, ["task", "show", task["id"], "--pod", "demo"])

        assert result.exit_code == 0, result.output
        assert "Worktree" not in result.output

    def test_json_carries_the_worktree(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seeded = _seed_worktree_task(tmp_path, monkeypatch)

        result = _runner.invoke(app, ["task", "show", seeded["id"], "--json", "--pod", "demo"])

        body = json.loads(result.output)
        assert body["task"]["worktree"]["path"] == str(seeded["wt"])
        assert body["task"]["worktree"]["baseCommit"] == seeded["base"]

    def test_an_ambiguous_prefix_lists_both_and_exits_one(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)
        first = _dispatch.enqueue_task("demo", "one")
        second = _dispatch.enqueue_task("demo", "two")

        result = _runner.invoke(app, ["task", "show", "task-"])

        assert result.exit_code == 1
        assert str(first["id"]) in result.output
        assert str(second["id"]) in result.output

    def test_an_unknown_ref_exits_one(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)
        assert _runner.invoke(app, ["task", "show", "task-nope"]).exit_code == 1


class TestShowRunExitCode:
    def _run_for(self, status: str) -> str:
        from docket.core import runs as _runs

        task = _dispatch.enqueue_task("demo", "x")

        class _Result:
            task_id = task["id"]

        _Result.status = status  # type: ignore[attr-defined]
        _Result.reason = "verifyCmd exited 1" if status == "failed" else ""  # type: ignore[attr-defined]
        rec = _runs.create_run("cli", "demo")
        _runs.execute(rec["id"], lambda: [_Result()])
        return str(rec["id"])

    def test_a_failed_run_resolves_to_its_task_and_exits_one(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)
        run_id = self._run_for("failed")

        result = _runner.invoke(app, ["task", "show", run_id])

        assert result.exit_code == 1
        assert run_id in result.output

    def test_a_succeeded_run_exits_zero(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)
        assert _runner.invoke(app, ["task", "show", self._run_for("done")]).exit_code == 0


class TestTaskList:
    def test_json_items_carry_the_worktree_path_or_null(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seeded = _seed_worktree_task(tmp_path, monkeypatch)
        _dispatch.enqueue_task("demo", "second")

        result = _runner.invoke(app, ["task", "list", "--json", "--pod", "demo"])

        items = json.loads(result.output)["tasks"]
        assert [i["worktree"] for i in items] == [str(seeded["wt"]), None]

    def test_the_table_prints_the_short_id(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)
        task = _dispatch.enqueue_task("demo", "visible")

        result = _runner.invoke(app, ["task", "list", "--pod", "demo"])

        assert str(task["id"])[:18] in result.output
        assert "visible" in result.output

    def test_no_pod_for_the_directory_exits_one(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("DOCKET_POD", raising=False)
        assert _runner.invoke(app, ["task", "list"]).exit_code == 1


class TestTaskDiff:
    def test_a_task_that_ran_in_place_has_nothing_to_diff(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)
        task = _dispatch.enqueue_task("demo", "plain")
        assert _runner.invoke(app, ["task", "diff", task["id"], "--pod", "demo"]).exit_code == 1


class TestTaskAdd:
    def test_queues_from_the_pod_in_the_environment(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)
        monkeypatch.setenv("DOCKET_POD", "demo")

        result = _runner.invoke(app, ["task", "add", "fix the redirect"])

        assert result.exit_code == 0, result.output
        assert [t["description"] for t in _dispatch.read_tasks("demo")] == ["fix the redirect"]

    @pytest.mark.parametrize(
        ("args", "code"),
        [
            (["task", "add", "", "--pod", "demo"], 1),
            (["task", "add", "x", "--priority", "urgent", "--pod", "demo"], 2),
            (["task", "add", "a" * 501, "--pod", "demo"], 1),
        ],
    )
    def test_invalid_input_enqueues_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, args: list[str], code: int
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)

        assert _runner.invoke(app, args).exit_code == code
        assert _dispatch.read_tasks("demo") == []

    def test_bracketed_text_prints_literally(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)

        result = _runner.invoke(app, ["task", "add", "Fix [/bold] in [red] mode", "--pod", "demo"])

        task_id = _dispatch.read_tasks("demo")[0]["id"]
        assert result.exit_code == 0, result.output
        assert f"[{task_id}] Fix [/bold] in [red] mode" in result.output

    def test_an_invalid_brief_enqueues_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)
        brief = tmp_path / "brief.json"
        brief.write_text(json.dumps({"acceptance": ["missing objective"]}))

        result = _runner.invoke(app, ["task", "add", "x", "--brief", str(brief), "--pod", "demo"])

        assert result.exit_code == 1
        assert _dispatch.read_tasks("demo") == []

    def test_a_valid_brief_is_stored_on_the_task(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)
        brief = tmp_path / "brief.json"
        brief.write_text(json.dumps({"objective": "fix the flaky test"}))

        result = _runner.invoke(app, ["task", "add", "x", "--brief", str(brief), "--pod", "demo"])

        assert result.exit_code == 0, result.output
        assert _dispatch.read_tasks("demo")[0]["brief"]["objective"] == "fix the flaky test"

    def test_a_clean_pod_says_nothing_will_ask(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)

        result = _runner.invoke(app, ["task", "add", "x", "--pod", "demo"])

        assert _interruptions.NOTHING_WILL_ASK in result.output

    def test_a_role_gate_is_named_in_the_summary(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)
        _fleet.meta_set("demo-lead", "requireApprovalRoles", "implementer")

        result = _runner.invoke(app, ["task", "add", "x", "--pod", "demo"])

        assert "May ask you:" in result.output
        assert "docket task show" in result.output


class TestShowForecast:
    def test_a_role_gate_is_listed_with_the_park_posture(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)
        _fleet.meta_set("demo-lead", "requireApprovalRoles", "implementer")
        task = _dispatch.enqueue_task("demo", "x")

        result = _runner.invoke(app, ["task", "show", task["id"], "--pod", "demo"])

        assert "requireApprovalRoles" in result.output
        assert "approvalMode resolves to" in result.output

    def test_json_lists_the_interruption_kinds(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)
        _fleet.meta_set("demo-lead", "requireApprovalRoles", "implementer")
        task = _dispatch.enqueue_task("demo", "x")

        result = _runner.invoke(app, ["task", "show", task["id"], "--json", "--pod", "demo"])

        kinds = {i["kind"] for i in json.loads(result.output)["interruptions"]}
        assert {"role_gate", "mode"} <= kinds


def _write_trace(task_id: str, *events: tuple[str, dict[str, Any]]) -> None:
    from docket.core import trace as _trace

    for etype, payload in events:
        _trace.trace_event("demo", f"agent:demo:{task_id}", "lead", etype, json.dumps(payload))


class TestTaskTrace:
    def test_prints_the_tool_name_on_tool_call_lines(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)
        task = _dispatch.enqueue_task("demo", "x")
        _write_trace(task["id"], ("tool_call", {"tool": "grep", "callId": "c1"}))

        result = _runner.invoke(app, ["task", "trace", task["id"], "--pod", "demo"])

        assert result.exit_code == 0, result.output
        assert "tool=grep" in result.output

    def test_model_text_with_markup_tags_prints_literally(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)
        task = _dispatch.enqueue_task("demo", "x")
        text = "ok [/bold] then [red]x[/red] for [task-1]"
        _write_trace(task["id"], ("tool_result", {"text": text}))

        result = _runner.invoke(app, ["task", "trace", task["id"], "--pod", "demo"])

        assert f"text={text}" in result.output

    def test_tail_returns_once_the_session_has_ended(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)
        task = _dispatch.enqueue_task("demo", "x")
        _write_trace(task["id"], ("session_start", {}), ("session_end", {"status": "done"}))

        result = _runner.invoke(app, ["task", "trace", task["id"], "--tail", "--pod", "demo"])

        assert result.exit_code == 0, result.output
        assert "session_end" in result.output

    def test_export_is_the_raw_jsonl(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _seed_pod(tmp_path, monkeypatch)
        task = _dispatch.enqueue_task("demo", "x")
        _write_trace(task["id"], ("session_start", {}))

        result = _runner.invoke(app, ["task", "trace", task["id"], "--export", "--pod", "demo"])

        assert json.loads(result.output.splitlines()[0])["event_type"] == "session_start"

    def test_json_lists_the_events(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _seed_pod(tmp_path, monkeypatch)
        task = _dispatch.enqueue_task("demo", "x")
        _write_trace(task["id"], ("session_start", {}))

        result = _runner.invoke(app, ["task", "trace", task["id"], "--json", "--pod", "demo"])

        assert json.loads(result.output)["events"][0]["event_type"] == "session_start"

    def test_a_task_that_never_ran_has_no_trace(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)
        task = _dispatch.enqueue_task("demo", "x")
        assert _runner.invoke(app, ["task", "trace", task["id"], "--pod", "demo"]).exit_code == 1


class TestTaskPrune:
    def test_days_without_traces_is_a_usage_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)
        assert _runner.invoke(app, ["task", "prune", "--days", "3", "--pod", "demo"]).exit_code == 2

    def test_traces_reports_both_stores(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)

        result = _runner.invoke(
            app, ["task", "prune", "--traces", "--days", "0", "--dry-run", "--pod", "demo"]
        )

        assert result.exit_code == 0, result.output
        assert "trace file" in result.output
        assert "run record" in result.output


class TestRetiredNames:
    @pytest.mark.parametrize("name", ["runs", "trace", "delegate"])
    def test_a_removed_top_level_name_is_unknown(self, name: str) -> None:
        assert _runner.invoke(app, [name]).exit_code == 2
