"""The OpenAI-compatible adapter's `/models` limits and request bytes (`models/adapters/openai_http.py`).

The four recorded `/models` bodies under `tests/fixtures/provider-models/` are the oracle for the
per-row limits field map; no test here opens a socket.
"""

from __future__ import annotations

import json

from docket.agent.ports import Endpoint, ToolSpec, system, user
from docket.models.adapters import openai_wire

SUBJECT = "docket.models.adapters.openai_wire"


class TestRequestBytes:
    def test_a_non_ascii_part_is_measured_as_utf8(self) -> None:
        text = "ñáé" * 100
        endpoint = Endpoint(base_url="http://127.0.0.1:1/v1", model_id="m")
        payload = openai_wire.build_payload(endpoint, [user(text)])
        measured = openai_wire.request_part_bytes(payload)["user"]
        assert measured == len(json.dumps(payload["messages"][0], ensure_ascii=False).encode())
        assert measured < len(json.dumps(payload["messages"][0]).encode())


class TestASummaryInTheHistory:
    def test_it_is_a_user_message_between_the_prompt_and_the_task(self) -> None:
        endpoint = Endpoint(base_url="http://127.0.0.1:1/v1", model_id="m")
        summary = user("[compacted summary of 2 earlier turn(s), 4 message(s)]\nwhat happened")

        payload = openai_wire.build_payload(
            endpoint, [system("the prompt"), summary, user("the task")]
        )

        assert [(m["role"], m["content"]) for m in payload["messages"]] == [
            ("system", "the prompt"),
            ("user", summary.content),
            ("user", "the task"),
        ]


class TestUsageDecoding:
    def test_cache_write_tokens_from_either_body_shape(self) -> None:
        openai_shape = {
            "choices": [{"message": {"content": "x"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "prompt_tokens_details": {"cache_write_tokens": 4}},
        }
        anthropic_shape = {
            "choices": [{"message": {"content": "x"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "cache_creation_input_tokens": 6},
        }
        assert openai_wire.decode_response(openai_shape).usage.cache_write_tokens == 4
        assert openai_wire.decode_response(anthropic_shape).usage.cache_write_tokens == 6


class TestSamplingAndToolChoice:
    _ENDPOINT = Endpoint(base_url="http://127.0.0.1:1/v1", model_id="m")
    _TOOL = ToolSpec(name="verdict", description="d", parameters={})

    def test_declared_sampling_is_sent(self) -> None:
        payload = openai_wire.build_payload(
            self._ENDPOINT, [user("hi")], temperature=0.7, top_p=0.8
        )

        assert payload["temperature"] == 0.7
        assert payload["top_p"] == 0.8

    def test_undeclared_sampling_sends_neither_key(self) -> None:
        payload = openai_wire.build_payload(self._ENDPOINT, [user("hi")], [self._TOOL])

        assert "temperature" not in payload
        assert "top_p" not in payload

    def test_tools_default_to_auto_choice(self) -> None:
        payload = openai_wire.build_payload(self._ENDPOINT, [user("hi")], [self._TOOL])

        assert payload["tool_choice"] == "auto"

    def test_a_named_choice_forces_that_function(self) -> None:
        payload = openai_wire.build_payload(
            self._ENDPOINT, [user("hi")], [self._TOOL], tool_choice="verdict"
        )

        assert payload["tool_choice"] == {"type": "function", "function": {"name": "verdict"}}

    def test_a_named_choice_without_tools_sends_no_choice(self) -> None:
        payload = openai_wire.build_payload(self._ENDPOINT, [user("hi")], tool_choice="verdict")

        assert "tool_choice" not in payload
