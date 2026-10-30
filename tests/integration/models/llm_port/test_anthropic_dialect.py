"""The `anthropic-messages` dialect end to end: the real client and a real turn against the fake.

A `kind: provider` document with `dialect: anthropic-messages` is read by `client_for`, spoken to
through `POST /v1/messages` on the fake model server, and driven by `DocketDriver.run_turn`.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest
from tests.support import pods as _support_pods
from tests.support.model_server import FakeModel, Reply, call, fail, say
from tests.support.pods import write_meta_overrides as _write_meta
from tests.support.trace import trace_events

from docket.agent import ports as _ports
from docket.agent.ports import Endpoint, user
from docket.governance import secrets as _secrets
from docket.hops.application.driver import DocketDriver
from docket.models import catalog as _catalog
from docket.models.adapters import openai_http as adapter

workspace = _support_pods.workspace

SUBJECT = "docket.models.adapters.openai_http"

_KEY = "sk-ant-test-0123456789"

_RECORDED = Path(__file__).resolve().parents[3] / "fixtures" / "anthropic-messages"


def _recorded(name: str) -> Reply:
    """A real `/v1/messages` reply, served byte for byte."""
    return Reply(raw_body=(_RECORDED / f"{name}.json").read_text(encoding="utf-8"))


def _id(name: str) -> str:
    return str(json.loads((_RECORDED / f"{name}.json").read_text(encoding="utf-8"))["id"])


def _register(server: FakeModel, **model_row: object) -> None:
    _catalog.save_provider(
        _catalog.ProviderSpec.model_validate(
            {
                "name": "lab",
                "dialect": "anthropic-messages",
                "baseUrl": server.base_url,
                "auth": {"type": "header", "header": "x-api-key", "credentials": ["LAB_API_KEY"]},
                "headers": {"anthropic-version": "2023-06-01"},
                "models": [{"id": "m", "contextWindow": 32768, **model_row}],
            }
        )
    )


@pytest.fixture(autouse=True)
def _credential(monkeypatch: pytest.MonkeyPatch) -> None:
    _secrets.save_secrets({"LAB_API_KEY": _KEY})
    monkeypatch.delenv("LAB_API_KEY", raising=False)
    monkeypatch.delenv("DOCKET_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("DOCKET_LLM_API_KEY", raising=False)


class TestTheClient:
    def test_the_catalog_dialect_picks_the_messages_wire_and_the_key_header(
        self, fake_model: Callable[..., FakeModel]
    ) -> None:
        server = fake_model(sequence=[say("hello")])
        _register(server, maxTokens=512)

        client = adapter.client_for("lab/m")
        assert client is not None
        got = client.complete([user("hi")], timeout=5)

        assert got.ok and got.message.content == "hello"
        request = server.requests[0]
        assert request.path == "/v1/messages"
        assert request.headers.get("x-api-key") == _KEY
        assert "authorization" not in request.headers
        assert request.headers.get("anthropic-version") == "2023-06-01"
        assert request.raw["max_tokens"] == 512

    def test_an_unknown_output_cap_fails_before_any_request_naming_the_flag(
        self, fake_model: Callable[..., FakeModel]
    ) -> None:
        server = fake_model(sequence=[say("never")])
        _register(server)

        client = adapter.client_for("lab/m")
        assert client is not None
        got = client.complete([user("hi")], timeout=5)

        assert (got.ok, got.failure_kind) == (False, "nonzero_exit")
        assert "--max-tokens" in got.error and "lab" in got.error and "m" in got.error
        assert server.requests == []

    def test_a_request_carrying_its_own_max_tokens_needs_no_declared_cap(
        self, fake_model: Callable[..., FakeModel]
    ) -> None:
        server = fake_model(sequence=[say("ok")])
        _register(server)

        client = adapter.client_for("lab/m")
        assert client is not None
        got = client.complete([user("hi")], max_tokens=64, timeout=5)

        assert got.ok and server.requests[0].raw["max_tokens"] == 64

    def test_estimating_the_input_never_needs_the_output_cap(self) -> None:
        client = adapter.client_for_endpoint(
            Endpoint(base_url="http://127.0.0.1:1/v1", model_id="m"), "anthropic-messages"
        )
        assert client is not None

        assert client.estimate_input_tokens([user("hi there")]) > 0

    def test_the_url_follows_the_dialect(self) -> None:
        endpoint = Endpoint(base_url="http://127.0.0.1:9999/v1", model_id="m")

        messages = adapter.client_for_endpoint(endpoint, "anthropic-messages")
        chat = adapter.client_for_endpoint(endpoint, "openai-chat")

        assert messages is not None and chat is not None
        assert messages.url == "http://127.0.0.1:9999/v1/messages"
        assert chat.url == "http://127.0.0.1:9999/v1/chat/completions"

    def test_each_request_names_the_previous_reply_and_a_failed_call_keeps_it(
        self, fake_model: Callable[..., FakeModel]
    ) -> None:
        server = fake_model(
            sequence=[_recorded("tool-use"), fail(400), _recorded("end-turn-cached"), say("x")]
        )
        _register(server, maxTokens=512)
        client = adapter.client_for("lab/m")
        assert client is not None

        for _ in range(4):
            client.complete([user("hi")], timeout=5)

        sent = [r.raw["diagnostics"] for r in server.requests]
        assert sent == [
            {"previous_message_id": None},
            {"previous_message_id": _id("tool-use")},
            {"previous_message_id": _id("tool-use")},
            {"previous_message_id": _id("end-turn-cached")},
        ]

    def test_the_openai_chat_wire_sends_no_diagnostics(
        self, fake_model: Callable[..., FakeModel]
    ) -> None:
        server = fake_model(sequence=[say("a"), say("b")])
        client = adapter.client_for_endpoint(
            Endpoint(base_url=server.base_url, model_id="m"), "openai-chat"
        )
        assert client is not None

        client.complete([user("hi")], timeout=5)
        got = client.complete([user("hi")], timeout=5)

        assert got.ok and got.cache_miss == ""
        assert all("diagnostics" not in r.raw for r in server.requests)

    def test_a_dialect_with_no_adapter_gives_no_client(self) -> None:
        endpoint = Endpoint(base_url="http://127.0.0.1:1/v1", model_id="m")

        assert adapter.client_for_endpoint(endpoint, "no-such-dialect") is None


class TestTheTurn:
    def test_a_pod_member_runs_a_bash_call_and_a_closing_tool_and_the_trace_carries_the_cache_read(
        self,
        fake_model: Callable[..., FakeModel],
        workspace: Path,
    ) -> None:
        usage = {
            "input_tokens": 4,
            "output_tokens": 9,
            "cache_read_input_tokens": 300,
            "cache_creation_input_tokens": 11,
        }
        server = fake_model(
            sequence=[
                call("bash", call_id="b1", command="echo from-the-turn"),
                call("handoff", call_id="h1", summary="all done"),
            ],
            usage=usage,
        )
        _register(server, maxTokens=1024)
        _write_meta("cache-agent", role="implementer", model="lab/m", codebase=str(workspace))

        result = DocketDriver().run_turn(
            "cache-agent", "agent:cache-agent:default", "list it", 60, {_ports.DOCKET_HANDOFF: "1"}
        )

        assert result.ok, result.error
        assert result.closing_args == {"summary": "all done"}
        assert [r.path for r in server.requests] == ["/v1/messages", "/v1/messages"]
        assert all(r.headers.get("x-api-key") == _KEY for r in server.requests)
        assert all("authorization" not in r.headers for r in server.requests)
        assert "from-the-turn" in (server.requests[1].tool_result("b1") or "")
        calls = [e for e in trace_events("cache-agent") if e["event_type"] == "llm_call"]
        assert len(calls) == 2
        assert [e["payload"]["cachedTokens"] for e in calls] == [300, 300]
        assert [e["payload"]["inputTokens"] for e in calls] == [315, 315]

    def test_the_trace_carries_the_divergence_the_endpoint_reported(
        self,
        fake_model: Callable[..., FakeModel],
        workspace: Path,
    ) -> None:
        server = fake_model(
            sequence=[_recorded("diagnostics-not-found"), _recorded("diagnostics-system-changed")]
        )
        _register(server, maxTokens=1024)
        _write_meta("diag-agent", role="implementer", model="lab/m", codebase=str(workspace))

        result = DocketDriver().run_turn("diag-agent", "agent:diag-agent:default", "ls", 60, {})

        assert result.ok, result.error
        calls = [e["payload"] for e in trace_events("diag-agent") if e["event_type"] == "llm_call"]
        assert [(c.get("cacheMiss"), c.get("cacheMissedTokens")) for c in calls] == [
            ("previous_message_not_found", None),
            ("system_changed", 11262),
        ]
        assert server.requests[1].raw["diagnostics"] == {
            "previous_message_id": _id("diagnostics-not-found")
        }
