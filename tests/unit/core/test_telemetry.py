"""Neutral span model, incremental projection and export policy (core/telemetry.py)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from docket.core import privacy, telemetry, trace
from docket.edges.adapters.exporters import otlp_http

SUBJECT = "docket.core.telemetry"

_FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "traces" / "dispatch-3-hops.jsonl"


def _load_fixture() -> list[dict[str, Any]]:
    return [json.loads(line) for line in _FIXTURE.read_text().splitlines() if line.strip()]


def _project_all(records: list[dict[str, Any]]) -> list[telemetry.Span]:
    state = telemetry.ProjectionState()
    spans: list[telemetry.Span] = []
    for record in records:
        spans.extend(telemetry.project(record, state))
    spans.extend(telemetry.flush_open(state))
    return spans


class TestFixtureProjection:
    def test_one_root_session_span(self) -> None:
        spans = _project_all(_load_fixture())
        roots = [s for s in spans if s.name == "docket.session"]
        assert len(roots) == 1
        root = roots[0]
        assert root.parent_id is None
        assert root.attributes["docket.project"] == "demo-project"
        assert root.attributes["docket.role"] == "lead"
        assert root.attributes["docket.session_id"] == "s1"
        assert root.attributes["session.id"] == "s1"

    def test_two_llm_call_children_carry_measured_tokens(self) -> None:
        spans = _project_all(_load_fixture())
        chats = [s for s in spans if s.name == "gen_ai.chat"]
        assert len(chats) == 2
        input_tokens = {s.attributes["gen_ai.usage.input_tokens"] for s in chats}
        assert input_tokens == {120, 180}
        root_id = next(s.span_id for s in spans if s.name == "docket.session")
        assert all(s.parent_id == root_id for s in chats)

    def test_execute_tool_span_closes_with_ok(self) -> None:
        spans = _project_all(_load_fixture())
        tool_spans = [s for s in spans if s.name == "execute_tool read"]
        assert len(tool_spans) == 1
        assert tool_spans[0].attributes["docket.tool.ok"] is True

    def test_guardrail_block_is_a_span_event_on_root(self) -> None:
        spans = _project_all(_load_fixture())
        root = next(s for s in spans if s.name == "docket.session")
        event_names = [e.name for e in root.events]
        assert "guardrail_block" in event_names

    def test_every_parent_id_resolves_within_the_output(self) -> None:
        spans = _project_all(_load_fixture())
        span_ids = {s.span_id for s in spans}
        for span in spans:
            if span.parent_id is not None:
                assert span.parent_id in span_ids

    def test_ids_are_identical_on_a_second_run(self) -> None:
        first = _project_all(_load_fixture())
        second = _project_all(_load_fixture())
        first_ids = sorted((s.trace_id, s.span_id) for s in first)
        second_ids = sorted((s.trace_id, s.span_id) for s in second)
        assert first_ids == second_ids


class TestEventTypeCoverage:
    @pytest.mark.parametrize("event_type", sorted(trace.EVENT_TYPES))
    def test_every_event_type_produces_no_exception(self, event_type: str) -> None:
        record = {
            "ts": "2026-09-27T10:00:00Z",
            "project": "p",
            "session_id": "cover",
            "agent_role": "lead",
            "event_type": event_type,
            "payload": {},
        }
        state = telemetry.ProjectionState()
        spans = telemetry.project(record, state)
        spans += telemetry.flush_open(state)
        assert spans, f"{event_type} produced neither a span nor a recorded span event"


class TestExportPolicy:
    """``admit`` filters by event type only (ADR 0015 §2 rule 1) -- content reduction moved
    to `project`'s allowlist, exercised below in ``TestPrivacyAllowlist``."""

    def test_admit_never_rewrites_the_payload(self) -> None:
        policy = telemetry.ExportPolicy(classes=frozenset())
        payload = {"tool": "read", "callId": "c1", "arguments": '{"path": "notes.md"}'}
        record = {"event_type": "tool_call", "payload": payload}
        admitted = policy.admit(record)
        assert admitted is record
        assert admitted["payload"] is payload

    def test_admit_rejects_an_event_type_outside_events(self) -> None:
        policy = telemetry.ExportPolicy(events=frozenset({"tool_call"}))
        record = {"event_type": "tool_result", "payload": {}}
        assert policy.admit(record) is None

    def test_prompt_composed_is_not_admitted_by_default(self) -> None:
        policy = telemetry.ExportPolicy(events=telemetry.DEFAULT_EVENTS)
        record = {"event_type": "prompt_composed", "payload": {"prompt": "be helpful"}}
        assert policy.admit(record) is None


