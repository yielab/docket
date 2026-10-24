"""The chat-completion port: transport, latency, endpoint resolution and protocol conformance."""

from __future__ import annotations

import io
import json
import time
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from typing import Any

import pytest
from tests.support.llm_port_harness import (
    ENDPOINT,
)

from docket.agent import ports
from docket.agent.ports import (
    ChatBackend,
    ChatMessage,
    Endpoint,
    ToolCall,
)
from docket.hops.application.runner import _RETRYABLE_FAILURE_KINDS
from docket.kernel.home import Home, use_home
from docket.models.adapters import openai_http as adapter
from docket.models.adapters import openai_wire as _openai_wire

SUBJECT = "docket.models.adapters.openai_http"


def _http_error(
    code: int, body: str = "", headers: dict[str, str] | None = None
) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        "http://127.0.0.1:8081/v1/chat/completions",
        code,
        "err",
        headers or {},  # type: ignore[arg-type]
        io.BytesIO(body.encode()),
    )


def _stub_urlopen(monkeypatch: pytest.MonkeyPatch, body: str, captured: dict[str, Any]) -> None:
    """Replace the adapter's open_same_origin with one that records the request."""

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

    monkeypatch.setattr(adapter, "open_same_origin", _fake)


def _raising_urlopen(monkeypatch: pytest.MonkeyPatch, exc: BaseException) -> None:
    def _fake(request: Any, timeout: int = 0) -> Any:
        raise exc

    monkeypatch.setattr(adapter, "open_same_origin", _fake)


def _register_provider(
    name: str,
    base_url: str,
    *,
    local: bool = False,
    credentials: tuple[str, ...] = (),
    models: list[dict[str, object]] | None = None,
) -> None:
    """Write *name* into the isolated global provider catalog (docket-providers.json),
    the document-shaped replacement for monkeypatching ``fleet.get_local_provider``."""
    from docket.models import catalog as _prov

    spec = _prov.ProviderSpec(
        name=name,
        baseUrl=base_url,
        auth=_prov.AuthSpec(type="none" if local else "bearer", credentials=list(credentials)),
        local=local,
        models=[_prov.ModelRow(**row) for row in (models or [])],
    )
    _prov.save_provider(spec)


