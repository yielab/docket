"""The `verify` tool: offered only to a hop whose step has a verify command, run exactly that
command through the gate's own runner, and never parked by the command classifier."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import pytest
from tests.support.driver_harness import _final_response, _ScriptedBackend
from tests.support.pods import write_meta_overrides as _write_meta

from docket.agent.ports import (
    DOCKET_APPROVAL_MODE,
    DOCKET_VERIFY_PLAN,
    ChatMessage,
    ChatResponse,
    TokenUsage,
    ToolCall,
    ToolSpec,
    assistant,
)
from docket.governance import audit as _audit
from docket.hops.application.driver import DocketDriver
from docket.hops.application.verify_tool import VerifyPlan, plan_env_value

SUBJECT = "docket.hops.application.driver"


class _RecordingBackend(_ScriptedBackend):
    """A scripted backend that also remembers the tool names it was offered."""

    def __init__(self, responses: Sequence[ChatResponse]) -> None:
        super().__init__(responses)
        self.offered: list[list[str]] = []

    def complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        tools: Sequence[ToolSpec] = (),
        max_tokens: int | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
        tool_choice: str | None = None,
        timeout: int = 120,
    ) -> ChatResponse:
        self.offered.append([t.name for t in tools])
        return super().complete(
            messages, tools=tools, max_tokens=max_tokens, temperature=temperature, timeout=timeout
        )


def _verify_call(arguments: dict[str, object]) -> ChatResponse:
    call = ToolCall(id="v1", name="verify", arguments=json.dumps(arguments))
    return ChatResponse(
        ok=True,
        message=assistant("", tool_calls=[call]),
        finish_reason="tool_calls",
        usage=TokenUsage(5, 5),
    )


def _plan(tmp_path: Path, command: str, timeout: int = 30) -> dict[str, str]:
    return {DOCKET_VERIFY_PLAN: plan_env_value(VerifyPlan(command, str(tmp_path), timeout))}


def _turn(role: str, tmp_path: Path, env: dict[str, str], backend: _RecordingBackend) -> None:
    _write_meta("solo-agent", role=role, codebase=str(tmp_path))
    driver = DocketDriver(backend_factory=lambda model: backend)
    result = driver.run_turn("solo-agent", "agent:solo-agent:default", "go", 30, env)
    assert result.ok is True, result.error


@pytest.mark.parametrize(
    ("role", "with_plan", "offered"),
    [
        ("implementer", True, True),
        ("operator", True, True),
        ("reviewer", True, False),
        ("lead", True, False),
        ("implementer", False, False),
    ],
)
def test_verify_is_offered_only_with_a_command_and_a_role_that_may_exec(
    tmp_path: Path, role: str, with_plan: bool, offered: bool
) -> None:
    backend = _RecordingBackend([_final_response("done")])
    _turn(role, tmp_path, _plan(tmp_path, "true") if with_plan else {}, backend)
    assert ("verify" in backend.offered[0]) is offered


def test_verify_runs_exactly_the_steps_command_in_its_directory_and_reports_the_exit(
    tmp_path: Path,
) -> None:
    command = "echo ran > marker.txt && echo checked the thing && exit 3"
    backend = _RecordingBackend(
        [_verify_call({"command": "touch other.txt"}), _final_response("done")]
    )
    _turn("implementer", tmp_path, _plan(tmp_path, command), backend)

    tool_message = next(m for m in backend.calls[1] if m.role == "tool")
    assert tool_message.content == "exit 3\nchecked the thing"
    assert (tmp_path / "marker.txt").read_text() == "ran\n"
    assert not (tmp_path / "other.txt").exists()


def test_a_silent_failure_is_just_the_exit_code(tmp_path: Path) -> None:
    backend = _RecordingBackend([_verify_call({}), _final_response("done")])
    _turn("implementer", tmp_path, _plan(tmp_path, "false"), backend)
    assert next(m for m in backend.calls[1] if m.role == "tool").content == "exit 1"


def test_a_command_the_classifier_would_ask_about_is_not_parked_and_leaves_no_audit_row(
    tmp_path: Path,
) -> None:
    command = "echo ok > out.txt; curl --version >/dev/null 2>&1; true"
    backend = _RecordingBackend([_verify_call({}), _final_response("done")])
    env = {**_plan(tmp_path, command), DOCKET_APPROVAL_MODE: "refuse"}
    _turn("implementer", tmp_path, env, backend)

    assert next(m for m in backend.calls[1] if m.role == "tool").content == "exit 0"
    assert [e for e in _audit.read_audit() if str(e["action"]).startswith("tool.")] == []


def test_the_report_is_normalized_like_a_bash_result(tmp_path: Path) -> None:
    command = "printf '\\033[31mfail\\033[0m\\n'; yes boom | head -n 30; exit 1"
    backend = _RecordingBackend([_verify_call({}), _final_response("done")])
    _turn("implementer", tmp_path, _plan(tmp_path, command), backend)

    tool_message = next(m for m in backend.calls[1] if m.role == "tool")
    assert tool_message.content == "exit 1\nfail\nboom  [x 30]"
