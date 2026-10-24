"""``docket status``: one pod's tasks, tokens, outcomes and last run, or every pod with --all."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from tests.support.pods import seed_3 as _seed
from typer.testing import CliRunner

from docket.interfaces.cli.app import app as _app
from docket.interfaces.cli.commands import status as _status
from docket.kernel.home import current_home
from docket.platform import store as _store
from docket.teams import settings as _settings

SUBJECT = "docket.interfaces.cli.commands.status"

runner = CliRunner()


def _tasks(project: str, *statuses: str) -> None:
    rows = [
        {"id": f"t{i}", "description": "d", "status": s, "created": "2026-09-28T00:00:00+00:00"}
        for i, s in enumerate(statuses)
    ]
    _store.write_json(_settings.pod_task_list_path(project), {"tasks": rows})


def _trace(project: str, name: str, status: str) -> None:
    d = current_home().traces_dir / project
    d.mkdir(parents=True, exist_ok=True)
    events = [
        {"event_type": "session_start", "ts": "2026-10-01T10:00:00Z", "agent_role": "lead"},
        {
            "event_type": "session_end",
            "ts": "2026-10-01T10:00:05Z",
            "agent_role": "lead",
            "payload": {"status": status},
        },
    ]
    (d / f"{name}.jsonl").write_text("\n".join(json.dumps(e) for e in events) + "\n")


def _json(*args: str) -> Any:
    result = runner.invoke(_app, ["status", *args, "--json"])
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)


class TestTheSandboxOpensTheOutput:
    def test_the_first_line_is_the_sandbox_posture(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        with _seed(tmp_path):
            monkeypatch.setenv("DOCKET_SANDBOX_BACKEND", "landlock")

            lines = runner.invoke(_app, ["status", "--pod", "demo"]).output.splitlines()
            first = next(ln for ln in lines if ln.strip())

            assert first.startswith("Sandbox   off. The agent's commands run with your user's")
            assert "Isolation" not in "\n".join(lines)

    def test_all_opens_with_it_too(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        with _seed(tmp_path):
            monkeypatch.setenv("DOCKET_SANDBOX_BACKEND", "landlock")

            out = runner.invoke(_app, ["status", "--all"]).output

            assert out.lstrip().startswith("Sandbox   off.")


class TestCurrentPod:
    def test_a_scripted_trace_of_one_done_and_two_failed_reads_1_2_0(self, tmp_path: Path) -> None:
        with _seed(tmp_path):
            _trace("demo", "a", "done")
            _trace("demo", "b", "failed")
            _trace("demo", "c", "failed")

            out = runner.invoke(_app, ["status", "--pod", "demo"]).output

            assert "1 / 2 / 0" in out
            body = _json("--pod", "demo")
            assert body["outcomes"]["failure"] == 2

    def test_json_carries_tasks_usage_last_run_and_the_start_flag(self, tmp_path: Path) -> None:
        with _seed(tmp_path):
            _tasks("demo", "pending", "failed", "done")

            body = _json("--pod", "demo")

            assert body["tasks"]["pending"] == 1 and body["tasks"]["failed"] == 1
            assert set(body["usage"]) == {"input", "output", "estimateUsd"}
            assert body["lastRun"] is None
            assert body["running"] is False

    def test_approved_ready_counts_a_granted_pending_task(self, tmp_path: Path) -> None:
        with _seed(tmp_path):
            _store.write_json(
                _settings.pod_task_list_path("demo"),
                {"tasks": [{"id": "t", "status": "pending", "gateOverridePipelineIndex": 1}]},
            )
            assert _json("--pod", "demo")["tasks"]["approvedReady"] == 1

    def test_start_is_running_when_the_pid_file_names_a_live_process(self, tmp_path: Path) -> None:
        import os

        with _seed(tmp_path) as home:
            (home / "serve.pid").write_text(str(os.getpid()))
            assert _json("--pod", "demo")["running"] is True

    def test_no_pod_for_the_directory_exits_1(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        with _seed(tmp_path):
            monkeypatch.chdir(tmp_path)
            assert runner.invoke(_app, ["status"]).exit_code == 1


class TestPaused:
    def test_a_budget_paused_pod_says_so_in_json_and_text(self, tmp_path: Path) -> None:
        from docket.teams import fleet as _fleet

        with _seed(tmp_path):
            _fleet.meta_set("demo-lead", "paused", True)
            _fleet.meta_set("demo-lead", "pausedReason", "budget")

            body = _json("--pod", "demo")
            out = runner.invoke(_app, ["status", "--pod", "demo"]).output

            assert body["paused"] is True and body["pausedReason"] == "budget"
            line = next(ln for ln in out.splitlines() if ln.strip().startswith("Paused:"))
            assert "budget" in line and "docket run --resume" in line

    def test_a_pod_that_is_not_paused_has_no_paused_row(self, tmp_path: Path) -> None:
        with _seed(tmp_path):
            body = _json("--pod", "demo")
            out = runner.invoke(_app, ["status", "--pod", "demo"]).output

            assert body["paused"] is False and body["pausedReason"] == ""
            assert "Paused:" not in out

    def test_all_json_carries_it_per_pod(self, tmp_path: Path) -> None:
        from docket.teams import fleet as _fleet

        with _seed(tmp_path):
            _fleet.meta_set("demo-lead", "paused", True)
            _fleet.meta_set("demo-lead", "pausedReason", "budget")

            assert _json("--all")["projects"][0]["paused"] is True


class TestQueueCounts:
    def test_the_task_block_is_the_pod_reports_queue_counts_plus_approved_ready(
        self, tmp_path: Path
    ) -> None:
        from docket.hops.application import report as _pod_report

        with _seed(tmp_path):
            _tasks("demo", "pending", "pending", "running", "waiting_approval", "failed", "done")

            tasks = _json("--pod", "demo")["tasks"]

            assert tasks == {**_pod_report.task_counts("demo"), "approvedReady": 0}
            assert tasks["completed"] == 1 and tasks["pending"] == 2


class TestAllPods:
    def test_all_shows_failed_counts(self, tmp_path: Path) -> None:
        with _seed(tmp_path):
            _tasks("demo", "failed", "failed")
            assert "2 failed" in runner.invoke(_app, ["status", "--all"]).output

    def test_all_json_carries_the_inventory(self, tmp_path: Path) -> None:
        with _seed(tmp_path):
            body = _json("--all")
            assert [p["id"] for p in body["projects"]] == ["demo"]
            assert {"timestamp", "channels", "agents", "totalCostUsd"} <= set(body)
            assert {a["id"] for a in body["agents"]} == {"demo-lead", "demo-implementer"}


class TestHistory:
    def test_history_with_no_dated_data_is_an_empty_list(self, tmp_path: Path) -> None:
        with _seed(tmp_path):
            assert _json("--pod", "demo", "--history", "--days", "2") == {"history": []}


class TestCostSnapshot:
    def test_lists_every_agent_with_a_total(self, tmp_path: Path) -> None:
        with _seed(tmp_path):
            snap = _status.cost_snapshot()
            assert {a["id"] for a in snap["agents"]} == {"demo-lead", "demo-implementer"}
            assert snap["totalUsd"] == 0.0


class TestParkedQuestionAndSandbox:
    def test_a_waiting_input_task_is_counted_and_the_pod_is_waiting(self, tmp_path: Path) -> None:
        """A parked question shows in the JSON count, the pod state and the human Tasks line."""
        with _seed(tmp_path):
            _tasks("demo", "waiting_input", "pending")

            body = _json("--pod", "demo")
            out = runner.invoke(_app, ["status", "--pod", "demo"]).output

            assert body["tasks"]["waitingInput"] == 1
            assert body["status"] == "waiting"
            assert "1 waiting input" in out

    def test_isolation_reports_the_sandbox_state_in_json_and_on_the_line(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """JSON carries the phrase built from sandbox_state; the text opens with the Sandbox line."""
        with _seed(tmp_path):
            monkeypatch.setattr(
                _status,
                "sandbox_state",
                lambda: {"isolation": "off (default)", "network": "open", "backend": "landlock"},
            )
            phrase = "off (default); landlock found, network open"

            assert _json("--pod", "demo")["isolation"] == phrase
            assert "Sandbox   " in runner.invoke(_app, ["status", "--pod", "demo"]).output

            monkeypatch.setattr(
                _status,
                "sandbox_state",
                lambda: {"isolation": "on", "network": "none", "backend": "docker"},
            )
            assert _json("--pod", "demo")["isolation"] == "on (docker, network none)"

    def test_isolation_off_says_the_network_is_not_enforced(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A fresh home has isolation off, so `network none` would read as a cut it is not."""
        with _seed(tmp_path):
            monkeypatch.setenv("DOCKET_SANDBOX_BACKEND", "landlock")

            phrase = _json("--pod", "demo")["isolation"]

            assert phrase.endswith("network none (not enforced: isolation off)")


