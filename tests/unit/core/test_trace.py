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


class TestRedactionWordBoundary:
    """Redaction patterns must match only at word boundaries."""

    def test_task_field_is_not_redacted_as_a_secret(self) -> None:
        """task=... should not match task's 'sk' inside, or 'key' as part of 'task'."""
        text = "task=task-8d627c86-9a63-4379-beee-ee3b2afff6f7"
        assert trace.redact(text) == text

    def test_risk_field_is_not_redacted_as_a_secret(self) -> None:
        """risk=... should not match the 'sk' in 'risk'."""
        text = "risk=" + "a" * 24
        assert trace.redact(text) == text

    def test_api_key_with_underscore_is_redacted(self) -> None:
        """api_key=<value> should be redacted even with underscore."""
        text = "api_key=" + "A" * 24
        out = trace.redact(text)
        assert "[REDACTED]" in out
        assert "A" * 24 not in out

    def test_key_after_colon_is_redacted(self) -> None:
        """key: <value> should be redacted (colon separator)."""
        text = "key: " + "A" * 24
        out = trace.redact(text)
        assert "[REDACTED]" in out
        assert "A" * 24 not in out

    def test_bearer_token_is_redacted(self) -> None:
        """Bearer <value> should be redacted (space separator)."""
        text = "Bearer " + "A" * 24
        out = trace.redact(text)
        assert "[REDACTED]" in out
        assert "A" * 24 not in out

    def test_tok_equals_is_redacted(self) -> None:
        """tok=<value> should be redacted."""
        text = "tok=" + "A" * 24
        out = trace.redact(text)
        assert "[REDACTED]" in out
        assert "A" * 24 not in out


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


class TestTaskId:
    def test_task_id_written_after_event_type_when_truthy(self) -> None:
        trace.trace_event("proj", "s6", "tester", "session_start", "{}", task_id="task-1")
        tracefile = trace.project_trace_dir("proj") / "s6.jsonl"
        record = trace.read_trace(tracefile)[0]
        assert record["task_id"] == "task-1"
        keys = list(record.keys())
        assert keys.index("task_id") == keys.index("event_type") + 1

    def test_task_id_key_absent_when_not_given(self) -> None:
        trace.trace_event("proj", "s7", "tester", "session_start", "{}")
        tracefile = trace.project_trace_dir("proj") / "s7.jsonl"
        record = trace.read_trace(tracefile)[0]
        assert "task_id" not in record


class TestIngestNotifiesSubscribers:
    def test_ingest_notifies_subscribers_before_append(self) -> None:
        from docket.core import session as _session
        from docket.core.llm import ToolCall, assistant, tool_result, user

        session_key = "agent:myshop:default"
        call = ToolCall(id="t1", name="read", arguments="{}")
        _session.append_messages(
            session_key, [user("go"), assistant(tool_calls=[call]), tool_result(call, "ok")]
        )
        received: list[dict[str, object]] = []
        with trace.subscribe(received.append):
            trace.trace_ingest("myshop")
        tracefile = trace.project_trace_dir("myshop") / f"{session_key}.jsonl"
        assert received == trace.read_trace(tracefile)
