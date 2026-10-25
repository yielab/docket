"""In-process chat backends and small builders shared by integration tests."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

from docket.agent import session as _sess
from docket.agent.ports import (
    ChatMessage,
    ChatResponse,
    TokenUsage,
    ToolCall,
    ToolSpec,
    TurnResult,
    assistant,
    tool_result,
)
from docket.agent.tools.registry import ToolContext
from docket.interfaces.telegram import poll
from docket.tasks.domain import task as _task
from tests.support.fakes import FakeDriver


@pytest.fixture
def ctx(tmp_path: Path) -> ToolContext:
    return ToolContext(
        agent_id="demo-agent", role="implementer", project="demo", roots=(tmp_path,), timeout=10
    )


def final(text: str = "done") -> ChatResponse:
    return ChatResponse(
        ok=True, message=assistant(text), finish_reason="stop", usage=TokenUsage(5, 5)
    )


class RecordingScriptedBackend:
    """Replays scripted responses and records each call's messages and the tools offered."""

    def __init__(self, responses: Sequence[ChatResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[list[ChatMessage]] = []
        self.tools_seen: list[Sequence[ToolSpec]] = []

    def complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        tools: Sequence[ToolSpec] = (),
        max_tokens: int | None = None,
        temperature: float | None = None,
        timeout: int = 120,
    ) -> ChatResponse:
        self.calls.append(list(messages))
        self.tools_seen.append(tools)
        return self._responses.pop(0)


def final_response(text: str) -> ChatResponse:
    return ChatResponse(
        ok=True, message=assistant(text), finish_reason="stop", usage=TokenUsage(5, 5)
    )


def implementer_messages(driver: FakeDriver) -> list[str]:
    return [c[2] for c in driver.calls if c[0].endswith("-implementer")]


def hop(role: str, output: str, member_id: str = "") -> _task.HopResult:
    return _task.HopResult(
        role=role, member_id=member_id or f"demo-{role}", ok=True, output=output, cost_usd=0.0
    )


def summarizing_driver(text: str = "summary of the old turns") -> _sess.SessionSummaryRunner:
    def _driver(
        agent_id: str,
        session_key: str,
        message: str,
        timeout: int,
        env: dict[str, str] | None = None,
    ) -> TurnResult:
        return TurnResult(True, text, 0.0, {})

    return _driver


def tool_call_turn(
    call_id: str = "c1", name: str = "read_file", arguments: str = "{}"
) -> list[ChatMessage]:
    call = ToolCall(id=call_id, name=name, arguments=arguments)
    return [assistant("", tool_calls=[call]), tool_result(call, f"result for {call_id}")]


@pytest.fixture
def ctx_in_workspace(workspace: Path) -> ToolContext:
    return ToolContext(agent_id="demo-implementer", roots=(workspace,), timeout=10)


@pytest.fixture(autouse=True)
def fast_backoffs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(poll, "TELEGRAM_UNCONFIGURED_BACKOFF_S", 0, raising=True)
    monkeypatch.setattr(poll, "TELEGRAM_ERROR_BACKOFF_S", 0, raising=True)