def _canary_records() -> list[dict[str, Any]]:
    """One synthetic record per ``trace.EVENT_TYPES`` member: every content-eligible field
    is seeded ``CANARY-<event>-<key>``; every other forwarded field gets a plain value, so a
    leak of the wrong field is distinguishable from a leak of the right one."""
    ts = "2026-09-28T00:00:00Z"
    records: list[dict[str, Any]] = []
    for event_type in sorted(trace.EVENT_TYPES):
        base = {
            "ts": ts,
            "project": "p",
            "session_id": f"s-{event_type}",
            "agent_role": "lead",
            "task_id": "t1",
            "event_type": event_type,
        }
        if event_type == "tool_call":
            payload: dict[str, Any] = {
                "tool": "read",
                "callId": "c1",
                "arguments": f"CANARY-{event_type}-arguments",
            }
        elif event_type == "tool_result":
            payload = {
                "tool": "read",
                "callId": "c1",
                "decision": "allow",
                "ok": True,
                "executed": True,
                "text": f"CANARY-{event_type}-text",
            }
        elif event_type == "llm_call":
            payload = _llm_call_canary_payload()
        else:
            payload = {
                key: f"struct-{event_type}-{key}"
                for key in telemetry._STRUCTURAL_KEYS.get(event_type, ())
            }
            content = telemetry._GENERIC_CONTENT_ATTRS.get(event_type)
            if content is not None:
                payload_key, _attr_name, _cls = content
                payload[payload_key] = f"CANARY-{event_type}-{payload_key}"
        records.append({**base, "payload": payload})
    return records


def _llm_call_canary_payload() -> dict[str, Any]:
    return {
        "model": "m",
        "provider": "p",
        "ok": True,
        "finishReason": "stop",
        "failureKind": None,
        "inputTokens": 1,
        "outputTokens": 1,
        "cachedTokens": 0,
        "inputMessages": [
            {"role": "system", "parts": [{"type": "text", "content": "CANARY-llm_call-system"}]},
            {"role": "user", "parts": [{"type": "text", "content": "CANARY-llm_call-user"}]},
            {
                "role": "assistant",
                "parts": [
                    {"type": "text", "content": "CANARY-llm_call-assistant-text"},
                    {
                        "type": "tool_call",
                        "id": "c1",
                        "name": "read",
                        "content": "CANARY-llm_call-assistant-toolcall",
                    },
                ],
            },
            {"role": "tool", "parts": [{"type": "text", "content": "CANARY-llm_call-tool"}]},
        ],
        "outputMessages": [
            {
                "role": "assistant",
                "parts": [{"type": "text", "content": "CANARY-llm_call-completion"}],
            }
        ],
        "systemInstructions": "CANARY-llm_call-instructions",
        "systemInstructionsSha256": "deadbeef",
    }


# canary attribute -> the one class that must be granted for it to appear.
_CANARY_CLASSES: dict[str, str] = {
    "CANARY-approval_requested-action": "toolArguments",
    "CANARY-error-error": "errors",
    "CANARY-tool_call-arguments": "toolArguments",
    "CANARY-tool_result-text": "toolResults",
    "CANARY-llm_call-system": "instructions",
    "CANARY-llm_call-instructions": "instructions",
    "CANARY-llm_call-user": "prompts",
    "CANARY-llm_call-assistant-text": "prompts",
    "CANARY-llm_call-assistant-toolcall": "toolArguments",
    "CANARY-llm_call-tool": "toolResults",
    "CANARY-llm_call-completion": "completions",
}


def _encode_under(records: list[dict[str, Any]], policy: telemetry.ExportPolicy) -> str:
    state = telemetry.ProjectionState()
    spans: list[telemetry.Span] = []
    for record in records:
        spans.extend(telemetry.project(record, state, policy))
    spans.extend(telemetry.flush_open(state))
    return json.dumps(otlp_http.encode(spans, resource={}, aliases={}))


