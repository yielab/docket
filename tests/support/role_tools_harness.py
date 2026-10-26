"""Meta writer, scripted backend and response builder for the role-tools tests."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from docket.agent.ports import ChatMessage, ChatResponse, ToolSpec
from docket.kernel.home import current_home
from docket.platform import store as _store


def _write_meta(agent_id: str, **overrides: object) -> Path:
    ws = current_home().workspace_dir(agent_id)
    ws.mkdir(parents=True, exist_ok=True)
    data: dict[str, object] = {"kind": "project", "role": "implementer"}
    data.update(overrides)
    _store.write_json(current_home().meta_path(agent_id), data)
    return ws


class _ScriptedBackend:
    def __init__(self, responses: Sequence[ChatResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[list[ChatMessage]] = []

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
        return self._responses.pop(0)
