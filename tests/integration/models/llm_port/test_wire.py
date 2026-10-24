"""The chat-completion port: tool-call arguments and the wire encoding and decoding."""

from __future__ import annotations

import json
from typing import Any

import pytest
from tests.support.llm_port_harness import (
    ENDPOINT,
)

from docket.agent import ports
from docket.agent.ports import (
    Endpoint,
    TokenUsage,
    ToolCall,
    ToolCallArgumentsError,
    ToolSpec,
)
from docket.models.adapters import openai_http as adapter
from docket.models.adapters import openai_wire as _openai_wire

SUBJECT = "docket.models.adapters.openai_http"


class TestToolCallArguments:
    """The gate reads arguments; a caller that cannot read them must not run."""

    def test_object_arguments_parse(self) -> None:
        call = ToolCall(id="c1", name="bash", arguments='{"command": "ls"}')
        assert call.parsed_arguments() == {"command": "ls"}

    def test_blank_arguments_are_an_empty_object(self) -> None:
        assert ToolCall(id="c1", name="now", arguments="   ").parsed_arguments() == {}

    def test_invalid_json_raises_rather_than_defaulting_to_empty(self) -> None:
        call = ToolCall(id="c1", name="bash", arguments="{not json")
        with pytest.raises(ToolCallArgumentsError):
            call.parsed_arguments()

    @pytest.mark.parametrize("payload", ['["ls"]', '"ls"', "42"])
    def test_non_object_json_raises(self, payload: str) -> None:
        with pytest.raises(ToolCallArgumentsError):
            ToolCall(id="c1", name="bash", arguments=payload).parsed_arguments()


class TestMessageHelpers:
    def test_tool_result_is_addressed_to_its_call(self) -> None:
        call = ToolCall(id="call_7", name="read")
        msg = ports.tool_result(call, "file contents")
        assert (msg.role, msg.tool_call_id, msg.name) == ("tool", "call_7", "read")

    def test_assistant_may_carry_tool_calls_without_prose(self) -> None:
        msg = ports.assistant(tool_calls=[ToolCall(id="c1", name="bash")])
        assert msg.content == "" and len(msg.tool_calls) == 1

    def test_usage_totals(self) -> None:
        assert TokenUsage(input_tokens=10, output_tokens=5).total_tokens == 15

    def test_counted_tokens_exclude_cache_reads(self) -> None:
        usage = TokenUsage(input_tokens=30_000, output_tokens=40, cached_tokens=25_000)
        assert usage.counted_tokens == 5_040

    def test_counted_tokens_never_go_negative_on_an_inconsistent_report(self) -> None:
        assert TokenUsage(input_tokens=10, cached_tokens=50, output_tokens=0).counted_tokens == 0


