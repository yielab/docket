"""The condensed-boundary cache marker, from the real producer to both real wires.

`condense_history` marks the last message of a condensed range; `anthropic_wire` and `openai_wire`
(for a Claude model id) place the third `cache_control` on it. No test here sets the mark by hand.
"""

from __future__ import annotations

from typing import Any

from docket.agent.ports import ChatMessage, Endpoint, ToolCall, assistant, system, user
from docket.agent.session import condense_history
from docket.models.adapters import anthropic_wire, openai_wire

SUBJECT = "docket.models.adapters.anthropic_wire"

_ANTHROPIC = Endpoint(
    base_url="http://127.0.0.1:1/v1", model_id="claude-haiku-5-5", max_output_tokens=64
)
_GATEWAY = Endpoint(base_url="http://127.0.0.1:1/v1", model_id="anthropic/claude-haiku-5-5")


def _history(rounds: int) -> list[ChatMessage]:
    out: list[ChatMessage] = [system("the prompt"), user("the task")]
    for n in range(rounds):
        call = ToolCall(id=f"c{n}", name="read", arguments=f'{{"path":"src/f{n}.py"}}')
        body = "\n".join(f"{i}\tline {n}-{i}" for i in range(1, 41))
        out.append(assistant("", [call]))
        out.append(ChatMessage(role="tool", content=body, tool_call_id=call.id, name="read"))
    out.append(assistant("noted"))
    out.append(user("continue"))
    return out


def _anthropic_marked(payload: dict[str, Any]) -> list[dict[str, Any]]:
    blocks = [*payload["system"], *(b for m in payload["messages"] for b in m["content"])]
    return [b for b in blocks if "cache_control" in b]


def _openai_marked(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return [m for m in payload["messages"] if isinstance(m["content"], list)]


class TestACondensedHistoryReachesBothWires:
    def test_three_markers_and_the_middle_one_on_the_marked_result(self) -> None:
        projected = condense_history(_history(8), keep=2, budget=0)
        boundary = [m for m in projected if m.cache_boundary]
        assert len(boundary) == 1 and boundary[0].role == "tool"
        marked_id = boundary[0].tool_call_id

        anthropic = anthropic_wire.build_payload(_ANTHROPIC, projected)
        blocks = _anthropic_marked(anthropic)
        assert len(blocks) == 3
        assert blocks[1]["type"] == "tool_result" and blocks[1]["tool_use_id"] == marked_id

        openai = openai_wire.build_payload(_GATEWAY, projected)
        messages = _openai_marked(openai)
        assert len(messages) == 3
        assert messages[1]["role"] == "tool" and messages[1]["tool_call_id"] == marked_id
        assert messages[1]["content"][0]["cache_control"] == {"type": "ephemeral"}

    def test_no_condensation_leaves_two_markers(self) -> None:
        projected = condense_history(_history(8), keep=2, budget=10_000_000)
        assert not any(m.cache_boundary for m in projected)

        assert len(_anthropic_marked(anthropic_wire.build_payload(_ANTHROPIC, projected))) == 2
        assert len(_openai_marked(openai_wire.build_payload(_GATEWAY, projected))) == 2
