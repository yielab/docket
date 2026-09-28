"""Neutral span model, incremental projection and export policy (core/telemetry.py)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from docket.core import telemetry, trace

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
    def test_metadata_drops_tool_call_arguments(self) -> None:
        policy = telemetry.ExportPolicy(payload="metadata")
        record = {
            "event_type": "tool_call",
            "payload": {"tool": "read", "callId": "c1", "arguments": '{"path": "notes.md"}'},
        }
        admitted = policy.admit(record)
        assert admitted is not None
        assert "arguments" not in admitted["payload"]
        assert admitted["payload"]["tool"] == "read"

    def test_full_truncates_content_fields(self) -> None:
        policy = telemetry.ExportPolicy(payload="full", payload_max_chars=10)
        record = {
            "event_type": "tool_result",
            "payload": {"tool": "read", "callId": "c1", "output": "x" * 500},
        }
        admitted = policy.admit(record)
        assert admitted is not None
        assert len(admitted["payload"]["output"]) == 10

    def test_prompt_composed_is_not_admitted_by_default(self) -> None:
        policy = telemetry.ExportPolicy(events=telemetry.DEFAULT_EVENTS)
        record = {"event_type": "prompt_composed", "payload": {"prompt": "be helpful"}}
        assert policy.admit(record) is None
