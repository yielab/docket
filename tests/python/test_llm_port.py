"""The chat-completion port and its OpenAI-compatible adapter.

Everything here runs without a network. The transport tests monkeypatch
``urlopen`` inside the adapter's namespace; the encode/decode tests call
``build_payload``/``decode_response`` directly, which is why those two are
public functions rather than private helpers — the wire shape is the part most
likely to break against a real server, so it is the part worth pinning.
"""

from __future__ import annotations

import io
import json
import urllib.error
from typing import Any

import pytest

from docket.core import llm
from docket.core.dispatch import _RETRYABLE_FAILURE_KINDS
from docket.core.llm import (
    ChatBackend,
    ChatMessage,
    Endpoint,
    TokenUsage,
    ToolCall,
    ToolCallArgumentsError,
    ToolSpec,
)
from docket.edges.adapters import llm as adapter

ENDPOINT = Endpoint(base_url="http://127.0.0.1:8081/v1", model_id="test-model")


def _http_error(code: int, body: str = "") -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        "http://127.0.0.1:8081/v1/chat/completions",
        code,
        "err",
        {},  # type: ignore[arg-type]
        io.BytesIO(body.encode()),
    )


def _stub_urlopen(monkeypatch: pytest.MonkeyPatch, body: str, captured: dict[str, Any]) -> None:
    """Replace the adapter's urlopen with one that records the request."""

    class _Resp:
        def read(self) -> bytes:
            return body.encode()

        def __enter__(self) -> _Resp:
            return self

        def __exit__(self, *exc: object) -> None:
            return None

    def _fake(request: Any, timeout: int = 0) -> _Resp:
        captured["url"] = request.full_url
        captured["headers"] = dict(request.headers)
        captured["timeout"] = timeout
        captured["payload"] = json.loads(request.data.decode())
        return _Resp()

    monkeypatch.setattr(adapter.urllib.request, "urlopen", _fake)


def _raising_urlopen(monkeypatch: pytest.MonkeyPatch, exc: BaseException) -> None:
    def _fake(request: Any, timeout: int = 0) -> Any:
        raise exc

    monkeypatch.setattr(adapter.urllib.request, "urlopen", _fake)


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
        msg = llm.tool_result(call, "file contents")
        assert (msg.role, msg.tool_call_id, msg.name) == ("tool", "call_7", "read")

    def test_assistant_may_carry_tool_calls_without_prose(self) -> None:
        msg = llm.assistant(tool_calls=[ToolCall(id="c1", name="bash")])
        assert msg.content == "" and len(msg.tool_calls) == 1

    def test_usage_totals(self) -> None:
        assert TokenUsage(input_tokens=10, output_tokens=5).total_tokens == 15


class TestWireEncoding:
    def test_minimal_payload_shape(self) -> None:
        payload = adapter.build_payload(ENDPOINT, [llm.user("hi")])
        assert payload["model"] == "test-model"
        assert payload["stream"] is False
        assert payload["messages"] == [{"role": "user", "content": "hi"}]

    def test_no_tools_key_when_no_tools_advertised(self) -> None:
        payload = adapter.build_payload(ENDPOINT, [llm.user("hi")])
        assert "tools" not in payload and "tool_choice" not in payload

    def test_tools_are_wrapped_as_functions(self) -> None:
        spec = ToolSpec(
            name="bash",
            description="run a command",
            parameters={"type": "object", "properties": {"command": {"type": "string"}}},
        )
        payload = adapter.build_payload(ENDPOINT, [llm.user("hi")], tools=[spec])
        assert payload["tool_choice"] == "auto"
        assert payload["tools"][0]["type"] == "function"
        assert payload["tools"][0]["function"]["name"] == "bash"
        assert payload["tools"][0]["function"]["parameters"]["properties"] == {
            "command": {"type": "string"}
        }

    def test_empty_schema_becomes_a_valid_object_schema(self) -> None:
        payload = adapter.build_payload(
            ENDPOINT, [llm.user("hi")], tools=[ToolSpec(name="now", description="")]
        )
        assert payload["tools"][0]["function"]["parameters"] == {
            "type": "object",
            "properties": {},
        }

    def test_assistant_tool_call_replays_with_null_content(self) -> None:
        """A tool-calling assistant turn fed back as history must send
        `content: null`, not `""` — several endpoints reject the latter."""
        msg = llm.assistant(tool_calls=[ToolCall(id="c1", name="bash", arguments='{"a":1}')])
        encoded = adapter.build_payload(ENDPOINT, [msg])["messages"][0]
        assert encoded["content"] is None
        assert encoded["tool_calls"] == [
            {"id": "c1", "type": "function", "function": {"name": "bash", "arguments": '{"a":1}'}}
        ]

    def test_tool_message_carries_its_call_id_and_keeps_empty_content(self) -> None:
        msg = llm.tool_result(ToolCall(id="c9", name="read"), "")
        encoded = adapter.build_payload(ENDPOINT, [msg])["messages"][0]
        assert encoded == {"role": "tool", "content": "", "tool_call_id": "c9", "name": "read"}

    def test_optional_sampling_knobs_are_omitted_unless_set(self) -> None:
        bare = adapter.build_payload(ENDPOINT, [llm.user("hi")])
        assert "max_tokens" not in bare and "temperature" not in bare
        full = adapter.build_payload(ENDPOINT, [llm.user("hi")], max_tokens=64, temperature=0.2)
        assert full["max_tokens"] == 64 and full["temperature"] == 0.2