class TestCommandsRows:
    """`status` names the commands the operator allowed and any the repository since changed."""

    def _reviewed(self, tmp_path: Path, run: str) -> Path:
        from docket.governance import review as _rr
        from docket.governance.review import RunItem

        code = tmp_path / "code"
        (code / ".docket").mkdir(parents=True)
        (code / ".docket" / "pipeline.yaml").write_text(
            f"name: p\nsteps:\n  - migrate:\n      run: {run}\n"
        )
        _rr.remember(code, "demo", (RunItem("pipeline-step", "migrate", "make migrate"),))
        return code

    def test_allowed_and_changed_rows(self, tmp_path: Path) -> None:
        from docket.teams import fleet as _fleet
        from docket.teams import pod as _pod_core

        with _seed(tmp_path):
            code = self._reviewed(tmp_path, "make evil")
            _fleet.meta_set(_pod_core.member_id("demo", "lead"), "codebase", str(code))
            result = runner.invoke(_app, ["status", "--pod", "demo"])
            assert result.exit_code == 0
            assert "Commands:" in result.output
            assert "1 allowed on " in result.output and "(code " in result.output
            assert "1 changed in the repository, waiting for your OK: docket run asks" in (
                result.output
            )

    def test_no_review_no_rows(self, tmp_path: Path) -> None:
        with _seed(tmp_path):
            result = runner.invoke(_app, ["status", "--pod", "demo"])
            assert "Commands" not in result.output

    def test_unchanged_has_no_changed_row(self, tmp_path: Path) -> None:
        from docket.teams import fleet as _fleet
        from docket.teams import pod as _pod_core

        with _seed(tmp_path):
            code = self._reviewed(tmp_path, "make migrate")
            _fleet.meta_set(_pod_core.member_id("demo", "lead"), "codebase", str(code))
            result = runner.invoke(_app, ["status", "--pod", "demo"])
            assert (
                "1 allowed on " in result.output
                and "changed in the repository" not in result.output
            )
