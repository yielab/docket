"""Secret-shape redaction and the subscriber seam (core/trace.py)."""

from __future__ import annotations

import re
import time

import pytest

from docket.core import trace

SUBJECT = "docket.core.trace"


class TestRedactPerformance:
    def test_long_alphanumeric_run_redacts_in_linear_time(self) -> None:
        text = "Z" * 40_000  # no secret shape present anywhere in this run
        start = time.perf_counter()
        trace.redact(text)
        elapsed = time.perf_counter() - start
        assert elapsed < 0.5, f"redact() took {elapsed:.2f}s on a 40,000-char alnum run"


@pytest.mark.parametrize(
    ("text", "leaked"),
    [
        ("api_key=abcdefghijklmnopqrstuvwxyz0123456789", "abcdefghijklmnopqrstuvwxyz0123456789"),
        ("api_key=sk-ant-abcdefghijklmnopqrstuvwxyz0123", "sk-ant-abcdefghijklmnopqrstuvwxyz0123"),
        (
            "deploy with ANTHROPIC_API_KEY=sk-ant-abcdefghijklmnopqrstuvwxyz123456",
            "sk-ant-abcdefghijklmnopqrstuvwxyz123456",
        ),
        (
            "MYAPP_API_KEY=sk-ant-1234567890abcdefghijklmnop",
            "sk-ant-1234567890abcdefghijklmnop",
        ),
        ("loop in leaky@example.com before shipping", "leaky@example.com"),
        ("lead contact: lead@example.com", "lead@example.com"),
        ("impl contact: impl@example.com", "impl@example.com"),
    ],
)
def test_every_previously_redacted_shape_still_redacts(text: str, leaked: str) -> None:
    out = trace.redact(text)
    assert "[REDACTED]" in out
    assert leaked not in out


def test_short_value_and_plain_text_are_left_alone() -> None:
    assert trace.redact("value abc123 here") == "value abc123 here"
    assert trace.redact('{"action": "edit"}') == '{"action": "edit"}'


class TestSubscribe:
    def test_sink_receives_the_exact_record_read_trace_later_returns(self) -> None:
        received: list[dict[str, object]] = []
        with trace.subscribe(received.append):
            status = trace.trace_event("proj", "s1", "tester", "session_start", '{"a": 1}')
        assert status == "written"
        tracefile = trace.project_trace_dir("proj") / "s1.jsonl"
        assert received == trace.read_trace(tracefile)

    def test_sink_receives_nothing_once_the_context_exits(self) -> None:
        received: list[dict[str, object]] = []
        with trace.subscribe(received.append):
            pass
        trace.trace_event("proj", "s2", "tester", "session_start", "{}")
        assert received == []

    def test_sink_receives_nothing_when_trace_is_suppressed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DOCKET_NO_TRACE", "1")
        received: list[dict[str, object]] = []
        with trace.subscribe(received.append):
            status = trace.trace_event("proj", "s3", "tester", "session_start", "{}")
        assert status == "suppressed"
        assert received == []

    def test_a_raising_sink_never_changes_the_write_or_the_return_value(self) -> None:
        def boom(_record: dict[str, object]) -> None:
            raise RuntimeError("sink exploded")

        with trace.subscribe(boom):
            status = trace.trace_event("proj", "s4", "tester", "session_start", '{"a": 1}')
        assert status == "written"
        tracefile = trace.project_trace_dir("proj") / "s4.jsonl"
        records = trace.read_trace(tracefile)
        assert len(records) == 1
        assert records[0]["event_type"] == "session_start"

    def test_zero_sinks_produces_a_byte_identical_record_shape(self) -> None:
        trace.trace_event("proj", "s5", "tester", "session_start", '{"a": 1}')
        tracefile = trace.project_trace_dir("proj") / "s5.jsonl"
        line = tracefile.read_text(encoding="utf-8").splitlines()[0]
        assert re.fullmatch(
            r'\{"ts": "[^"]+", "project": "proj", "session_id": "s5", '
            r'"agent_role": "tester", "event_type": "session_start", "payload": \{"a": 1\}\}',
            line,
        ), line