def _assert_shares_exactly(encoded: str, classes: frozenset[str]) -> None:
    for canary, cls in _CANARY_CLASSES.items():
        if cls in classes:
            assert canary in encoded, f"{canary} missing though {cls} is granted"
        else:
            assert canary not in encoded, f"{canary} leaked though {cls} is not granted"


class TestPrivacyAllowlist:
    """The canary property (ADR 0015, "Test discipline"): under `minimal` nothing beyond
    structure leaves; under any granted set, exactly its classes' canaries appear."""

    def test_minimal_shares_no_canary(self) -> None:
        encoded = _encode_under(_canary_records(), telemetry.MINIMAL_POLICY)
        assert "CANARY-" not in encoded
        _assert_shares_exactly(encoded, frozenset())

    @pytest.mark.parametrize("level", sorted(privacy.LEVELS))
    def test_level_shares_exactly_its_granted_classes(self, level: str) -> None:
        classes = privacy.LEVELS[level]
        policy = telemetry.ExportPolicy(classes=classes, label=level)
        encoded = _encode_under(_canary_records(), policy)
        _assert_shares_exactly(encoded, classes)

    @pytest.mark.parametrize("cls", sorted(privacy.CONTENT_CLASSES))
    def test_single_class_share_grants_only_that_class(self, cls: str) -> None:
        policy = telemetry.ExportPolicy(classes=frozenset({cls}), label="custom")
        encoded = _encode_under(_canary_records(), policy)
        _assert_shares_exactly(encoded, frozenset({cls}))

    def test_nothing_granted_omits_the_input_messages_attribute(self) -> None:
        llm_record = next(r for r in _canary_records() if r["event_type"] == "llm_call")
        state = telemetry.ProjectionState()
        spans = telemetry.project(llm_record, state, telemetry.MINIMAL_POLICY)
        chat = next(s for s in spans if s.name == "gen_ai.chat")
        assert "gen_ai.input.messages" not in chat.attributes

    def test_share_prompts_withholds_the_tool_turn_as_a_marked_part(self) -> None:
        policy = telemetry.ExportPolicy(classes=frozenset({"prompts"}), label="custom")
        llm_record = next(r for r in _canary_records() if r["event_type"] == "llm_call")
        state = telemetry.ProjectionState()
        spans = telemetry.project(llm_record, state, policy)
        spans += telemetry.flush_open(state)
        chat = next(s for s in spans if s.name == "gen_ai.chat")
        input_messages = json.loads(str(chat.attributes["gen_ai.input.messages"]))
        tool_turn = next(m for m in input_messages if m["role"] == "tool")
        assert tool_turn["parts"] == [{"type": "withheld", "class": "toolResults"}]
        user_turn = next(m for m in input_messages if m["role"] == "user")
        assert user_turn["parts"][0]["content"] == "CANARY-llm_call-user"
        assert "gen_ai.output.messages" not in chat.attributes

    def test_long_part_truncates_and_stays_valid_json(self) -> None:
        policy = telemetry.ExportPolicy(
            classes=frozenset({"prompts"}), label="custom", content_max_chars=4000
        )
        record = {
            "ts": "2026-09-28T00:00:00Z",
            "project": "p",
            "session_id": "s-trunc",
            "agent_role": "lead",
            "event_type": "llm_call",
            "payload": {
                "model": "m",
                "provider": "p",
                "ok": True,
                "finishReason": "stop",
                "inputTokens": 1,
                "outputTokens": 1,
                "cachedTokens": 0,
                "inputMessages": [
                    {"role": "user", "parts": [{"type": "text", "content": "x" * 10000}]}
                ],
            },
        }
        state = telemetry.ProjectionState()
        spans = telemetry.project(record, state, policy)
        spans += telemetry.flush_open(state)
        chat = next(s for s in spans if s.name == "gen_ai.chat")
        input_messages = json.loads(str(chat.attributes["gen_ai.input.messages"]))
        content = input_messages[0]["parts"][0]["content"]
        assert content == "x" * 4000 + "…[truncated 6000 chars]"
        json.dumps(content)  # still a valid string to re-encode