class TestTransport:
    def test_successful_post_shape(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, Any] = {}
        _stub_urlopen(
            monkeypatch, json.dumps({"choices": [{"message": {"content": "hi"}}]}), captured
        )
        res = adapter.OpenAIChatClient(ENDPOINT).complete([ports.user("yo")], timeout=30)
        assert res.ok and res.message.content == "hi"
        assert captured["url"] == "http://127.0.0.1:8081/v1/chat/completions"
        assert captured["timeout"] == 30
        assert captured["payload"]["messages"][0]["content"] == "yo"

    def test_no_auth_header_without_a_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, Any] = {}
        _stub_urlopen(monkeypatch, '{"choices": [{"message": {"content": "x"}}]}', captured)
        adapter.OpenAIChatClient(ENDPOINT).complete([ports.user("yo")])
        assert not any(k.lower() == "authorization" for k in captured["headers"])

    def test_bearer_header_when_a_key_is_present(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, Any] = {}
        _stub_urlopen(monkeypatch, '{"choices": [{"message": {"content": "x"}}]}', captured)
        client = adapter.OpenAIChatClient(
            Endpoint(base_url="https://api.example/v1", model_id="m", api_key="sk-secret")
        )
        client.complete([ports.user("yo")])
        headers = {k.lower(): v for k, v in captured["headers"].items()}
        assert headers["authorization"] == "Bearer sk-secret"

    def test_header_auth_and_static_headers_reach_the_wire(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Azure-style ``api-key`` header auth plus a static header, resolved from a
        catalog document end to end -- no ``Authorization`` header is sent."""
        from docket.models import catalog as _prov

        monkeypatch.delenv("DOCKET_LLM_BASE_URL", raising=False)
        monkeypatch.delenv("DOCKET_LLM_API_KEY", raising=False)
        monkeypatch.setenv("AZURE_KEY", "k")
        _prov.save_provider(
            _prov.ProviderSpec(
                name="azure",
                baseUrl="https://example.com/v1",
                auth=_prov.AuthSpec(type="header", header="api-key", credentials=["AZURE_KEY"]),
                headers={"x-title": "docket"},
            )
        )
        ep = adapter.resolve_endpoint("azure/gpt-4")
        assert ep is not None

        captured: dict[str, Any] = {}
        _stub_urlopen(monkeypatch, '{"choices": [{"message": {"content": "x"}}]}', captured)
        adapter.OpenAIChatClient(ep).complete([ports.user("yo")])
        headers = {k.lower(): v for k, v in captured["headers"].items()}
        assert headers["api-key"] == "k"
        assert headers["x-title"] == "docket"
        assert "authorization" not in headers

    def test_unconfigured_endpoint_fails_without_posting(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _raising_urlopen(monkeypatch, AssertionError("must not POST"))
        res = adapter.OpenAIChatClient(Endpoint(base_url="", model_id="m")).complete(
            [ports.user("x")]
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
        res = adapter.OpenAIChatClient(ENDPOINT).complete([ports.user("x")])
        assert not res.ok and res.failure_kind == expected

    def test_retry_after_is_parsed_only_on_a_retryable_status(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _raising_urlopen(monkeypatch, _http_error(429, headers={"Retry-After": "7"}))
        res = adapter.OpenAIChatClient(ENDPOINT).complete([ports.user("x")])
        assert res.failure_kind == "daemon_error"
        assert res.retry_after_s == 7.0

        _raising_urlopen(monkeypatch, _http_error(400, headers={"Retry-After": "7"}))
        res = adapter.OpenAIChatClient(ENDPOINT).complete([ports.user("x")])
        assert res.failure_kind == "nonzero_exit"
        assert res.retry_after_s is None

    def test_error_body_is_surfaced(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _raising_urlopen(monkeypatch, _http_error(400, "context length exceeded"))
        res = adapter.OpenAIChatClient(ENDPOINT).complete([ports.user("x")])
        assert "context length exceeded" in res.error

    def test_timeout_is_classified_as_timeout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _raising_urlopen(monkeypatch, TimeoutError("timed out"))
        res = adapter.OpenAIChatClient(ENDPOINT).complete([ports.user("x")], timeout=7)
        assert res.failure_kind == "timeout" and "7s" in res.error

    def test_timeout_wrapped_in_urlerror_is_still_a_timeout(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _raising_urlopen(monkeypatch, urllib.error.URLError(TimeoutError("timed out")))
        res = adapter.OpenAIChatClient(ENDPOINT).complete([ports.user("x")])
        assert res.failure_kind == "timeout"

    def test_unreachable_endpoint_is_retryable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _raising_urlopen(monkeypatch, urllib.error.URLError(ConnectionRefusedError(111, "refused")))
        res = adapter.OpenAIChatClient(ENDPOINT).complete([ports.user("x")])
        assert res.failure_kind == "daemon_error"
        assert res.failure_kind in _RETRYABLE_FAILURE_KINDS

    def test_non_json_body_is_invalid_output(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, Any] = {}
        _stub_urlopen(monkeypatch, "<html>502 Bad Gateway</html>", captured)
        res = adapter.OpenAIChatClient(ENDPOINT).complete([ports.user("x")])
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
            res = adapter.OpenAIChatClient(ENDPOINT).complete([ports.user("x")])
            assert res.ok is False and res.failure_kind is not None


class TestLatencyMeasurement:
    """``latency_ms``/``model``/``provider`` are stamped by ``complete()`` on every return
    path, over a real socket (a monkeypatched ``urlopen`` returns instantly, which can't
    prove a measurement)."""

    def test_a_slow_response_measures_at_least_its_own_delay(self) -> None:
        body = json.dumps({"choices": [{"message": {"content": "hi"}}]}).encode()

        class _SlowHandler(BaseHTTPRequestHandler):
            def log_message(self, *_args: object) -> None:  # quiet the test output
                pass

            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", "0"))
                self.rfile.read(length)
                time.sleep(0.05)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        srv = ThreadingHTTPServer(("127.0.0.1", 0), _SlowHandler)
        thread = Thread(target=srv.serve_forever, daemon=True)
        thread.start()
        try:
            endpoint = Endpoint(
                base_url=f"http://127.0.0.1:{srv.server_address[1]}/v1",
                model_id="local-model",
                provider="local",
            )
            res = adapter.OpenAIChatClient(endpoint).complete([ports.user("hi")], timeout=5)
        finally:
            srv.shutdown()
            thread.join(timeout=5)

        assert res.ok
        assert res.model == "local-model"
        assert res.provider == "local"
        assert res.latency_ms >= 50

    def test_a_closed_port_still_reports_a_non_negative_latency(self) -> None:
        endpoint = Endpoint(base_url="http://127.0.0.1:1/v1", model_id="local-model")
        res = adapter.OpenAIChatClient(endpoint).complete([ports.user("hi")], timeout=5)
        assert res.ok is False
        assert res.latency_ms >= 0


class TestRetryVocabularyStaysAlignedWithDispatch:
    """This backend slots under the existing dispatch state machine, so the
    failure kinds it emits have to mean the same thing there."""

    def test_transport_failures_are_retryable_and_answers_are_not(self) -> None:
        assert _openai_wire._classify_http_status(429) in _RETRYABLE_FAILURE_KINDS
        assert _openai_wire._classify_http_status(400) not in _RETRYABLE_FAILURE_KINDS

    def test_every_status_maps_to_a_known_failure_kind(self) -> None:
        known = {"timeout", "daemon_error", "nonzero_exit", "invalid_output"}
        for status in (400, 401, 404, 408, 422, 429, 500, 502, 503, 504):
            assert _openai_wire._classify_http_status(status) in known


class TestEndpointResolution:
    def test_stored_keys_enable_both_hosted_gateways_without_global_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("DOCKET_LLM_BASE_URL", raising=False)
        monkeypatch.delenv("DOCKET_LLM_API_KEY", raising=False)
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        monkeypatch.delenv("AI_GATEWAY_API_KEY", raising=False)
        monkeypatch.delenv("VERCEL_OIDC_TOKEN", raising=False)

        from docket.interfaces.cli.commands import setup_model as _setup_model
        from docket.interfaces.cli.commands import (
            setup_model_credentials as _setup_model_credentials,
        )

        with use_home(Home(tmp_path)):
            monkeypatch.setattr(_setup_model, "audit_log", lambda *args: None)

            assert _setup_model_credentials._write_credential(
                "OPENROUTER_API_KEY", "sk-or-stored", "add"
            )
            assert _setup_model_credentials._write_credential(
                "AI_GATEWAY_API_KEY", "vercel-stored", "add"
            )

            openrouter = adapter.resolve_endpoint("openrouter/anthropic/claude-sonnet-4.6")
            gateway = adapter.resolve_endpoint("ai-gateway/anthropic/claude-sonnet-4.6")

            assert openrouter is not None
            assert openrouter.base_url == "https://openrouter.ai/api/v1"
            assert openrouter.model_id == "anthropic/claude-sonnet-4.6"
            assert openrouter.api_key == "sk-or-stored"
            assert gateway is not None
            assert gateway.base_url == "https://ai-gateway.vercel.sh/v1"
            assert gateway.model_id == "anthropic/claude-sonnet-4.6"
            assert gateway.api_key == "vercel-stored"

    def test_registered_gateway_placeholder_does_not_mask_env_key_or_exact_limits(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("DOCKET_LLM_BASE_URL", raising=False)
        monkeypatch.delenv("DOCKET_LLM_API_KEY", raising=False)
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-env")

        _register_provider(
            "openrouter",
            "https://openrouter.ai/api/v1",
            credentials=("OPENROUTER_API_KEY",),
            models=[
                {
                    "id": "anthropic/claude-sonnet-4.6",
                    "contextWindow": 1_000_000,
                    "maxTokens": 128_000,
                }
            ],
        )

        endpoint = adapter.resolve_endpoint("openrouter/anthropic/claude-sonnet-4.6")

        assert endpoint is not None
        assert endpoint.api_key == "sk-or-env"
        assert endpoint.context_window_tokens == 1_000_000
        assert endpoint.max_output_tokens == 128_000

    def test_ai_gateway_accepts_oidc_fallback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("DOCKET_LLM_BASE_URL", raising=False)
        monkeypatch.delenv("DOCKET_LLM_API_KEY", raising=False)
        monkeypatch.delenv("AI_GATEWAY_API_KEY", raising=False)
        monkeypatch.setenv("VERCEL_OIDC_TOKEN", "oidc-token")

        endpoint = adapter.resolve_endpoint("ai-gateway/anthropic/claude-haiku-4.5")

        assert endpoint is not None
        assert endpoint.api_key == "oidc-token"

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

        _register_provider("local", "http://127.0.0.1:8081/v1", local=True)
        ep = adapter.resolve_endpoint("local/qwen3.6-35b-a3b")
        assert ep is not None
        assert ep.base_url == "http://127.0.0.1:8081/v1"
        assert ep.model_id == "qwen3.6-35b-a3b"
        assert ep.provider == "local"

    def test_stored_provider_resolves_limits_for_the_exact_model(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("DOCKET_LLM_BASE_URL", raising=False)

        _register_provider(
            "local",
            "http://127.0.0.1:8081/v1",
            local=True,
            models=[
                {"id": "other", "contextWindow": 32768, "maxTokens": 4096},
                {"id": "wanted", "contextWindow": 16384, "maxTokens": 2048},
            ],
        )

        ep = adapter.resolve_endpoint("local/wanted")

        assert ep is not None
        assert ep.context_window_tokens == 16384
        assert ep.max_output_tokens == 2048
        client = adapter.client_for("local/wanted")
        assert client is not None
        assert client.context_window_tokens == 16384
        assert client.max_output_tokens == 2048

    def test_url_override_does_not_inherit_limits_from_replaced_endpoint(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DOCKET_LLM_BASE_URL", "http://127.0.0.1:9999/v1")

        _register_provider(
            "local",
            "http://127.0.0.1:8081/v1",
            local=True,
            models=[{"id": "m", "contextWindow": 16384, "maxTokens": 2048}],
        )

        ep = adapter.resolve_endpoint("local/m")

        assert ep is not None
        assert ep.context_window_tokens is None
        assert ep.max_output_tokens is None

    def test_placeholder_local_key_is_not_sent_as_a_credential(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("DOCKET_LLM_BASE_URL", raising=False)
        monkeypatch.delenv("DOCKET_LLM_API_KEY", raising=False)

        _register_provider("local", "http://127.0.0.1:8081/v1", local=True)
        ep = adapter.resolve_endpoint("local/m")
        assert ep is not None and ep.api_key == ""

    def test_provider_named_env_var_fallback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("DOCKET_LLM_BASE_URL", raising=False)
        monkeypatch.delenv("DOCKET_LLM_API_KEY", raising=False)
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or")

        _register_provider(
            "openrouter", "https://openrouter.ai/api/v1", credentials=("OPENROUTER_API_KEY",)
        )
        ep = adapter.resolve_endpoint("openrouter/some-model")
        assert ep is not None and ep.api_key == "sk-or"

    def test_provider_environment_key_overrides_central_store(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("DOCKET_LLM_BASE_URL", raising=False)
        monkeypatch.delenv("DOCKET_LLM_API_KEY", raising=False)
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-env")
        from docket.governance import secrets as _secrets

        with use_home(Home(tmp_path)):
            _secrets.save_secrets({"OPENROUTER_API_KEY": "sk-or-stored"})

            endpoint = adapter.resolve_endpoint("openrouter/anthropic/claude-haiku-4.5")

            assert endpoint is not None
            assert endpoint.api_key == "sk-or-env"

    def test_unknown_provider_resolves_to_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("DOCKET_LLM_BASE_URL", raising=False)
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
        """The port must stay format-free -- a wire field name in agent/ports.py means translation
        leaked out of the adapter. Checks executable string literals only via AST, excluding
        docstrings/comments, since a substring scan would flag legitimate protocol-describing prose."""
        import ast
        from pathlib import Path

        tree = ast.parse(Path(ports.__file__).read_text())
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
        assert not leaked, f"wire vocabulary leaked into agent/ports.py: {leaked}"

    def test_message_roles_are_the_four_the_protocol_defines(self) -> None:
        msgs = [
            ports.system("s"),
            ports.user("u"),
            ports.assistant("a"),
            ports.tool_result(ToolCall("i", "n"), "r"),
        ]
        assert [m.role for m in msgs] == ["system", "user", "assistant", "tool"]
        assert all(isinstance(m, ChatMessage) for m in msgs)
