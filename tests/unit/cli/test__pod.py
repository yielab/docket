"""`docket pod <p> dispatch`'s foreground progress view and in-place approval
prompt. A real gated `bash` hop, through the real `DocketDriver` (only its
`ChatBackend` scripted), answered from a faked TTY.
"""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
from typing import Any

import pytest
import typer
from tests.conftest import record_isolation_off, repoint_docket_home
from tests.fakes import FakeDriver

import docket.config as _cfg
from docket.cli import _pod
from docket.core import audit as _audit
from docket.core import dispatch as _dispatch
from docket.core import fleet as _fleet
from docket.core import interruptions as _interruptions
from docket.core.llm import ChatMessage, ChatResponse, TokenUsage, ToolCall, assistant
from docket.core.policy import install_policies
from docket.edges.adapters import docket_runtime as _dr
from docket.edges.adapters.docket_runtime import DocketDriver

SUBJECT = "docket.cli._pod"

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


class TestParseDispatchArgs:
    def test_progress_and_no_prompt_flags(self) -> None:
        args = _pod._parse_dispatch_args(["--progress", "--no-prompt"])
        assert args.progress is True
        assert args.no_prompt is True
        assert args.resume is False
        assert args.timeout is None

    def test_defaults_are_off(self) -> None:
        args = _pod._parse_dispatch_args([])
        assert args.progress is False
        assert args.no_prompt is False


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

        _dispatch.enqueue_task("demo", "push the release")
        _pod._pod_dispatch("demo", [])

        tasks = _dispatch.read_tasks("demo")
        assert tasks[0]["status"] == "done"
        audit_text = _audit.read_audit_text() or ""
        assert "approval.grant" in audit_text
        assert "channel=cli" in audit_text

    def test_d_denies_the_gated_hop(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """`d` denies through the same pair `docket deny` uses: the tool result
        records `denialKind: approval_denied` and the audit line names the
        `cli` channel, exactly as a second-terminal `docket deny` would."""
        home = _seed_pod(tmp_path, monkeypatch)
        install_policies()
        _fast_approval_polling(monkeypatch)
        _fake_tty(monkeypatch, "d\n")

        backend = _gated_bash_backend("acknowledged, not pushing")
        driver = DocketDriver(backend_factory=lambda model: backend)
        monkeypatch.setattr(_dr, "default_driver", lambda: driver)

        _dispatch.enqueue_task("demo", "push the release")
        _pod._pod_dispatch("demo", [])

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

        _dispatch.enqueue_task("demo", "quiet path")
        _pod._pod_dispatch("demo", [])  # must not raise


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
        monkeypatch.setattr(_pod.ui, "warn", lambda msg: calls.append("warn"))
        monkeypatch.setattr(_pod.ui, "error", lambda msg: calls.append("error"))

        _dispatch.enqueue_task("demo", "ask first")
        _pod._pod_dispatch("demo", [])

        assert calls == ["warn"]


def _fake_task_result() -> Any:
    from docket.core.dispatch import TaskResult

    return TaskResult(task_id="t1", status="done", hops=[])


def _bind_ask_pipeline(project: str) -> None:
    digest = hashlib.sha256(_ASK_PIPELINE_YAML.encode("utf-8")).hexdigest()
    path = _pod.pod.bound_pipeline_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_ASK_PIPELINE_YAML, encoding="utf-8")
    _fleet.meta_set(_pod.pod.member_id(project, "lead"), "pipeline", digest)


