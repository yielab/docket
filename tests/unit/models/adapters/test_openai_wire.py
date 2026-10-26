"""The OpenAI-compatible adapter's `/models` limits and request bytes (`models/adapters/openai_http.py`).

The four recorded `/models` bodies under `tests/fixtures/provider-models/` are the oracle for the
per-row limits field map; no test here opens a socket.
"""

from __future__ import annotations

import json

from docket.agent.ports import Endpoint, user
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