class TestWireEncoding:
    def test_minimal_payload_shape(self) -> None:
        payload = _openai_wire.build_payload(ENDPOINT, [ports.user("hi")])
        assert payload["model"] == "test-model"
        assert payload["stream"] is False
        assert payload["messages"] == [{"role": "user", "content": "hi"}]

    def test_no_tools_key_when_no_tools_advertised(self) -> None:
        payload = _openai_wire.build_payload(ENDPOINT, [ports.user("hi")])
        assert "tools" not in payload and "tool_choice" not in payload

    def test_tools_are_wrapped_as_functions(self) -> None:
        spec = ToolSpec(
            name="bash",
            description="run a command",
            parameters={"type": "object", "properties": {"command": {"type": "string"}}},
        )
        payload = _openai_wire.build_payload(ENDPOINT, [ports.user("hi")], tools=[spec])
        assert payload["tool_choice"] == "auto"
        assert payload["tools"][0]["type"] == "function"
        assert payload["tools"][0]["function"]["name"] == "bash"
        assert payload["tools"][0]["function"]["parameters"]["properties"] == {
            "command": {"type": "string"}
        }

    def test_empty_schema_becomes_a_valid_object_schema(self) -> None:
        payload = _openai_wire.build_payload(
            ENDPOINT, [ports.user("hi")], tools=[ToolSpec(name="now", description="")]
        )
        assert payload["tools"][0]["function"]["parameters"] == {
            "type": "object",
            "properties": {},
        }

    def test_assistant_tool_call_replays_with_null_content(self) -> None:
        """A tool-calling assistant turn fed back as history must send
        `content: null`, not `""` — several endpoints reject the latter."""
        msg = ports.assistant(tool_calls=[ToolCall(id="c1", name="bash", arguments='{"a":1}')])
        encoded = _openai_wire.build_payload(ENDPOINT, [msg])["messages"][0]
        assert encoded["content"] is None
        assert encoded["tool_calls"] == [
            {"id": "c1", "type": "function", "function": {"name": "bash", "arguments": '{"a":1}'}}
        ]

    def test_tool_message_carries_its_call_id_and_keeps_empty_content(self) -> None:
        msg = ports.tool_result(ToolCall(id="c9", name="read"), "")
        encoded = _openai_wire.build_payload(ENDPOINT, [msg])["messages"][0]
        assert encoded == {"role": "tool", "content": "", "tool_call_id": "c9", "name": "read"}

    def test_optional_sampling_knobs_are_omitted_unless_set(self) -> None:
        bare = _openai_wire.build_payload(ENDPOINT, [ports.user("hi")])
        assert "max_tokens" not in bare and "temperature" not in bare
        full = _openai_wire.build_payload(
            ENDPOINT, [ports.user("hi")], max_tokens=64, temperature=0.2
        )
        assert full["max_tokens"] == 64 and full["temperature"] == 0.2

    def test_non_anthropic_payload_is_byte_identical_to_the_unmarked_encoding(self) -> None:
        """A model that is not Anthropic gets the plain string-content body."""
        spec = ToolSpec(name="bash", description="run", parameters={"type": "object"})
        call = ToolCall(id="c1", name="bash", arguments="{}")
        messages = [
            ports.system("sys"),
            ports.user("hi"),
            ports.assistant(tool_calls=[call]),
            ports.tool_result(call, "out"),
        ]
        for model_id in ("gpt-5", "openai/gpt-5", "qwen3", "x/not-claude-3", "clau"):
            endpoint = Endpoint(base_url="http://127.0.0.1:8081/v1", model_id=model_id)
            body = json.dumps(_openai_wire.build_payload(endpoint, messages, [spec], 64, 0.2))
            assert body == json.dumps(
                {
                    "model": model_id,
                    "messages": [
                        {"role": "system", "content": "sys"},
                        {"role": "user", "content": "hi"},
                        {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "c1",
                                    "type": "function",
                                    "function": {"name": "bash", "arguments": "{}"},
                                }
                            ],
                        },
                        {"role": "tool", "content": "out", "tool_call_id": "c1", "name": "bash"},
                    ],
                    "stream": False,
                    "tools": [
                        {
                            "type": "function",
                            "function": {
                                "name": "bash",
                                "description": "run",
                                "parameters": {"type": "object"},
                            },
                        }
                    ],
                    "tool_choice": "auto",
                    "max_tokens": 64,
                    "temperature": 0.2,
                }
            )

    @pytest.mark.parametrize("model_id", ["claude-sonnet-5-5", "anthropic/claude-opus-4"])
    def test_anthropic_request_marks_the_system_and_the_last_message(self, model_id: str) -> None:
        marker = {"type": "ephemeral"}
        call = ToolCall(id="c1", name="bash", arguments="{}")
        endpoint = Endpoint(base_url="http://127.0.0.1:8081/v1", model_id=model_id)
        messages = _openai_wire.build_payload(
            endpoint,
            [
                ports.system("sys"),
                ports.user("hi"),
                ports.assistant(tool_calls=[call]),
                ports.tool_result(call, "out"),
            ],
        )["messages"]
        assert messages[0]["content"] == [{"type": "text", "text": "sys", "cache_control": marker}]
        assert messages[1]["content"] == "hi"
        assert messages[2]["content"] is None
        assert messages[3]["content"] == [{"type": "text", "text": "out", "cache_control": marker}]
        assert messages[3]["tool_call_id"] == "c1" and messages[3]["name"] == "bash"
        assert json.dumps(messages).count("cache_control") == 2

    def test_anthropic_marker_skips_empty_content_and_never_doubles_up(self) -> None:
        endpoint = Endpoint(base_url="http://127.0.0.1:8081/v1", model_id="claude-haiku-4")
        alone = _openai_wire.build_payload(endpoint, [ports.system("sys")])["messages"]
        assert json.dumps(alone).count("cache_control") == 1
        call = ToolCall(id="c1", name="bash", arguments="{}")
        empty = _openai_wire.build_payload(
            endpoint, [ports.system("sys"), ports.tool_result(call, "")]
        )
        assert empty["messages"][1]["content"] == ""
        assert json.dumps(empty).count("cache_control") == 1

    def test_request_part_bytes_counts_the_marked_parts(self) -> None:
        plain = Endpoint(base_url="http://127.0.0.1:8081/v1", model_id="gpt-5")
        marked = Endpoint(base_url="http://127.0.0.1:8081/v1", model_id="claude-sonnet-5-5")
        messages = [ports.system("sys"), ports.user("hi")]
        before = _openai_wire.request_part_bytes(_openai_wire.build_payload(plain, messages))
        after = _openai_wire.request_part_bytes(_openai_wire.build_payload(marked, messages))
        assert after["system"] > before["system"]
        assert after["user"] > before["user"]

    def test_request_estimate_uses_wire_payload_and_accounts_for_tools(self) -> None:
        client = adapter.OpenAIChatClient(ENDPOINT)
        spec = ToolSpec(
            name="lookup",
            description="Look up a deliberately descriptive diagnostic value.",
            parameters={"type": "object", "properties": {"query": {"type": "string"}}},
        )

        bare = client.estimate_input_tokens([ports.user("hi")], max_tokens=64)
        with_tool = client.estimate_input_tokens([ports.user("hi")], tools=[spec], max_tokens=64)

        assert with_tool > bare


