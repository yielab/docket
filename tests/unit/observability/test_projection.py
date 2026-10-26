"""Neutral span model, incremental projection and export policy (observability/telemetry.py)."""

from __future__ import annotations

import pytest

from docket.governance import privacy
from docket.observability import projection, trace
from docket.observability import spans as observability_spans

SUBJECT = "docket.observability.projection"


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
        state = observability_spans.ProjectionState()
        spans = projection.project(record, state)
        spans += projection.flush_open(state)
        assert spans, f"{event_type} produced neither a span nor a recorded span event"


def _esc_record(
    event_type: str, ts: str, session: str = "agent:demo:t-1", **payload: object
) -> dict[str, object]:
    base = {
        "escalation": "esc-0123456789ab",
        "kind": "consult",
        "task": "t-1",
        "step": "implementer",
        "policy": "person",
        "askedAt": "2026-10-25T10:00:00Z",
    }
    return {
        "ts": ts,
        "project": "demo",
        "session_id": session,
        "agent_role": "implementer",
        "event_type": event_type,
        "payload": {**base, **payload},
    }


def _run(
    records: list[dict[str, object]],
    policy: observability_spans.ExportPolicy = observability_spans.MINIMAL_POLICY,
    state: observability_spans.ProjectionState | None = None,
) -> list[observability_spans.Span]:
    state = state or observability_spans.ProjectionState()
    spans: list[observability_spans.Span] = []
    for record in records:
        spans += projection.project(record, state, policy)
    return spans


def _escalation_spans(
    spans: list[observability_spans.Span],
) -> list[observability_spans.Span]:
    return [s for s in spans if s.name == "docket.escalation"]


