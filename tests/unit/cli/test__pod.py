"""`docket pod <p> dispatch`'s foreground progress view and in-place approval
prompt. A real gated `bash` hop, through the real `DocketDriver` (only its
`ChatBackend` scripted), answered from a faked TTY.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

import pytest
from tests.conftest import repoint_docket_home

import docket.config as _cfg
from docket.cli import _pod
from docket.core import audit as _audit
from docket.core import dispatch as _dispatch
from docket.core.llm import ChatMessage, ChatResponse, TokenUsage, ToolCall, assistant
from docket.core.policy import install_policies
from docket.edges.adapters import docket_runtime as _dr
from docket.edges.adapters.docket_runtime import DocketDriver

SUBJECT = "docket.cli._pod"


def _seed_pod(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, project: str = "demo") -> Path:
    home = tmp_path / ".docket"
    (home / "workspaces" / "projects").mkdir(parents=True)
    (home / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    repoint_docket_home(monkeypatch, home)
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


def _fake_task_result() -> Any:
    from docket.core.dispatch import TaskResult

    return TaskResult(task_id="t1", status="done", hops=[])