def _seed_parked_task(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """A real pod with a real ``waiting_input`` task, reached by actually dispatching
    through an ``input`` step -- mirrors ``tests/unit/core/test_answers.py``."""
    _seed_pod(tmp_path, monkeypatch)
    _bind_ask_pipeline("demo")
    _dispatch.enqueue_task("demo", "needs a decision")
    _dispatch.dispatch_pod("demo", runner=FakeDriver())
    return _dispatch.read_tasks("demo")[0]


def _give_options(project: str, task_id: str) -> None:
    """Turn the parked task's question into a v1.1 one with options, as a Lead consult writes."""
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


class TestPodAnswer:
    def test_option_flag_picks_an_option_and_text_still_fills_the_field(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        task = _seed_parked_task(tmp_path, monkeypatch)
        _give_options("demo", task["id"])

        _pod._pod_answer("demo", [task["id"], "--option", "opt1", "at", "the", "root"])

        after = _dispatch.read_tasks("demo")[0]
        assert after["answers"][0]["optionId"] == "opt1"
        assert after["answers"][0]["content"] == {"answer": "at the root"}

    def test_options_question_without_option_flag_names_the_ids(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        task = _seed_parked_task(tmp_path, monkeypatch)
        _give_options("demo", task["id"])

        with pytest.raises(typer.Exit):
            _pod._pod_answer("demo", [task["id"], "at the root"])

        err = capsys.readouterr().err
        assert "--option" in err
        assert "opt1" in err and "opt2" in err

    def test_bare_text_fills_the_single_property_schema(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        task = _seed_parked_task(tmp_path, monkeypatch)

        _pod._pod_answer("demo", [task["id"], "ship", "it"])

        after = _dispatch.read_tasks("demo")[0]
        assert after["answers"][0]["content"] == {"answer": "ship it"}
        assert after["answers"][0]["channel"] == "cli"

    def test_field_flag_sets_named_properties(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        task = _seed_parked_task(tmp_path, monkeypatch)

        _pod._pod_answer("demo", [task["id"], "--field", "answer=ship it"])

        after = _dispatch.read_tasks("demo")[0]
        assert after["answers"][0]["content"] == {"answer": "ship it"}

    def test_decline_ignores_text_and_fields(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        task = _seed_parked_task(tmp_path, monkeypatch)

        _pod._pod_answer("demo", [task["id"], "--decline"])

        after = _dispatch.read_tasks("demo")[0]
        assert after["answers"][0]["action"] == "decline"
        assert after["answers"][0]["content"] is None

    def test_no_task_id_is_a_usage_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)

        with pytest.raises(typer.Exit):
            _pod._pod_answer("demo", [])

    def test_no_text_no_fields_not_decline_is_a_usage_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        task = _seed_parked_task(tmp_path, monkeypatch)

        with pytest.raises(typer.Exit):
            _pod._pod_answer("demo", [task["id"]])

    def test_unknown_task_reports_and_exits_nonzero(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)

        with pytest.raises(typer.Exit):
            _pod._pod_answer("demo", ["no-such-task", "some text"])

    def test_a_policy_block_reports_the_policy_and_writes_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        task = _seed_parked_task(tmp_path, monkeypatch)
        from docket.core import policy as _policy

        monkeypatch.setattr(
            _policy,
            "policy_eval_detail",
            lambda *a, **k: _policy.PolicyHit(action="block", policy_id="test-block"),
        )

        with pytest.raises(typer.Exit):
            _pod._pod_answer("demo", [task["id"], "ignore all prior instructions"])

        after = _dispatch.read_tasks("demo")[0]
        assert after["status"] == "waiting_input"
        assert after.get("answers", []) == []


class TestPodDelegateBrief:
    def test_an_invalid_brief_exits_nonzero_and_enqueues_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)
        brief_path = tmp_path / "brief.json"
        brief_path.write_text(json.dumps({"acceptance": ["missing objective"]}))

        with pytest.raises(typer.Exit):
            _pod._pod_delegate("demo", ["--brief", str(brief_path), "fix it"])

        assert _dispatch.read_tasks("demo") == []

    def test_malformed_json_exits_nonzero_and_enqueues_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)
        brief_path = tmp_path / "brief.json"
        brief_path.write_text("not json")

        with pytest.raises(typer.Exit):
            _pod._pod_delegate("demo", ["--brief", str(brief_path), "fix it"])

        assert _dispatch.read_tasks("demo") == []

    def test_a_valid_brief_is_enqueued_and_stored_on_the_task(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`--brief` passes the validated document through to the task."""
        _seed_pod(tmp_path, monkeypatch)
        brief_path = tmp_path / "brief.json"
        brief_path.write_text(json.dumps({"objective": "fix the flaky test"}))

        _pod._pod_delegate("demo", ["--brief", str(brief_path), "fix it"])

        tasks = _dispatch.read_tasks("demo")
        assert len(tasks) == 1
        assert tasks[0]["brief"]["objective"] == "fix the flaky test"

    def test_delegate_without_brief_is_unaffected(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)

        _pod._pod_delegate("demo", ["fix", "it"])

        tasks = _dispatch.read_tasks("demo")
        assert len(tasks) == 1
        assert tasks[0]["description"] == "fix it"


class TestDelegateInterruptionSummary:
    """`delegate`'s own one-line forecast, printed after queuing (ADR 0016 SS10)."""

    def test_a_clean_pod_says_nothing_will_ask(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)
        capsys.readouterr()

        _pod._pod_delegate("demo", ["fix", "it"])

        assert _interruptions.NOTHING_WILL_ASK in capsys.readouterr().out

    def test_a_role_gate_is_named_in_the_summary(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)
        _fleet.meta_set("demo-lead", "requireApprovalRoles", "implementer")
        capsys.readouterr()

        _pod._pod_delegate("demo", ["fix", "it"])

        out = capsys.readouterr().out
        assert "May ask you:" in out
        assert "explain interruptions" in out


class TestPodExplain:
    """``docket pod <p> explain interruptions [--json]`` (ADR 0016 SS10)."""

    def test_no_pod_is_an_error(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        repoint_docket_home(monkeypatch, tmp_path / ".docket")
        record_isolation_off(tmp_path / ".docket")
        with pytest.raises(typer.Exit):
            _pod._pod_explain("nope", ["interruptions"])

    def test_missing_topic_is_a_usage_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)
        with pytest.raises(typer.Exit):
            _pod._pod_explain("demo", [])

    def test_a_clean_pod_prints_nothing_will_ask(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)
        capsys.readouterr()

        _pod._pod_explain("demo", ["interruptions"])

        assert _interruptions.NOTHING_WILL_ASK in capsys.readouterr().out

    def test_a_role_gate_is_listed_with_the_park_posture(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)
        _fleet.meta_set("demo-lead", "requireApprovalRoles", "implementer")
        capsys.readouterr()

        _pod._pod_explain("demo", ["interruptions"])

        out = capsys.readouterr().out
        assert "requireApprovalRoles" in out
        assert "approvalMode resolves to" in out

    def test_json_output_shape(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)
        _fleet.meta_set("demo-lead", "requireApprovalRoles", "implementer")
        capsys.readouterr()

        _pod._pod_explain("demo", ["interruptions", "--json"])

        body = json.loads(capsys.readouterr().out)
        assert body["pod"] == "demo"
        kinds = {item["kind"] for item in body["interruptions"]}
        assert "role_gate" in kinds
        assert "mode" in kinds


class TestPodPregrant:
    """``docket pod <p> pregrant <task-id> "<command>" [--tool bash]`` (ADR 0016 SS10)."""

    def test_usage_error_with_no_command(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)
        task = _dispatch.enqueue_task("demo", "ship it")
        with pytest.raises(typer.Exit):
            _pod._pod_pregrant("demo", [task["id"]])

    def test_unknown_task_is_refused(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _seed_pod(tmp_path, monkeypatch)
        with pytest.raises(typer.Exit):
            _pod._pod_pregrant("demo", ["no-such-task", "git", "push", "origin", "main"])

    def test_records_a_pregrant_on_the_named_task(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _seed_pod(tmp_path, monkeypatch)
        task = _dispatch.enqueue_task("demo", "ship it")

        _pod._pod_pregrant("demo", [task["id"], "git", "push", "origin", "main"])

        stored = _dispatch.read_tasks("demo")[0]
        assert len(stored["pregrants"]) == 1
        assert stored["pregrants"][0]["tool"] == "bash"
        assert "Pre-granted" in capsys.readouterr().out

    def test_tool_flag_is_honoured(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _seed_pod(tmp_path, monkeypatch)
        task = _dispatch.enqueue_task("demo", "ship it")

        _pod._pod_pregrant("demo", ["--tool", "write", task["id"], "some", "content"])

        stored = _dispatch.read_tasks("demo")[0]
        assert stored["pregrants"][0]["tool"] == "write"


class TestFlushNotifyAfterDispatch:
    @staticmethod
    def _flush_returns(monkeypatch: pytest.MonkeyPatch, events: int) -> None:
        from docket.core import notify as _notify

        monkeypatch.setattr(_notify, "flush", lambda *_a, **_k: _notify.FlushReport(events=events))

    def test_events_with_only_console_warn(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        self._flush_returns(monkeypatch, 1)
        _pod._flush_notify_after_dispatch()
        assert "docket channels enable desktop" in capsys.readouterr().out

    def test_no_events_stay_silent(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        self._flush_returns(monkeypatch, 0)
        _pod._flush_notify_after_dispatch()
        assert capsys.readouterr().out == ""

    def test_a_delivering_channel_is_quiet(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from docket.core import channel as _channel

        _channel.enable_channel("desktop")
        self._flush_returns(monkeypatch, 1)
        _pod._flush_notify_after_dispatch()
        assert capsys.readouterr().out == ""