class TestWireDecoding:
    def test_plain_reply(self) -> None:
        res = adapter.decode_response(
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
        res = adapter.decode_response(
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
        res = adapter.decode_response(
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
        res = adapter.decode_response(
            {"choices": [{"message": {"tool_calls": [{"function": {"name": "calc"}}]}}]}
        )
        assert len(res.tool_calls) == 1 and res.tool_calls[0].id == "call_0"

    def test_malformed_call_survives_decoding_so_the_gate_can_refuse_it(self) -> None:
        """Dropping an unnamed call here would hide it from pre_tool_call and
        from the audit log. It must reach the dispatcher to be refused."""
        res = adapter.decode_response(
            {"choices": [{"message": {"tool_calls": [{"id": "x", "function": {}}]}}]}
        )
        assert len(res.tool_calls) == 1 and res.tool_calls[0].name == ""

    def test_cached_prompt_tokens_when_reported(self) -> None:
        res = adapter.decode_response(
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

    def test_length_finish_reason_marks_truncation(self) -> None:
        res = adapter.decode_response(
            {"choices": [{"message": {"content": "partial"}, "finish_reason": "length"}]}
        )
        assert res.truncated is True

    def test_no_choices_is_invalid_output(self) -> None:
        res = adapter.decode_response({"id": "x"})
        assert not res.ok and res.failure_kind == "invalid_output"

    def test_error_object_in_a_200_body_is_invalid_output(self) -> None:
        res = adapter.decode_response({"error": {"message": "model not found"}})
        assert not res.ok and "model not found" in res.error


class TestTransport:
    def test_successful_post_shape(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, Any] = {}
        _stub_urlopen(
            monkeypatch, json.dumps({"choices": [{"message": {"content": "hi"}}]}), captured
        )
        res = adapter.OpenAIChatClient(ENDPOINT).complete([llm.user("yo")], timeout=30)
        assert res.ok and res.message.content == "hi"
        assert captured["url"] == "http://127.0.0.1:8081/v1/chat/completions"
        assert captured["timeout"] == 30
        assert captured["payload"]["messages"][0]["content"] == "yo"

    def test_no_auth_header_without_a_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, Any] = {}
        _stub_urlopen(monkeypatch, '{"choices": [{"message": {"content": "x"}}]}', captured)
        adapter.OpenAIChatClient(ENDPOINT).complete([llm.user("yo")])
        assert not any(k.lower() == "authorization" for k in captured["headers"])

    def test_bearer_header_when_a_key_is_present(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, Any] = {}
        _stub_urlopen(monkeypatch, '{"choices": [{"message": {"content": "x"}}]}', captured)
        client = adapter.OpenAIChatClient(
            Endpoint(base_url="https://api.example/v1", model_id="m", api_key="sk-secret")
        )
        client.complete([llm.user("yo")])
        headers = {k.lower(): v for k, v in captured["headers"].items()}
        assert headers["authorization"] == "Bearer sk-secret"

    def test_unconfigured_endpoint_fails_without_posting(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _raising_urlopen(monkeypatch, AssertionError("must not POST"))
        res = adapter.OpenAIChatClient(Endpoint(base_url="", model_id="m")).complete(
            [llm.user("x")]
        )
        assert not res.ok and "no endpoint configured" in res.error

    @pytest.mark.parametrize(
        ("status", "expected"),
        [
            (429, "daemon_error"),
            (503, "daemon_error"),
            (400, "nonzero_exit"),
            (401, "nonzero_exit"),
        ],
    )
    def test_http_status_classification(
        self, monkeypatch: pytest.MonkeyPatch, status: int, expected: str
    ) -> None:
        _raising_urlopen(monkeypatch, _http_error(status, '{"error":{"message":"nope"}}'))
        res = adapter.OpenAIChatClient(ENDPOINT).complete([llm.user("x")])
        assert not res.ok and res.failure_kind == expected

    def test_error_body_is_surfaced(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _raising_urlopen(monkeypatch, _http_error(400, "context length exceeded"))
        res = adapter.OpenAIChatClient(ENDPOINT).complete([llm.user("x")])
        assert "context length exceeded" in res.error

    def test_timeout_is_classified_as_timeout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _raising_urlopen(monkeypatch, TimeoutError("timed out"))
        res = adapter.OpenAIChatClient(ENDPOINT).complete([llm.user("x")], timeout=7)
        assert res.failure_kind == "timeout" and "7s" in res.error

    def test_timeout_wrapped_in_urlerror_is_still_a_timeout(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _raising_urlopen(monkeypatch, urllib.error.URLError(TimeoutError("timed out")))
        res = adapter.OpenAIChatClient(ENDPOINT).complete([llm.user("x")])
        assert res.failure_kind == "timeout"

    def test_unreachable_endpoint_is_retryable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _raising_urlopen(monkeypatch, urllib.error.URLError(ConnectionRefusedError(111, "refused")))
        res = adapter.OpenAIChatClient(ENDPOINT).complete([llm.user("x")])
        assert res.failure_kind == "daemon_error"
        assert res.failure_kind in _RETRYABLE_FAILURE_KINDS

    def test_non_json_body_is_invalid_output(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, Any] = {}
        _stub_urlopen(monkeypatch, "<html>502 Bad Gateway</html>", captured)
        res = adapter.OpenAIChatClient(ENDPOINT).complete([llm.user("x")])
        assert not res.ok and res.failure_kind == "invalid_output"

    def test_no_ordinary_failure_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The port's contract: transport problems come back as data."""
        for exc in (
            _http_error(500),
            TimeoutError(),
            urllib.error.URLError("down"),
            OSError("socket exploded"),
        ):
            _raising_urlopen(monkeypatch, exc)
            res = adapter.OpenAIChatClient(ENDPOINT).complete([llm.user("x")])
            assert res.ok is False and res.failure_kind is not None


class TestRetryVocabularyStaysAlignedWithDispatch:
    """This backend slots under the existing dispatch state machine, so the
    failure kinds it emits have to mean the same thing there."""

    def test_transport_failures_are_retryable_and_answers_are_not(self) -> None:
        assert adapter._classify_http_status(429) in _RETRYABLE_FAILURE_KINDS
        assert adapter._classify_http_status(400) not in _RETRYABLE_FAILURE_KINDS

    def test_every_status_maps_to_a_known_failure_kind(self) -> None:
        known = {"timeout", "daemon_error", "nonzero_exit", "invalid_output"}
        for status in (400, 401, 404, 408, 422, 429, 500, 502, 503, 504):
            assert adapter._classify_http_status(status) in known


class TestEndpointResolution:
    def test_env_override_wins_and_short_circuits_stored_config(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DOCKET_LLM_BASE_URL", "http://127.0.0.1:9999/v1")
        monkeypatch.setenv("DOCKET_LLM_API_KEY", "sk-env")
        ep = adapter.resolve_endpoint("anything/some-model")
        assert ep is not None
        assert ep.base_url == "http://127.0.0.1:9999/v1"
        assert ep.api_key == "sk-env"
        assert ep.model_id == "some-model"

    def test_stored_provider_block(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("DOCKET_LLM_BASE_URL", raising=False)
        monkeypatch.delenv("DOCKET_LLM_API_KEY", raising=False)
        from docket.core import fleet as _fleet

        monkeypatch.setattr(
            _fleet, "get_local_provider", lambda name: {"baseUrl": "http://127.0.0.1:8081/v1"}
        )
        ep = adapter.resolve_endpoint("local/qwen3.6-35b-a3b")
        assert ep is not None
        assert ep.base_url == "http://127.0.0.1:8081/v1"
        assert ep.model_id == "qwen3.6-35b-a3b"
        assert ep.provider == "local"
        assert ep.is_local is True

    def test_placeholder_local_key_is_not_sent_as_a_credential(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("DOCKET_LLM_BASE_URL", raising=False)
        monkeypatch.delenv("DOCKET_LLM_API_KEY", raising=False)
        from docket.core import fleet as _fleet

        monkeypatch.setattr(
            _fleet,
            "get_local_provider",
            lambda name: {"baseUrl": "http://127.0.0.1:8081/v1", "apiKey": "local"},
        )
        ep = adapter.resolve_endpoint("local/m")
        assert ep is not None and ep.api_key == ""

    def test_provider_named_env_var_fallback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("DOCKET_LLM_BASE_URL", raising=False)
        monkeypatch.delenv("DOCKET_LLM_API_KEY", raising=False)
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or")
        from docket.core import fleet as _fleet

        monkeypatch.setattr(
            _fleet, "get_local_provider", lambda name: {"baseUrl": "https://openrouter.ai/api/v1"}
        )
        ep = adapter.resolve_endpoint("openrouter/some-model")
        assert ep is not None and ep.api_key == "sk-or"

    def test_unknown_provider_resolves_to_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("DOCKET_LLM_BASE_URL", raising=False)
        from docket.core import fleet as _fleet

        monkeypatch.setattr(_fleet, "get_local_provider", lambda name: None)
        assert adapter.resolve_endpoint("nosuch/model") is None
        assert adapter.client_for("nosuch/model") is None

    def test_client_for_builds_a_usable_client(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DOCKET_LLM_BASE_URL", "http://127.0.0.1:9999/v1")
        client = adapter.client_for("local/m")
        assert client is not None
        assert client.url == "http://127.0.0.1:9999/v1/chat/completions"


class TestProtocolConformance:
    def test_the_shipped_client_satisfies_the_port(self) -> None:
        assert isinstance(adapter.OpenAIChatClient(ENDPOINT), ChatBackend)

    def test_core_llm_holds_no_wire_knowledge(self) -> None:
        """The port must stay format-free — a wire field name appearing in
        core/llm.py means translation has leaked out of the adapter.

        Checks **executable string literals only**, via the AST: docstrings and
        comments are excluded, because the module legitimately *describes* the
        protocol it is a port for. A plain substring scan over the source flags
        that prose and would have to be weakened until it caught nothing.
        """
        import ast
        from pathlib import Path

        tree = ast.parse(Path(llm.__file__).read_text())
        docstrings: set[int] = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef):
                continue
            first = node.body[0] if node.body else None
            if (
                isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)
            ):
                docstrings.add(id(first.value))

        literals = [
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in docstrings
        ]
        wire_vocabulary = (
            "chat/completions",
            "prompt_tokens",
            "completion_tokens",
            "tool_choice",
            "finish_reason",
            "baseUrl",
            "Bearer",
        )
        leaked = [(word, text) for text in literals for word in wire_vocabulary if word in text]
        assert not leaked, f"wire vocabulary leaked into core/llm.py: {leaked}"

    def test_message_roles_are_the_four_the_protocol_defines(self) -> None:
        msgs = [
            llm.system("s"),
            llm.user("u"),
            llm.assistant("a"),
            llm.tool_result(ToolCall("i", "n"), "r"),
        ]
        assert [m.role for m in msgs] == ["system", "user", "assistant", "tool"]
        assert all(isinstance(m, ChatMessage) for m in msgs)
