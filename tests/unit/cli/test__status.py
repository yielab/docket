"""``docket status``: one pod's tasks, tokens, outcomes and last run, or every pod with --all."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from tests.conftest import repoint_docket_home
from typer.testing import CliRunner

import docket.config as _cfg
from docket.cli import _pod, _status
from docket.cli import app as _app
from docket.core import dispatch as _dispatch
from docket.edges import store as _store

SUBJECT = "docket.cli._status"

runner = CliRunner()


def _seed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, project: str = "demo") -> Path:
    home = tmp_path / ".docket"
    (home / "workspaces" / "projects").mkdir(parents=True)
    (home / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    repoint_docket_home(monkeypatch, home)
    _pod.build_pod(project, ("lead", "implementer"), codebase=f"/src/{project}")
    return home


def _tasks(project: str, *statuses: str) -> None:
    rows = [
        {"id": f"t{i}", "description": "d", "status": s, "created": "2026-09-28T00:00:00+00:00"}
        for i, s in enumerate(statuses)
    ]
    _store.write_json(_dispatch.pod_task_list_path(project), {"tasks": rows})


def _trace(project: str, name: str, status: str) -> None:
    d = _cfg.TRACES_DIR / project
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
        _seed(tmp_path, monkeypatch)
        monkeypatch.setenv("DOCKET_SANDBOX_BACKEND", "landlock")

        lines = runner.invoke(_app, ["status", "--pod", "demo"]).output.splitlines()
        first = next(ln for ln in lines if ln.strip())

        assert first.startswith("Sandbox   off. The agent's commands run with your user's")
        assert "Isolation" not in "\n".join(lines)

    def test_all_opens_with_it_too(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _seed(tmp_path, monkeypatch)
        monkeypatch.setenv("DOCKET_SANDBOX_BACKEND", "landlock")

        out = runner.invoke(_app, ["status", "--all"]).output

        assert out.lstrip().startswith("Sandbox   off.")


class TestCurrentPod:
    def test_a_scripted_trace_of_one_done_and_two_failed_reads_1_2_0(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed(tmp_path, monkeypatch)
        _trace("demo", "a", "done")
        _trace("demo", "b", "failed")
        _trace("demo", "c", "failed")

        out = runner.invoke(_app, ["status", "--pod", "demo"]).output

        assert "1 / 2 / 0" in out
        body = _json("--pod", "demo")
        assert body["outcomes"]["failure"] == 2

    def test_json_carries_tasks_usage_last_run_and_the_start_flag(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed(tmp_path, monkeypatch)
        _tasks("demo", "pending", "failed", "done")

        body = _json("--pod", "demo")

        assert body["tasks"]["pending"] == 1 and body["tasks"]["failed"] == 1
        assert set(body["usage"]) == {"input", "output", "estimateUsd"}
        assert body["lastRun"] is None
        assert body["running"] is False

    def test_approved_ready_counts_a_granted_pending_task(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed(tmp_path, monkeypatch)
        _store.write_json(
            _dispatch.pod_task_list_path("demo"),
            {"tasks": [{"id": "t", "status": "pending", "gateOverridePipelineIndex": 1}]},
        )
        assert _json("--pod", "demo")["tasks"]["approvedReady"] == 1

    def test_start_is_running_when_the_pid_file_names_a_live_process(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import os

        home = _seed(tmp_path, monkeypatch)
        (home / "serve.pid").write_text(str(os.getpid()))
        assert _json("--pod", "demo")["running"] is True

    def test_no_pod_for_the_directory_exits_1(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed(tmp_path, monkeypatch)
        monkeypatch.chdir(tmp_path)
        assert runner.invoke(_app, ["status"]).exit_code == 1


class TestAllPods:
    def test_all_shows_failed_counts(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _seed(tmp_path, monkeypatch)
        _tasks("demo", "failed", "failed")
        assert "2 failed" in runner.invoke(_app, ["status", "--all"]).output

    def test_all_json_carries_the_inventory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed(tmp_path, monkeypatch)
        body = _json("--all")
        assert [p["id"] for p in body["projects"]] == ["demo"]
        assert {"timestamp", "channels", "agents", "totalCostUsd"} <= set(body)
        assert {a["id"] for a in body["agents"]} == {"demo-lead", "demo-implementer"}


class TestHistory:
    def test_history_with_no_dated_data_is_an_empty_list(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed(tmp_path, monkeypatch)
        assert _json("--pod", "demo", "--history", "--days", "2") == {"history": []}


class TestCostSnapshot:
    def test_lists_every_agent_with_a_total(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed(tmp_path, monkeypatch)
        snap = _status.cost_snapshot()
        assert {a["id"] for a in snap["agents"]} == {"demo-lead", "demo-implementer"}
        assert snap["totalUsd"] == 0.0


class TestRemovedCommands:
    @pytest.mark.parametrize("name", ["cost", "metrics", "snapshot", "dispatch"])
    def test_a_removed_name_is_an_unknown_command(self, name: str) -> None:
        assert runner.invoke(_app, [name]).exit_code == 2


class TestParkedQuestionAndSandbox:
    def test_a_waiting_input_task_is_counted_and_the_pod_is_waiting(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A parked question shows in the JSON count, the pod state and the human Tasks line."""
        _seed(tmp_path, monkeypatch)
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
        _seed(tmp_path, monkeypatch)
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


class TestCommandsRows:
    """`status` names the commands the operator allowed and any the repository since changed."""

    def _reviewed(self, tmp_path: Path, run: str) -> Path:
        from docket.core import reviewed_repos as _rr
        from docket.core.pod_apply import RunItem

        code = tmp_path / "code"
        (code / ".docket").mkdir(parents=True)
        (code / ".docket" / "pipeline.yaml").write_text(
            f"name: p\nsteps:\n  - id: migrate\n    run: {run}\n"
        )
        _rr.remember(code, (RunItem("pipeline-step", "migrate", "make migrate"),))
        return code

    def test_allowed_and_changed_rows(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from docket.core import fleet as _fleet
        from docket.core import pod as _pod_core

        _seed(tmp_path, monkeypatch)
        code = self._reviewed(tmp_path, "make evil")
        _fleet.meta_set(_pod_core.member_id("demo", "lead"), "codebase", str(code))
        result = runner.invoke(_app, ["status", "--pod", "demo"])
        assert result.exit_code == 0
        assert "Commands:" in result.output
        assert "1 allowed on " in result.output and "(code " in result.output
        assert "1 changed in the repository, waiting for your OK: docket run asks" in (
            result.output
        )

    def test_no_review_no_rows(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _seed(tmp_path, monkeypatch)
        result = runner.invoke(_app, ["status", "--pod", "demo"])
        assert "Commands" not in result.output

    def test_unchanged_has_no_changed_row(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from docket.core import fleet as _fleet
        from docket.core import pod as _pod_core

        _seed(tmp_path, monkeypatch)
        code = self._reviewed(tmp_path, "make migrate")
        _fleet.meta_set(_pod_core.member_id("demo", "lead"), "codebase", str(code))
        result = runner.invoke(_app, ["status", "--pod", "demo"])
        assert "1 allowed on " in result.output and "changed in the repository" not in result.output