class TestWireDecoding:
    def test_plain_reply(self) -> None:
        res = _openai_wire.decode_response(
            {
                "choices": [
                    {"message": {"role": "assistant", "content": "hello"}, "finish_reason": "stop"}
                ],
                "usage": {"prompt_tokens": 12, "completion_tokens": 3},
            }
        )
        assert res.ok and res.message.content == "hello"
        assert res.finish_reason == "stop" and not res.truncated
        assert res.usage.input_tokens == 12 and res.usage.output_tokens == 3

    def test_tool_calls_are_decoded(self) -> None:
        res = _openai_wire.decode_response(
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_a",
                                    "type": "function",
                                    "function": {"name": "calc", "arguments": '{"expr": "17*23"}'},
                                }
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ]
            }
        )
        assert res.ok and len(res.tool_calls) == 1
        assert res.tool_calls[0].name == "calc"
        assert res.tool_calls[0].parsed_arguments() == {"expr": "17*23"}

    def test_dict_arguments_are_re_encoded_to_the_documented_string(self) -> None:
        """llama.cpp can emit already-decoded arguments; ToolCall.arguments is
        contractually the raw JSON *text*, so the adapter re-encodes."""
        res = _openai_wire.decode_response(
            {
                "choices": [
                    {
                        "message": {
                            "tool_calls": [
                                {
                                    "id": "c1",
                                    "function": {"name": "calc", "arguments": {"expr": "1+1"}},
                                }
                            ]
                        }
                    }
                ]
            }
        )
        assert isinstance(res.tool_calls[0].arguments, str)
        assert res.tool_calls[0].parsed_arguments() == {"expr": "1+1"}

    def test_missing_call_id_is_synthesised_not_dropped(self) -> None:
        res = _openai_wire.decode_response(
            {"choices": [{"message": {"tool_calls": [{"function": {"name": "calc"}}]}}]}
        )
        assert len(res.tool_calls) == 1 and res.tool_calls[0].id == "call_0"

    def test_malformed_call_survives_decoding_so_the_gate_can_refuse_it(self) -> None:
        """Dropping an unnamed call here would hide it from pre_tool_call and
        from the audit log. It must reach the dispatcher to be refused."""
        res = _openai_wire.decode_response(
            {"choices": [{"message": {"tool_calls": [{"id": "x", "function": {}}]}}]}
        )
        assert len(res.tool_calls) == 1 and res.tool_calls[0].name == ""

    def test_cached_prompt_tokens_when_reported(self) -> None:
        res = _openai_wire.decode_response(
            {
                "choices": [{"message": {"content": "ok"}}],
                "usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 2,
                    "prompt_tokens_details": {"cached_tokens": 80},
                },
            }
        )
        assert res.usage.cached_tokens == 80

    @pytest.mark.parametrize(
        "usage",
        [
            {"prompt_tokens_details": {"cached_tokens": 80, "cache_write_tokens": 15}},
            {"prompt_tokens_details": {"cached_tokens": 80}, "cache_creation_input_tokens": 15},
        ],
    )
    def test_cache_writes_when_reported(self, usage: dict[str, Any]) -> None:
        res = _openai_wire.decode_response(
            {
                "choices": [{"message": {"content": "ok"}}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 2, **usage},
            }
        )
        assert res.usage.cache_write_tokens == 15
        assert res.usage.counted_tokens == 100 - 80 + 2

    def test_cache_writes_default_to_zero(self) -> None:
        res = _openai_wire.decode_response(
            {"choices": [{"message": {"content": "ok"}}], "usage": {"prompt_tokens": 9}}
        )
        assert res.usage.cache_write_tokens == 0

    def test_length_finish_reason_marks_truncation(self) -> None:
        res = _openai_wire.decode_response(
            {"choices": [{"message": {"content": "partial"}, "finish_reason": "length"}]}
        )
        assert res.truncated is True

    def test_no_choices_is_invalid_output(self) -> None:
        res = _openai_wire.decode_response({"id": "x"})
        assert not res.ok and res.failure_kind == "invalid_output"

    def test_error_object_in_a_200_body_is_invalid_output(self) -> None:
        res = _openai_wire.decode_response({"error": {"message": "model not found"}})
        assert not res.ok and "model not found" in res.error

    def test_gateway_choice_error_in_a_200_body_is_retryable_by_status(self) -> None:
        res = _openai_wire.decode_response(
            {
                "choices": [
                    {
                        "message": {"role": "assistant", "content": ""},
                        "finish_reason": "error",
                        "error": {"code": 429, "message": "upstream rate limited"},
                    }
                ]
            }
        )

        assert res.ok is False
        assert res.failure_kind == "daemon_error"
        assert "upstream rate limited" in res.error

    def test_gateway_error_finish_without_detail_is_not_empty_success(self) -> None:
        res = _openai_wire.decode_response(
            {
                "choices": [
                    {
                        "message": {"role": "assistant", "content": ""},
                        "finish_reason": "error",
                    }
                ]
            }
        )

        assert res.ok is False
        assert res.failure_kind == "invalid_output"
        assert "finish_reason" in res.error
