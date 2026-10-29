"""The Anthropic Messages wire (`models/adapters/anthropic_wire.py`): encoding, decoding, usage.

The recorded response bodies under `tests/fixtures/anthropic-messages/` are the oracle for decoding;
no test here opens a socket.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from docket.agent.ports import (
    ChatMessage,
    Endpoint,
    ToolCall,
    ToolSpec,
    assistant,
    system,
    tool_result,
    user,
)
from docket.models.adapters import anthropic_wire as wire

SUBJECT = "docket.models.adapters.anthropic_wire"

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "anthropic-messages"

_ENDPOINT = Endpoint(
    base_url="http://127.0.0.1:1/v1", model_id="claude-haiku-4-5", max_output_tokens=2048
)
_EPHEMERAL = {"type": "ephemeral"}


def _recorded(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def _conversation() -> list[ChatMessage]:
    return [
        system("You are the lead."),
        system("Second rule."),
        user("list the files"),
        assistant(
            "",
            [
                ToolCall("t1", "bash", '{"command":"ls"}'),
                ToolCall("t2", "read", '{"path":"README.md"}'),
            ],
        ),
        tool_result(ToolCall("t1", "bash", "{}"), "a.txt"),
        tool_result(ToolCall("t2", "read", "{}"), "hello"),
        user("go on"),
    ]


class TestEncoding:
    def test_system_messages_become_top_level_blocks_and_never_a_message(self) -> None:
        payload = wire.build_payload(_ENDPOINT, _conversation())

        assert [b["text"] for b in payload["system"]] == ["You are the lead.", "Second rule."]
        assert all(m["role"] != "system" for m in payload["messages"])

    def test_the_turn_with_two_calls_and_two_results_encodes_to_alternating_roles(self) -> None:
        payload = wire.build_payload(_ENDPOINT, _conversation())

        roles = [m["role"] for m in payload["messages"]]
        assistant_blocks = payload["messages"][1]["content"]
        results = payload["messages"][2]["content"]
        assert roles == ["user", "assistant", "user"]
        assert [b["type"] for b in assistant_blocks] == ["tool_use", "tool_use"]
        assert assistant_blocks[0] == {
            "type": "tool_use",
            "id": "t1",
            "name": "bash",
            "input": {"command": "ls"},
        }
        assert [b["type"] for b in results] == ["tool_result", "tool_result", "text"]
        assert results[0] == {"type": "tool_result", "tool_use_id": "t1", "content": "a.txt"}
        assert results[2]["text"] == "go on"

    def test_a_call_whose_arguments_do_not_parse_is_sent_with_an_empty_input(self) -> None:
        messages = [user("x"), assistant("", [ToolCall("t1", "bash", "{not json")])]

        payload = wire.build_payload(_ENDPOINT, messages)

        assert payload["messages"][1]["content"][0]["input"] == {}

    def test_an_assistant_text_precedes_its_calls_and_an_empty_one_is_no_block(self) -> None:
        call = ToolCall("t1", "bash", "{}")
        with_text = wire.build_payload(_ENDPOINT, [user("x"), assistant("thinking", [call])])
        without = wire.build_payload(_ENDPOINT, [user("x"), assistant("", [call])])

        assert [b["type"] for b in with_text["messages"][1]["content"]] == ["text", "tool_use"]
        assert [b["type"] for b in without["messages"][1]["content"]] == ["tool_use"]

    def test_cache_markers_sit_on_the_last_system_block_and_the_last_block_only(self) -> None:
        payload = wire.build_payload(_ENDPOINT, _conversation())

        marked = [
            b
            for b in [*payload["system"], *(b for m in payload["messages"] for b in m["content"])]
            if "cache_control" in b
        ]
        assert marked == [payload["system"][-1], payload["messages"][-1]["content"][-1]]
        assert all(b["cache_control"] == _EPHEMERAL for b in marked)

    def test_every_model_on_the_dialect_is_marked_not_only_claude_ids(self) -> None:
        other = Endpoint(base_url="http://x/v1", model_id="proxy-model", max_output_tokens=64)

        payload = wire.build_payload(other, [system("s"), user("u")])

        assert payload["system"][0]["cache_control"] == _EPHEMERAL
        assert payload["messages"][0]["content"][-1]["cache_control"] == _EPHEMERAL

    def test_a_tool_result_may_carry_the_last_marker(self) -> None:
        messages = [
            user("x"),
            assistant("", [ToolCall("t1", "bash", "{}")]),
            tool_result(ToolCall("t1", "bash", "{}"), "o"),
        ]

        payload = wire.build_payload(_ENDPOINT, messages)

        assert payload["messages"][-1]["content"][-1]["cache_control"] == _EPHEMERAL

    def test_a_conversation_without_a_system_message_has_no_system_key(self) -> None:
        assert "system" not in wire.build_payload(_ENDPOINT, [user("u")])

    def test_encoding_the_same_conversation_twice_gives_the_same_bytes(self) -> None:
        first = json.dumps(wire.build_payload(_ENDPOINT, _conversation()))
        second = json.dumps(wire.build_payload(_ENDPOINT, _conversation()))

        assert first == second

    def test_a_tool_is_name_description_and_input_schema(self) -> None:
        bare = ToolSpec(name="verdict", description="d", parameters={})
        full = ToolSpec(name="read", description="r", parameters={"type": "object", "x": 1})

        payload = wire.build_payload(_ENDPOINT, [user("u")], [bare, full])

        assert payload["tools"] == [
            {
                "name": "verdict",
                "description": "d",
                "input_schema": {"type": "object", "properties": {}},
            },
            {"name": "read", "description": "r", "input_schema": {"type": "object", "x": 1}},
        ]

    def test_a_named_tool_choice_forces_that_tool_and_none_sends_no_key(self) -> None:
        tool = ToolSpec(name="verdict", description="d", parameters={})

        forced = wire.build_payload(_ENDPOINT, [user("u")], [tool], tool_choice="verdict")
        auto = wire.build_payload(_ENDPOINT, [user("u")], [tool])

        assert forced["tool_choice"] == {"type": "tool", "name": "verdict"}
        assert "tool_choice" not in auto

    def test_sampling_is_sent_only_when_declared(self) -> None:
        plain = wire.build_payload(_ENDPOINT, [user("u")])
        sampled = wire.build_payload(_ENDPOINT, [user("u")], temperature=0.5, top_p=0.9)

        assert "temperature" not in plain and "top_p" not in plain
        assert (sampled["temperature"], sampled["top_p"]) == (0.5, 0.9)

    def test_the_model_is_sent_and_streaming_is_not_asked_for(self) -> None:
        payload = wire.build_payload(_ENDPOINT, [user("u")])

        assert payload["model"] == "claude-haiku-4-5"
        assert "stream" not in payload


class TestMaxTokens:
    def test_the_requests_value_wins_over_the_endpoints_cap(self) -> None:
        payload = wire.build_payload(_ENDPOINT, [user("u")], max_tokens=300)

        assert payload["max_tokens"] == 300

    def test_the_endpoints_cap_is_the_fallback(self) -> None:
        assert wire.build_payload(_ENDPOINT, [user("u")])["max_tokens"] == 2048

    def test_with_neither_the_request_is_refused_naming_the_flag_and_the_model(self) -> None:
        bare = Endpoint(base_url="http://x/v1", model_id="claude-haiku-4-5", provider="anthropic")

        problem = wire.request_problem(bare, None)

        assert problem is not None
        assert "claude-haiku-4-5" in problem
        assert (
            "docket setup provider add anthropic --model claude-haiku-4-5 --max-tokens N" in problem
        )
        assert wire.request_problem(bare, 100) is None
        assert wire.request_problem(_ENDPOINT, None) is None

    def test_an_unknown_cap_is_never_filled_in_with_a_number(self) -> None:
        bare = Endpoint(base_url="http://x/v1", model_id="m")

        assert "max_tokens" not in wire.build_payload(bare, [user("u")])


class TestDecoding:
    def test_a_tool_use_body_gives_calls_whose_arguments_parse_back_to_the_input(self) -> None:
        data = _recorded("tool-use")

        got = wire.decode_response(data)

        recorded = data["content"][0]
        assert got.ok and got.finish_reason == "tool_calls"
        assert [(c.id, c.name) for c in got.message.tool_calls] == [(recorded["id"], "bash")]
        assert json.loads(got.message.tool_calls[0].arguments) == recorded["input"]
        assert got.message.content == ""

    def test_a_text_body_joins_its_blocks_and_ends_with_stop(self) -> None:
        got = wire.decode_response(_recorded("end-turn-cached"))

        assert got.ok and got.finish_reason == "stop"
        assert got.message.content.startswith("The files in the workspace are:")
        assert got.message.tool_calls == []

    def test_several_text_blocks_are_joined_in_order(self) -> None:
        data = {
            "content": [{"type": "text", "text": "a"}, {"type": "text", "text": "b"}],
            "stop_reason": "end_turn",
        }

        assert wire.decode_response(data).message.content == "ab"

    @pytest.mark.parametrize(
        ("stop_reason", "finish"),
        [
            ("tool_use", "tool_calls"),
            ("end_turn", "stop"),
            ("stop_sequence", "stop"),
            ("max_tokens", "length"),
            ("refusal", "refusal"),
        ],
    )
    def test_stop_reasons_map_and_an_unknown_one_is_kept(
        self, stop_reason: str, finish: str
    ) -> None:
        data = {"content": [{"type": "text", "text": "x"}], "stop_reason": stop_reason}

        assert wire.decode_response(data).finish_reason == finish

    def test_the_error_body_is_a_failed_response_carrying_the_message(self) -> None:
        got = wire.decode_response(_recorded("error-unknown-model"))

        assert not got.ok
        assert got.error == "model: claude-no-such-model"

    def test_a_body_without_content_is_a_failed_response(self) -> None:
        got = wire.decode_response({"stop_reason": "end_turn"})

        assert (got.ok, got.failure_kind) == (False, "invalid_output")


class TestUsage:
    def test_input_is_the_sum_of_the_three_fields_with_the_cache_counts_as_subsets(self) -> None:
        usage = wire.decode_response(_recorded("end-turn-cached")).usage

        assert (usage.input_tokens, usage.cached_tokens, usage.cache_write_tokens) == (
            6 + 8986 + 69,
            8986,
            69,
        )
        assert usage.output_tokens == 42

    def test_a_first_call_reports_its_creation_and_no_read(self) -> None:
        usage = wire.decode_response(_recorded("tool-use")).usage

        assert (usage.input_tokens, usage.cached_tokens, usage.cache_write_tokens) == (
            3 + 8986,
            0,
            8986,
        )
        assert usage.output_tokens == 52

    def test_a_missing_usage_is_zeros(self) -> None:
        data = {"content": [{"type": "text", "text": "x"}], "stop_reason": "end_turn"}

        assert wire.decode_response(data).usage.total_tokens == 0


class TestRoundTrip:
    def test_a_decoded_tool_use_encodes_to_the_same_block_in_the_next_request(self) -> None:
        data = _recorded("tool-use")
        reply = wire.decode_response(data).message

        payload = wire.build_payload(
            _ENDPOINT, [user("ls"), reply, tool_result(reply.tool_calls[0], "x")]
        )

        sent = payload["messages"][1]["content"][0]
        assert sent == {k: data["content"][0][k] for k in ("type", "id", "name", "input")}
        assert json.dumps(sent) == json.dumps(
            {k: data["content"][0][k] for k in ("type", "id", "name", "input")}
        )


class TestRequestBytes:
    def test_each_part_is_counted_where_it_travels(self) -> None:
        tool = ToolSpec(name="bash", description="d", parameters={})
        payload = wire.build_payload(_ENDPOINT, _conversation(), [tool])

        sizes = wire.request_part_bytes(payload)

        def size(part: Any) -> int:
            return len(json.dumps(part, ensure_ascii=False).encode())

        assert sizes["system"] == sum(size(b) for b in payload["system"])
        assert sizes["tools"] == size(payload["tools"][0])
        assert sizes["assistant"] == sum(size(b) for b in payload["messages"][1]["content"])
        results = payload["messages"][2]["content"]
        assert sizes["toolResults"] == sum(size(b) for b in results if b["type"] == "tool_result")
        assert sizes["user"] == size(payload["messages"][0]["content"][0]) + size(results[2])
