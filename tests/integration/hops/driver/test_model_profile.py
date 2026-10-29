"""A catalog row's model profile reaches the wire: descriptions, sampling, the closing call, the trace."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from tests.support.model_server import FakeModel, Request, call, register_lab_provider, say
from tests.support.pods import write_meta_overrides as _write_meta
from tests.support.prose import sentence_count

from docket.agent.ports import DOCKET_VERDICT_VALUES, TurnResult
from docket.hops.application.driver import DocketDriver
from docket.observability import trace as _trace

SUBJECT = "docket.hops.application.driver"
VALUES = json.dumps({"values": ["APPROVE", "REQUEST-CHANGES"], "caseSensitive": False})
FORCED = {"type": "function", "function": {"name": "handoff"}}


def _run(env: dict[str, str] | None = None) -> TurnResult:
    _write_meta("rev-agent", role="reviewer", model="lab/m")
    return DocketDriver().run_turn("rev-agent", "agent:rev-agent:default", "review it", 60, env)


def _tools(request: Request) -> dict[str, str]:
    return {
        t["function"]["name"]: t["function"]["description"] for t in request.body.get("tools", [])
    }


class TestLocalRow:
    def test_a_local_row_without_a_profile_sends_compact_descriptions(
        self, fake_model: Callable[..., FakeModel]
    ) -> None:
        server = fake_model(sequence=[say("done")])
        register_lab_provider(server, local=True)

        _run()

        tools = _tools(server.requests[0])
        assert tools and all(sentence_count(text) <= 2 for text in tools.values()), tools

    def test_the_closing_call_of_a_verdict_step_forces_the_handoff_tool(
        self, fake_model: Callable[..., FakeModel]
    ) -> None:
        server = fake_model(
            sequence=[say("The helper is fine."), call("handoff", verdict="APPROVE")]
        )
        register_lab_provider(server, local=True)

        result = _run({DOCKET_VERDICT_VALUES: VALUES})

        first, closing = server.requests
        assert first.body["tool_choice"] == "auto"
        assert closing.body["tool_choice"] == FORCED
        assert result.ok is True
        assert result.output == "The helper is fine.\nAPPROVE"

    def test_a_step_with_no_closing_tool_never_forces_a_call(
        self, fake_model: Callable[..., FakeModel]
    ) -> None:
        server = fake_model(sequence=[say("done")])
        register_lab_provider(server, local=True)

        result = _run()

        assert len(server.requests) == 1
        assert server.requests[0].body["tool_choice"] == "auto"
        assert result.output == "done"


class TestHostedRow:
    def test_a_hosted_row_keeps_full_descriptions_and_never_forces(
        self, fake_model: Callable[..., FakeModel]
    ) -> None:
        server = fake_model(sequence=[say("The helper is fine.")])
        register_lab_provider(server)

        result = _run({DOCKET_VERDICT_VALUES: VALUES})

        (request,) = server.requests
        assert request.body["tool_choice"] == "auto"
        assert "temperature" not in request.body and "top_p" not in request.body
        assert "Nobody can answer during this run" in _tools(request)["consult"]
        assert result.output == "The helper is fine."


class TestSampling:
    def test_a_row_that_declares_sampling_sends_both_on_every_request(
        self, fake_model: Callable[..., FakeModel]
    ) -> None:
        server = fake_model(sequence=[say("one"), call("handoff", verdict="APPROVE")])
        register_lab_provider(server, local=True, sampling={"temperature": 0.7, "topP": 0.8})

        _run({DOCKET_VERDICT_VALUES: VALUES})

        assert len(server.requests) == 2
        for request in server.requests:
            assert request.body["temperature"] == 0.7
            assert request.body["top_p"] == 0.8

    def test_a_local_row_that_declares_none_sends_neither(
        self, fake_model: Callable[..., FakeModel]
    ) -> None:
        server = fake_model(sequence=[say("one")])
        register_lab_provider(server, local=True)

        _run()

        assert "temperature" not in server.requests[0].body
        assert "top_p" not in server.requests[0].body


class TestTrace:
    def test_every_llm_call_names_the_profile_and_what_was_sent(
        self, fake_model: Callable[..., FakeModel]
    ) -> None:
        server = fake_model(sequence=[say("one"), call("handoff", verdict="APPROVE")])
        register_lab_provider(server, local=True, sampling={"temperature": 0.7, "topP": 0.8})
        events: list[dict[str, Any]] = []

        with _trace.subscribe(events.append):
            _run({DOCKET_VERDICT_VALUES: VALUES})

        payloads = [e["payload"] for e in events if e["event_type"] == "llm_call"]
        assert [p["profile"] for p in payloads] == ["local", "local"]
        assert all(p["temperature"] == 0.7 and p["topP"] == 0.8 for p in payloads)
        assert "toolChoice" not in payloads[0] and payloads[1]["toolChoice"] == "handoff"

    def test_a_hosted_call_names_hosted_and_no_sampling(
        self, fake_model: Callable[..., FakeModel]
    ) -> None:
        server = fake_model(sequence=[say("one")])
        register_lab_provider(server)
        events: list[dict[str, Any]] = []

        with _trace.subscribe(events.append):
            _run()

        (payload,) = [e["payload"] for e in events if e["event_type"] == "llm_call"]
        assert payload["profile"] == "hosted"
        assert not {"temperature", "topP", "toolChoice"} & payload.keys()