class TestEscalationSpans:
    def test_one_span_per_escalation_lasting_from_the_ask_to_the_settlement(self) -> None:
        spans = _run(
            [
                _esc_record("escalation_asked", "2026-10-25T10:00:00Z", prompt="Which store?"),
                _esc_record(
                    "escalation_resolved",
                    "2026-10-25T10:07:30Z",
                    by="person",
                    optionId="redis",
                    channel="cli",
                ),
            ]
        )

        (span,) = _escalation_spans(spans)
        assert (span.start_ts, span.end_ts) == ("2026-10-25T10:00:00Z", "2026-10-25T10:07:30Z")
        assert span.status == "ok"

    def test_nothing_closes_until_the_escalation_settles(self) -> None:
        assert _run([_esc_record("escalation_asked", "2026-10-25T10:00:00Z")]) == []

    def test_the_attributes_name_the_escalation_and_how_it_ended(self) -> None:
        spans = _run(
            [
                _esc_record("escalation_asked", "2026-10-25T10:00:00Z"),
                _esc_record(
                    "escalation_resolved",
                    "2026-10-25T10:01:00Z",
                    by="person",
                    optionId="redis",
                    channel="telegram",
                ),
            ]
        )

        (span,) = _escalation_spans(spans)
        assert span.attributes == {
            "docket.escalation.id": "esc-0123456789ab",
            "docket.escalation.kind": "consult",
            "docket.escalation.policy": "person",
            "docket.escalation.task": "t-1",
            "docket.escalation.step": "implementer",
            "docket.escalation.by": "person",
            "docket.escalation.channel": "telegram",
            "docket.escalation.outcome": "resolved",
        }

    def test_an_expiry_is_an_error_span_by_the_timeout(self) -> None:
        spans = _run(
            [
                _esc_record("escalation_asked", "2026-10-25T10:00:00Z"),
                _esc_record("escalation_expired", "2026-10-25T12:00:00Z", by="timeout"),
            ]
        )

        (span,) = _escalation_spans(spans)
        assert span.status == "error"
        assert span.attributes["docket.escalation.outcome"] == "expired"
        assert span.attributes["docket.escalation.by"] == "timeout"

    def test_a_policy_decision_never_asked_is_still_one_complete_span(self) -> None:
        spans = _run(
            [
                _esc_record(
                    "escalation_decided",
                    "2026-10-25T10:00:00Z",
                    policy="recommendation",
                    by="policy",
                    optionId="sqlite",
                )
            ]
        )

        (span,) = _escalation_spans(spans)
        assert (span.start_ts, span.end_ts) == ("2026-10-25T10:00:00Z", "2026-10-25T10:00:00Z")
        assert span.attributes["docket.escalation.policy"] == "recommendation"
        assert span.attributes["docket.escalation.by"] == "policy"
        assert span.attributes["docket.escalation.outcome"] == "decided"

    def test_a_settlement_after_a_restart_rebuilds_the_span_from_its_payload(self) -> None:
        late = _esc_record("escalation_resolved", "2026-10-25T10:30:00Z", by="person")

        (span,) = _escalation_spans(_run([late]))

        assert (span.start_ts, span.end_ts) == ("2026-10-25T10:00:00Z", "2026-10-25T10:30:00Z")

    def test_the_span_survives_the_session_end_and_the_turn_flush(self) -> None:
        state = observability_spans.ProjectionState()
        spans = _run(
            [
                _esc_record("session_start", "2026-10-25T09:59:00Z"),
                _esc_record("escalation_asked", "2026-10-25T10:00:00Z"),
            ],
            state=state,
        )
        spans += projection.flush_turn(state)
        spans += _run([_esc_record("session_end", "2026-10-25T10:00:05Z")], state=state)
        assert _escalation_spans(spans) == []

        spans = _run(
            [
                _esc_record("session_start", "2026-10-25T10:20:00Z"),
                _esc_record("escalation_resolved", "2026-10-25T10:20:01Z", by="person"),
            ],
            state=state,
        )

        (span,) = _escalation_spans(spans)
        assert (span.start_ts, span.end_ts) == ("2026-10-25T10:00:00Z", "2026-10-25T10:20:01Z")

    def test_a_forced_flush_closes_a_pending_escalation_at_the_last_timestamp_seen(self) -> None:
        state = observability_spans.ProjectionState()
        _run([_esc_record("escalation_asked", "2026-10-25T10:00:00Z")], state=state)

        (span,) = _escalation_spans(projection.flush_open(state))

        assert span.end_ts == "2026-10-25T10:00:00Z"
        assert projection.flush_open(state) == []

    def test_the_parent_is_the_open_hop_span_else_the_session_root(self) -> None:
        state = observability_spans.ProjectionState()
        _run([_esc_record("session_start", "2026-10-25T09:59:00Z")], state=state)
        root = state.stacks["agent:demo:t-1"][0]
        _run([_esc_record("escalation_asked", "2026-10-25T10:00:00Z")], state=state)
        (bare,) = _escalation_spans(
            _run([_esc_record("escalation_decided", "2026-10-25T10:01:00Z")], state=state)
        )
        assert bare.parent_id == root.span_id

        hop = {
            "ts": "2026-10-25T10:02:00Z",
            "project": "demo",
            "session_id": "agent:demo:t-2",
            "agent_role": "implementer",
            "event_type": "tool_call",
            "payload": {"tool": "implementer"},
        }
        state = observability_spans.ProjectionState()
        projection.project(hop, state)
        hop_span = state.stacks["agent:demo:t-2"][-1]
        projection.project(
            _esc_record(
                "escalation_asked",
                "2026-10-25T10:03:00Z",
                session="agent:demo:t-2",
                escalation="esc-aaaaaaaaaaaa",
            ),
            state,
        )
        (nested,) = _escalation_spans(
            projection.project(
                _esc_record(
                    "escalation_resolved",
                    "2026-10-25T10:04:00Z",
                    session="agent:demo:t-2",
                    escalation="esc-aaaaaaaaaaaa",
                ),
                state,
            )
        )
        assert nested.parent_id == hop_span.span_id

    def test_a_delivery_is_an_event_on_the_open_span(self) -> None:
        spans = _run(
            [
                _esc_record("escalation_asked", "2026-10-25T10:00:00Z"),
                _esc_record("escalation_delivered", "2026-10-25T10:00:02Z", channel="ntfy"),
                _esc_record("escalation_resolved", "2026-10-25T10:01:00Z", by="person"),
            ]
        )

        (span,) = _escalation_spans(spans)
        (event,) = span.events
        assert (event.name, event.ts) == ("escalation_delivered", "2026-10-25T10:00:02Z")
        assert event.attributes == {"docket.escalation.channel": "ntfy"}

    def test_a_delivery_with_no_open_span_is_a_plain_event_on_its_session(self) -> None:
        state = observability_spans.ProjectionState()
        _run(
            [_esc_record("escalation_delivered", "2026-10-25T10:00:02Z", channel="ntfy")],
            state=state,
        )

        (root,) = projection.flush_open(state)
        assert [e.name for e in root.events] == ["escalation_delivered"]

    def test_a_level_in_the_payload_is_forwarded(self) -> None:
        spans = _run(
            [
                _esc_record("escalation_asked", "2026-10-25T10:00:00Z", level="L3"),
                _esc_record("escalation_resolved", "2026-10-25T10:01:00Z", by="person"),
            ]
        )

        (span,) = _escalation_spans(spans)
        assert span.attributes["docket.escalation.level"] == "L3"

    def test_the_prompt_is_exported_only_where_prompts_are_granted(self) -> None:
        records = [
            _esc_record("escalation_asked", "2026-10-25T10:00:00Z", prompt="CANARY-which-store"),
            _esc_record("escalation_resolved", "2026-10-25T10:01:00Z", by="person"),
        ]
        for level in ("minimal", "actions", "conversation", "full"):
            classes = privacy.LEVELS[level]
            policy = observability_spans.ExportPolicy(classes=classes, label=level)
            (span,) = _escalation_spans(_run(records, policy))
            carried = span.attributes.get("docket.escalation.prompt")
            assert carried == ("CANARY-which-store" if "prompts" in classes else None), level

    def test_what_an_approval_asks_is_a_command_line_exported_where_tool_arguments_are(
        self,
    ) -> None:
        records = [
            _esc_record(
                "escalation_asked",
                "2026-10-25T10:00:00Z",
                kind="approval",
                prompt="CANARY-rm-rf-build",
            ),
            _esc_record("escalation_resolved", "2026-10-25T10:01:00Z", by="person"),
        ]
        for level in ("minimal", "actions", "conversation", "full"):
            classes = privacy.LEVELS[level]
            policy = observability_spans.ExportPolicy(classes=classes, label=level)
            (span,) = _escalation_spans(_run(records, policy))
            carried = span.attributes.get("docket.approval.action")
            assert carried == ("CANARY-rm-rf-build" if "toolArguments" in classes else None), level
            assert "docket.escalation.prompt" not in span.attributes

    def test_the_default_events_admit_the_whole_family(self) -> None:
        family = {
            "escalation_asked",
            "escalation_delivered",
            "escalation_resolved",
            "escalation_expired",
            "escalation_decided",
        }
        assert family <= projection.DEFAULT_EVENTS
        assert family <= trace.EVENT_TYPES

    def test_the_options_and_the_recommendation_are_never_attributes(self) -> None:
        spans = _run(
            [
                _esc_record(
                    "escalation_asked",
                    "2026-10-25T10:00:00Z",
                    options=["redis", "sqlite"],
                    prompt="q",
                ),
                _esc_record("escalation_resolved", "2026-10-25T10:01:00Z", optionId="redis"),
            ],
            observability_spans.ExportPolicy(classes=privacy.LEVELS["full"], label="full"),
        )

        (span,) = _escalation_spans(spans)
        assert not any("option" in key.lower() for key in span.attributes)
