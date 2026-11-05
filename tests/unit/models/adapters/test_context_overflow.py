"""Recognizing a provider's context-overflow refusal (`models/adapters/context_overflow.py`).

The llama.cpp body is the one the local endpoint answered a 150,000-character prompt with; the
OpenAI and Anthropic bodies are the shapes their documentation gives. No test opens a socket.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from docket.models.adapters.context_overflow import ContextOverflow, detect

SUBJECT = "docket.models.adapters.context_overflow"

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "provider-errors"


def _body(name: str) -> str:
    return (FIXTURES / f"{name}.json").read_text(encoding="utf-8").strip()


class TestRecognized:
    @pytest.mark.parametrize(
        ("fixture", "tokens"),
        [
            ("llamacpp-exceed-context", 98915),
            ("openai-context-length-exceeded", 130123),
            ("anthropic-prompt-too-long", 208000),
        ],
    )
    def test_a_recorded_refusal_carries_the_providers_own_count(
        self, fixture: str, tokens: int
    ) -> None:
        assert detect(400, _body(fixture)) == ContextOverflow(input_tokens=tokens)

    def test_the_structured_count_wins_over_the_message_text(self) -> None:
        body = json.loads(_body("llamacpp-exceed-context"))
        body["error"]["message"] = "request (5 tokens) exceeds the available context size"
        assert detect(400, json.dumps(body)) == ContextOverflow(input_tokens=98915)

    def test_the_window_in_the_message_is_not_taken_for_the_count(self) -> None:
        body = '{"error":{"code":"context_length_exceeded","message":"maximum context length is 128000 tokens"}}'
        assert detect(400, body) == ContextOverflow(input_tokens=None)

    def test_a_structured_refusal_without_a_count_is_still_a_refusal(self) -> None:
        body = '{"error":{"code":400,"message":"too big","type":"exceed_context_size_error"}}'
        assert detect(400, body) == ContextOverflow(input_tokens=None)

    def test_a_refusal_known_only_by_its_text_is_recognized(self) -> None:
        body = '{"error":{"message":"prompt is too long: 4096 tokens > 2048 maximum"}}'
        assert detect(400, body) == ContextOverflow(input_tokens=4096)


class TestNotRecognized:
    @pytest.mark.parametrize("status", [200, 401, 404, 429, 500, 503])
    def test_a_status_that_is_not_a_bad_request_is_never_an_overflow(self, status: int) -> None:
        assert detect(status, _body("llamacpp-exceed-context")) is None

    @pytest.mark.parametrize(
        "body",
        [
            _body("anthropic-invalid-request"),
            '{"error":{"message":"nope"}}',
            '{"error":{"code":400,"message":"bad json","type":"invalid_request_error"}}',
            "context length exceeded",
            "",
            "[1, 2]",
            '{"error":"a string"}',
        ],
    )
    def test_any_other_bad_request_keeps_its_ordinary_classification(self, body: str) -> None:
        assert detect(400, body) is None
