"""``docket run``: the plan preview, the endpoint gate, the foreground progress view and the
in-place approval prompt. A real gated `bash` hop, through the real `DocketDriver` (only its
`ChatBackend` scripted), answered from a faked TTY.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

import pytest
from tests.conftest import record_isolation_off, repoint_docket_home
from typer.testing import CliRunner

import docket.config as _cfg
from docket.cli import _pod, _run, _setup
from docket.cli import app as _app
from docket.core import audit as _audit
from docket.core import dispatch as _dispatch
from docket.core import fleet as _fleet
from docket.core import pod as _pod_core
from docket.core.llm import ChatMessage, ChatResponse, TokenUsage, ToolCall, assistant
from docket.core.policy import install_policies
from docket.edges.adapters import docket_runtime as _dr
from docket.edges.adapters.docket_runtime import DocketDriver

SUBJECT = "docket.cli._run"

runner = CliRunner()


def _seed_pod(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    project: str = "demo",
    roles: tuple[str, ...] | None = None,
) -> Path:
    home = tmp_path / ".docket"
    (home / "workspaces" / "projects").mkdir(parents=True)
    (home / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    repoint_docket_home(monkeypatch, home)
    record_isolation_off(home)
    _pod.build_pod(project, roles or _pod.pod.DEFAULT_POD_ROLES, codebase=f"/src/{project}")
    return home


def _endpoint(monkeypatch: pytest.MonkeyPatch, ok: bool) -> None:
    piece = _setup.Piece("model endpoint", ok, "" if ok else "no provider", "docket setup")
    monkeypatch.setattr(_run, "readiness", lambda: _setup.Readiness(endpoint=piece))


def _runs_file() -> str:
    return _cfg.RUNS_FILE.read_text() if _cfg.RUNS_FILE.exists() else ""


class _FakeTTY(io.StringIO):
    """A stdin double that is both readable and reports as a TTY."""

    def isatty(self) -> bool:
        return True


def _final_response(text: str) -> ChatResponse:
    return ChatResponse(
        ok=True, message=assistant(text), finish_reason="stop", usage=TokenUsage(5, 5)
    )


class _ScriptedBackend:
    """Replays a fixed script of `ChatResponse`s -- mirrors
    `tests/integration/test_dispatch.py`'s `_ScriptedBackend`."""

    def __init__(self, responses: list[ChatResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[list[ChatMessage]] = []

    def complete(
        self,
        messages: list[ChatMessage],
        *,
        tools: Any = (),
        max_tokens: int | None = None,
        temperature: float | None = None,
        timeout: int = 120,
    ) -> ChatResponse:
        self.calls.append(list(messages))
        return self._responses.pop(0)


def _gated_bash_backend(after_gate: str) -> _ScriptedBackend:
    """Lead plans normally; the Implementer's first call is a `bash` command
    `high-risk-deploy` gates (`then: ask`). A third reply answers the model
    once the gate resolves, granted or denied, so the hop always finishes."""
    call = ToolCall(id="c1", name="bash", arguments=json.dumps({"command": "git push origin main"}))
    return _ScriptedBackend(
        [
            _final_response("lead plan"),
            ChatResponse(
                ok=True,
                message=assistant("", tool_calls=[call]),
                finish_reason="tool_calls",
                usage=TokenUsage(10, 5),
            ),
            _final_response(after_gate),
        ]
    )


def _fast_approval_polling(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_cfg, "TOOL_APPROVAL_POLL_INTERVAL_S", 0.02, raising=True)
    monkeypatch.setattr(_cfg, "TOOL_APPROVAL_TIMEOUT", 5, raising=True)


def _fake_tty(monkeypatch: pytest.MonkeyPatch, answer_line: str) -> None:
    monkeypatch.setattr("sys.stderr.isatty", lambda: True)
    import sys

    monkeypatch.setattr(sys, "stdin", _FakeTTY(answer_line))


class TestForegroundApprovalPrompt:
    def test_a_grants_the_gated_hop_once_and_audits_the_cli_channel(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)
        install_policies()
        _fast_approval_polling(monkeypatch)
        _fake_tty(monkeypatch, "a\n")

        backend = _gated_bash_backend("implementer done")
        driver = DocketDriver(backend_factory=lambda model: backend)
        monkeypatch.setattr(_dr, "default_driver", lambda: driver)

        _dispatch.enqueue_task("demo", "push the release", channel="cli")
        _run._pod_dispatch("demo")

        tasks = _dispatch.read_tasks("demo")
        assert tasks[0]["status"] == "done"
        audit_text = _audit.read_audit_text() or ""
        assert "approval.grant" in audit_text
        assert "channel=cli" in audit_text

    def test_d_denies_the_gated_hop(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """`d` denies through the same pair `docket task deny` uses: the tool result
        records `denialKind: approval_denied` and the audit line names the
        `cli` channel, exactly as a second-terminal `docket task deny` would."""
        home = _seed_pod(tmp_path, monkeypatch)
        install_policies()
        _fast_approval_polling(monkeypatch)
        _fake_tty(monkeypatch, "d\n")

        backend = _gated_bash_backend("acknowledged, not pushing")
        driver = DocketDriver(backend_factory=lambda model: backend)
        monkeypatch.setattr(_dr, "default_driver", lambda: driver)

        _dispatch.enqueue_task("demo", "push the release", channel="cli")
        _run._pod_dispatch("demo")

        tasks = _dispatch.read_tasks("demo")
        assert tasks[0]["status"] == "done"  # the model accepted the denial and finished
        trace_files = list((home / "traces" / "demo").glob("*.jsonl"))
        events = [json.loads(line) for tf in trace_files for line in tf.read_text().splitlines()]
        tool_results = [e for e in events if e.get("event_type") == "tool_result"]
        assert any(e["payload"].get("denialKind") == "approval_denied" for e in tool_results)
        audit_text = _audit.read_audit_text() or ""
        assert "approval.deny" in audit_text
        assert "channel=cli" in audit_text


class TestNoTtyNoChangePath:
    def test_without_a_tty_the_progress_module_is_never_invoked(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The card's no-change oracle: no TTY, no `--progress` -> the exact
        `_runs.execute` call this function has always made, nothing more."""
        _seed_pod(tmp_path, monkeypatch)
        monkeypatch.setattr("sys.stderr.isatty", lambda: False)

        from docket.cli import _progress

        def _boom(*a: Any, **k: Any) -> Any:
            raise AssertionError("dispatch_with_progress must not run without a TTY")

        monkeypatch.setattr(_progress, "dispatch_with_progress", _boom)
        monkeypatch.setattr(_dispatch, "dispatch_pod", lambda *a, **k: [_fake_task_result()])

        _dispatch.enqueue_task("demo", "quiet path", channel="cli")
        _run._pod_dispatch("demo")  # must not raise


class TestWaitingStatesAreNotErrors:
    def test_waiting_input_is_a_warning_not_an_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A parked question is an expected pause, rendered like waiting_approval."""
        from docket.core.dispatch import TaskResult

        _seed_pod(tmp_path, monkeypatch)
        monkeypatch.setattr("sys.stderr.isatty", lambda: False)
        parked = TaskResult(task_id="t1", status="waiting_input", hops=[], reason="parked")
        monkeypatch.setattr(_dispatch, "dispatch_pod", lambda *a, **k: [parked])
        calls: list[str] = []
        monkeypatch.setattr(_run.ui, "warn", lambda msg: calls.append("warn"))
        monkeypatch.setattr(_run.ui, "error", lambda msg: calls.append("error"))

        _dispatch.enqueue_task("demo", "ask first", channel="cli")
        _run._pod_dispatch("demo")

        assert calls == ["warn"]


def _fake_task_result() -> Any:
    from docket.core.dispatch import TaskResult

    return TaskResult(task_id="t1", status="done", hops=[])


class TestDryRun:
    def test_leaves_runs_and_tasks_untouched(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)
        _dispatch.enqueue_task("demo", "a task", channel="cli")
        before_runs, before_tasks = _runs_file(), _dispatch.read_tasks("demo")

        result = runner.invoke(_app, ["run", "--dry-run", "--pod", "demo"])

        assert result.exit_code == 0, result.output
        assert _runs_file() == before_runs
        assert _dispatch.read_tasks("demo") == before_tasks
        assert list((_cfg.TRACES_DIR / "demo").glob("*.jsonl")) == []

    def test_needs_no_model_endpoint(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _seed_pod(tmp_path, monkeypatch)
        _endpoint(monkeypatch, ok=False)
        assert runner.invoke(_app, ["run", "--dry-run", "--pod", "demo"]).exit_code == 0

    def test_a_two_member_pod_plans_two_runnable_hops(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch, roles=("lead", "implementer"))
        out = runner.invoke(_app, ["run", "--dry-run", "--pod", "demo"]).output
        assert "role=lead" in out and "role=implementer" in out
        assert "skipped" in out  # reviewer and tester are absent from the pod


class TestEndpointGate:
    def test_without_an_endpoint_run_exits_1_naming_setup(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)
        _dispatch.enqueue_task("demo", "a task", channel="cli")
        _endpoint(monkeypatch, ok=False)

        result = runner.invoke(_app, ["run", "--pod", "demo"])

        assert result.exit_code == 1
        assert "docket setup" in result.output
        assert _runs_file() == ""
        assert _dispatch.read_tasks("demo")[0]["status"] == "pending"

    def test_refuses_through_the_real_readiness_report(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The seam: no stand-in for ``readiness()``; a fresh home resolves to a hosted model
        with no credential, so the real report says the endpoint is missing."""
        _seed_pod(tmp_path, monkeypatch)
        _dispatch.enqueue_task("demo", "a task", channel="cli")
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

        result = runner.invoke(_app, ["run", "--pod", "demo"])

        assert result.exit_code == 1
        assert "docket setup" in result.output
        assert _runs_file() == ""


class TestUsage:
    def test_an_unknown_flag_exits_2_naming_it(self) -> None:
        result = runner.invoke(_app, ["run", "--bogus"])
        assert result.exit_code == 2
        assert "--bogus" in result.output

    def test_a_malformed_var_exits_2(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _seed_pod(tmp_path, monkeypatch)
        result = runner.invoke(_app, ["run", "--var", "novalue", "--pod", "demo", "--dry-run"])
        assert result.exit_code == 2

    def test_a_missing_pipeline_file_exits_2(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)
        result = runner.invoke(_app, ["run", "--pipeline", str(tmp_path / "nope.yaml")])
        assert result.exit_code == 2


class TestRun:
    def test_runs_the_pending_task_and_prints_the_summary_and_next_step(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)
        _endpoint(monkeypatch, ok=True)
        _dispatch.enqueue_task("demo", "a task", channel="cli")
        monkeypatch.setattr(_dispatch, "dispatch_pod", lambda *a, **k: [_fake_task_result()])

        result = runner.invoke(_app, ["run", "--pod", "demo"])

        assert result.exit_code == 0, result.output
        assert "1 done" in result.output and "0 failed" in result.output
        assert "Next: docket status" in result.output

    def test_pipeline_file_is_forwarded_to_the_executor(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)
        _endpoint(monkeypatch, ok=True)
        _dispatch.enqueue_task("demo", "a task", channel="cli")
        seen: dict[str, Any] = {}

        def _fake(project: str, **kw: Any) -> list[Any]:
            seen.update(kw)
            return [_fake_task_result()]

        monkeypatch.setattr(_dispatch, "dispatch_pod", _fake)
        spec = tmp_path / "p.pipeline.yaml"
        spec.write_text("name: solo\nsteps:\n  - id: lead\n    role: lead\n")

        result = runner.invoke(
            _app, ["run", "--pod", "demo", "--pipeline", str(spec), "--var", "k=v"]
        )

        assert result.exit_code == 0, result.output
        assert seen["spec"].name == "solo"
        assert seen["variables"] == {"k": "v"}

    def test_resume_clears_the_budget_pause_and_unblocks_tasks(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)
        _endpoint(monkeypatch, ok=True)
        _fleet.meta_set("demo-lead", "paused", True)
        _fleet.meta_set("demo-lead", "pausedReason", "budget")
        task = _dispatch.enqueue_task("demo", "held", channel="cli")
        monkeypatch.setattr(_dispatch, "unblock_pod", lambda project: 1)
        monkeypatch.setattr(_dispatch, "dispatch_pod", lambda *a, **k: [_fake_task_result()])
        assert task["status"] == "pending"

        result = runner.invoke(_app, ["run", "--pod", "demo", "--resume"])

        assert result.exit_code == 0, result.output
        assert _fleet.meta_get("demo-lead", "paused", "") == "False"
        assert "Unblocked 1" in result.output

    def test_an_invalid_pipeline_file_exits_1_before_dispatching(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)
        _endpoint(monkeypatch, ok=True)
        _dispatch.enqueue_task("demo", "a task", channel="cli")
        bad = tmp_path / "broken.pipeline.yaml"
        bad.write_text("name: broken\nsteps:\n  - id: build\n    role: implementer\n    nope: x\n")

        result = runner.invoke(_app, ["run", "--pod", "demo", "--pipeline", str(bad)])

        assert result.exit_code == 1
        assert _dispatch.read_tasks("demo")[0]["status"] == "pending"

    def test_dispatches_through_the_default_pipeline_with_the_fake_driver(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from tests.fakes import FakeDriver

        _seed_pod(tmp_path, monkeypatch)
        _endpoint(monkeypatch, ok=True)
        monkeypatch.setattr(_dr, "default_driver", lambda: FakeDriver(ok=True, cost=0.0))
        _dispatch.enqueue_task("demo", "a task", channel="cli")

        result = runner.invoke(_app, ["run", "--pod", "demo"])

        assert result.exit_code == 0, result.output
        assert _dispatch.read_tasks("demo")[0]["status"] == "done"

    def test_no_pending_tasks_is_a_warning_not_an_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)
        _endpoint(monkeypatch, ok=True)
        result = runner.invoke(_app, ["run", "--pod", "demo"])
        assert result.exit_code == 0
        assert "No pending tasks" in result.output

    def test_a_failed_task_exits_1_and_counts_as_failed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from docket.core.dispatch import TaskResult

        _seed_pod(tmp_path, monkeypatch)
        _endpoint(monkeypatch, ok=True)
        _dispatch.enqueue_task("demo", "a task", channel="cli")
        failed = TaskResult(task_id="t1", status="failed", hops=[], reason="verify failed")
        monkeypatch.setattr(_dispatch, "dispatch_pod", lambda *a, **k: [failed])

        result = runner.invoke(_app, ["run", "--pod", "demo"])

        assert "1 failed" in result.output
        assert "Next: docket inbox" in result.output


class TestFlushNotifyAfterDispatch:
    @staticmethod
    def _flush_returns(monkeypatch: pytest.MonkeyPatch, events: int) -> None:
        from docket.core import notify as _notify

        monkeypatch.setattr(_notify, "flush", lambda *_a, **_k: _notify.FlushReport(events=events))

    def test_events_with_only_console_warn(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        self._flush_returns(monkeypatch, 1)
        _run._flush_notify_after_dispatch()
        assert "docket setup notify enable desktop" in capsys.readouterr().out

    def test_no_events_stay_silent(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        self._flush_returns(monkeypatch, 0)
        _run._flush_notify_after_dispatch()
        assert capsys.readouterr().out == ""

    def test_a_delivering_channel_is_quiet(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from docket.core import channel as _channel

        _channel.enable_channel("desktop")
        self._flush_returns(monkeypatch, 1)
        _run._flush_notify_after_dispatch()
        assert capsys.readouterr().out == ""


_PIPELINE = "name: p\nsteps:\n  - id: migrate\n    run: {run}\n"
_SKILL = "---\nname: style-guide\ndescription: house style\n---\n{body}\n"


def _repo_pod(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, run: str = "make migrate") -> Path:
    """A pod whose recorded config is its repository's `.docket/`, the run step allowed."""
    from docket.core import pod_apply as _pa
    from docket.core import reviewed_repos as _rr

    home = tmp_path / ".docket"
    (home / "workspaces" / "projects").mkdir(parents=True)
    (home / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    repoint_docket_home(monkeypatch, home)
    record_isolation_off(home)
    code = tmp_path / "code"
    (code / ".docket" / "skills" / "style-guide").mkdir(parents=True)
    (code / ".docket" / "pipeline.yaml").write_text(_PIPELINE.format(run=run))
    (code / ".docket" / "skills" / "style-guide" / "SKILL.md").write_text(_SKILL.format(body="v1"))
    _pod.build_pod("demo", _pod.pod.DEFAULT_POD_ROLES, codebase=str(code))
    _pa.apply(_pa.plan_apply("demo", code / ".docket"))
    _rr.remember(code, _pa.classify_directory(code / ".docket").runs)
    return code


def _dispatches(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []
    monkeypatch.setattr(_run, "_pod_dispatch", lambda project, **kw: calls.append(project))
    _endpoint(monkeypatch, True)
    return calls


def _installed_skill() -> str:
    return (_cfg.pod_config_dir("demo") / "skills" / "style-guide" / "SKILL.md").read_text()


class TestRunPicksUpTheRepository:
    """`docket run` applies the repository's text changes and asks about a changed command."""

    def test_an_unchanged_repository_says_nothing_and_runs(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _repo_pod(tmp_path, monkeypatch)
        calls = _dispatches(monkeypatch)
        result = runner.invoke(_app, ["run", "--pod", "demo"])
        assert result.exit_code == 0 and calls == ["demo"]
        assert "Updated from the repository" not in result.output

    def test_a_changed_skill_is_applied_with_one_line_before_dispatch(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        code = _repo_pod(tmp_path, monkeypatch)
        (code / ".docket" / "skills" / "style-guide" / "SKILL.md").write_text(
            _SKILL.format(body="v2")
        )
        calls = _dispatches(monkeypatch)
        result = runner.invoke(_app, ["run", "--pod", "demo"])
        assert result.exit_code == 0 and calls == ["demo"]
        assert "-> Updated from the repository: skill style-guide." in result.output
        assert "v2" in _installed_skill()

    def test_dry_run_reads_nothing_and_writes_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        code = _repo_pod(tmp_path, monkeypatch)
        (code / ".docket" / "skills" / "style-guide" / "SKILL.md").write_text(
            _SKILL.format(body="v2")
        )
        _dispatches(monkeypatch)
        runner.invoke(_app, ["run", "--dry-run", "--pod", "demo"])
        assert "v1" in _installed_skill()

    def test_a_changed_command_off_a_terminal_runs_the_allowed_version_and_warns(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        code = _repo_pod(tmp_path, monkeypatch)
        (code / ".docket" / "pipeline.yaml").write_text(_PIPELINE.format(run="make evil"))
        (code / ".docket" / "skills" / "style-guide" / "SKILL.md").write_text(
            _SKILL.format(body="v2")
        )
        calls = _dispatches(monkeypatch)
        monkeypatch.setattr(_run, "_stdin_is_tty", lambda: False)
        result = runner.invoke(_app, ["run", "--pod", "demo"])
        assert result.exit_code == 0 and calls == ["demo"]
        assert "! The repository changed a command that needs your OK. Running with the" in (
            result.output
        )
        assert "To review it, run docket run on a terminal." in result.output
        assert "v1" in _installed_skill()
        assert "make migrate" in _pod_core.bound_pipeline_path("demo").read_text()

    def test_a_changed_command_on_a_terminal_shows_before_and_now_and_y_applies_it(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from docket.core import reviewed_repos as _rr

        code = _repo_pod(tmp_path, monkeypatch)
        (code / ".docket" / "pipeline.yaml").write_text(_PIPELINE.format(run="make evil"))
        calls = _dispatches(monkeypatch)
        monkeypatch.setattr(_run, "_stdin_is_tty", lambda: True)
        result = runner.invoke(_app, ["run", "--pod", "demo"], input="y\n")
        assert result.exit_code == 0 and calls == ["demo"]
        assert "The repository changed a command since you allowed it on " in result.output
        assert "make migrate" in result.output and "make evil" in result.output
        assert "Allow the new version? [y/N]" in result.output
        assert "make evil" in _pod_core.bound_pipeline_path("demo").read_text()
        found = _rr.lookup(code)
        assert found is not None and found.items[0].runs == "make evil"

    def test_n_runs_the_allowed_version(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        code = _repo_pod(tmp_path, monkeypatch)
        (code / ".docket" / "pipeline.yaml").write_text(_PIPELINE.format(run="make evil"))
        calls = _dispatches(monkeypatch)
        monkeypatch.setattr(_run, "_stdin_is_tty", lambda: True)
        result = runner.invoke(_app, ["run", "--pod", "demo"], input="n\n")
        assert result.exit_code == 0 and calls == ["demo"]
        assert "-> Running with the version you allowed on " in result.output
        assert "make migrate" in _pod_core.bound_pipeline_path("demo").read_text()
