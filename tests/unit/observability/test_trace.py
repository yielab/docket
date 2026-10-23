"""Secret-shape redaction and the subscriber seam (observability/trace.py)."""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

import pytest

from docket.kernel.home import current_home
from docket.observability import trace


@pytest.fixture
def permissive_umask():
    old = os.umask(0o002)
    yield
    os.umask(old)


SUBJECT = "docket.observability.trace"


class TestRedactPerformance:
    def test_long_alphanumeric_run_redacts_in_linear_time(self) -> None:
        text = "Z" * 40_000  # no secret shape present anywhere in this run
        start = time.perf_counter()
        trace.redact(text)
        elapsed = time.perf_counter() - start
        assert elapsed < 0.5, f"redact() took {elapsed:.2f}s on a 40,000-char alnum run"


def test_an_env_sourced_credential_value_is_redacted(monkeypatch) -> None:
    """A key exported in the shell never rests in `secrets.json`, so the value itself must be
    on the redaction list, not only the `NAME=value` shape."""
    monkeypatch.setenv("DOCKET_LLM_API_KEY", "envsourcedvalue0123456789")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456789:AAbbccddeeffgghhiijjkkllmmnnooppqqrrss1")
    out = trace.redact(
        "the key was envsourcedvalue0123456789 and 123456789:AAbbccddeeffgghhiijjkkllmmnnooppqqrrss1"
    )
    assert "envsourcedvalue0123456789" not in out
    assert "AAbbccddeeffgghh" not in out


@pytest.mark.parametrize(
    "bare",
    [
        "sk-ant-api03-" + "A" * 40,
        "sk-proj-" + "b" * 40,
        "ghp_" + "C" * 36,
        "987654321:AAzz" + "q" * 31,
    ],
)
def test_a_bare_vendor_token_is_redacted_without_a_prefix(bare: str) -> None:
    assert bare not in trace.redact(f"saw {bare} in output")


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


def _session(project: str, name: str, status: str, end: str = "10:00:05") -> None:
    import json

    d = current_home().traces_dir / project
    d.mkdir(parents=True, exist_ok=True)
    events = [
        {"event_type": "session_start", "ts": "2026-10-01T10:00:00Z", "agent_role": "lead"},
        {
            "event_type": "session_end",
            "ts": f"2026-10-01T{end}Z",
            "agent_role": "lead",
            "payload": {"status": status},
        },
    ]
    (d / f"{name}.jsonl").write_text("\n".join(json.dumps(e) for e in events) + "\n")


class TestTerminalOutcomes:
    def test_counts_done_failed_and_aborted_sessions(self) -> None:
        _session("demo", "a", "done")
        _session("demo", "b", "failed")
        _session("demo", "c", "failed")
        _session("demo", "d", "cancelled")

        out = trace.terminal_outcomes("demo", window=50)

        assert (out.success, out.failure, out.aborted) == (1, 2, 1)
        assert out.mean_ms == 5000

    def test_a_parked_task_is_not_terminal(self) -> None:
        _session("demo", "a", "done")
        _session("demo", "b", "waiting_input")
        assert trace.terminal_outcomes("demo", window=50).total == 1

    def test_the_window_keeps_only_the_newest_sessions(self) -> None:
        _session("demo", "a", "failed")
        _session("demo", "b", "done")
        out = trace.terminal_outcomes("demo", window=1)
        assert (out.success, out.failure) == (1, 0)

    def test_an_unknown_project_is_all_zero(self) -> None:
        assert trace.terminal_outcomes("nobody", window=50).total == 0

    def test_the_window_is_the_latest_by_end_time_not_by_file_name(self) -> None:
        # Session ids are random, so the file-name order says nothing about recency.
        _session("demo", "task-ffff", "failed", end="10:00:05")
        _session("demo", "task-0000", "done", end="11:00:05")
        _session("demo", "task-8888", "failed", end="10:30:05")

        out = trace.terminal_outcomes("demo", window=1)

        assert (out.success, out.failure) == (1, 0)

    def test_a_line_that_is_not_an_object_does_not_break_the_count(self) -> None:
        _session("demo", "a", "done")
        tf = trace.project_trace_dir("demo") / "a.jsonl"
        tf.write_text(tf.read_text() + '[1, 2]\n42\n"text"\n')

        assert trace.terminal_outcomes("demo", window=50).success == 1


class TestSweepAll:
    def _stale(self, name: str = "stale") -> Path:

        d = current_home().traces_dir / "demo"
        d.mkdir(parents=True, exist_ok=True)
        tf = d / f"{name}.jsonl"
        tf.write_text(json.dumps({"ts": "2000-01-01T00:00:00Z", "event_type": "tool_call"}) + "\n")
        return tf

    def test_the_synthetic_session_end_reaches_subscribers_before_it_is_appended(self) -> None:
        tf = self._stale()
        received: list[dict[str, object]] = []

        with trace.subscribe(received.append):
            trace.sweep_all()

        assert received == [trace.read_trace(tf)[-1]]
        assert received[0]["event_type"] == "session_end"

    def test_no_trace_suppresses_the_sweep_write_and_the_notification(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        tf = self._stale()
        before = tf.read_text()
        received: list[dict[str, object]] = []
        monkeypatch.setenv("DOCKET_NO_TRACE", "1")

        with trace.subscribe(received.append):
            trace.sweep_all()

        assert tf.read_text() == before
        assert received == []

    def test_a_line_that_is_not_an_object_does_not_stop_the_sweep(self) -> None:
        tf = self._stale("a-stale")
        tf.write_text("[1]\n" + tf.read_text())
        other = self._stale("b-stale")

        trace.sweep_all()

        assert trace.read_trace(tf)[-1]["event_type"] == "session_end"
        assert trace.read_trace(other)[-1]["event_type"] == "session_end"


class TestLinesThatAreNotObjects:
    def _write(self) -> Path:

        d = current_home().traces_dir / "demo"
        d.mkdir(parents=True, exist_ok=True)
        tf = d / "s.jsonl"
        tf.write_text(
            '{"ts": "2026-10-01T10:00:00Z", "event_type": "session_start"}\n'
            "[1, 2]\n"
            "42\n"
            '"text"\n'
            "null\n"
            '{"ts": "2026-10-01T10:00:09Z", "event_type": "session_end"}\n'
        )
        return tf

    def test_read_trace_returns_only_objects(self) -> None:
        tf = self._write()

        assert [r["event_type"] for r in trace.read_trace(tf)] == ["session_start", "session_end"]

    def test_export_lines_with_a_since_filter_does_not_raise(self) -> None:
        self._write()

        lines = trace.export_lines("demo", since="2026-10-01T10:00:05Z")

        assert [ln for ln in lines if ln.startswith("{")] == [
            '{"ts": "2026-10-01T10:00:09Z", "event_type": "session_end"}'
        ]

    def test_retention_skips_them(self) -> None:
        self._write()

        report = trace.expire_old_traces(retention_s=1)

        assert report.expired_count == 1


def test_a_new_trace_project_directory_is_created_0700(tmp_path, permissive_umask) -> None:
    """A trace append creates its project directory private under a permissive umask."""
    tracefile = tmp_path / "traces" / "newproj" / "sess.jsonl"
    trace._append(tracefile, [{"kind": "x"}])
    assert oct(os.stat(tracefile.parent).st_mode & 0o777) == "0o700"
    assert oct(os.stat(tracefile).st_mode & 0o777) == "0o600"


def test_hop_events_are_known_types() -> None:
    """The two hop-level events belong to the closed event vocabulary."""
    assert {"hop_started", "hop_finished"} <= trace.EVENT_TYPES


class TestRedactionKeepsPayloadStructured:
    """trace_event redacts string values of a JSON payload, never its structure."""

    @staticmethod
    def _stored(tmp_path: object) -> dict[str, object]:
        import json

        files = list(current_home().traces_dir.glob("*/*.jsonl"))
        assert len(files) == 1
        rec: dict[str, object] = json.loads(files[0].read_text().splitlines()[-1])
        return rec

    def test_secret_in_error_keeps_object_and_usage(self, tmp_path: object) -> None:
        """An error holding NAME_API_TOKEN=value is stored as an object with usage intact."""
        import json

        payload = json.dumps({"error": "x FAKE_API_TOKEN=abc", "usage": {"input": 1}})
        assert trace.trace_event("p", "s", "lead", "hop_finished", payload) == "written"
        stored = self._stored(tmp_path)["payload"]
        assert isinstance(stored, dict)
        assert stored["usage"] == {"input": 1}
        assert "abc" not in stored["error"]
        assert "[REDACTED]" in stored["error"]
        assert "text" not in stored

    def test_stored_secret_value_two_levels_deep_is_replaced(
        self, tmp_path: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A stored secret nested two levels deep is replaced and siblings survive."""
        import json

        monkeypatch.setenv("SOME_SERVICE_TOKEN", "zz-secret-value-12345")
        payload = json.dumps(
            {"a": {"b": ["note zz-secret-value-12345 end", {"c": "zz-secret-value-12345"}]}, "n": 2}
        )
        trace.trace_event("p", "s", "lead", "hop_finished", payload)
        stored = self._stored(tmp_path)["payload"]
        assert "zz-secret-value-12345" not in json.dumps(stored)
        assert stored["n"] == 2
        assert stored["a"]["b"][1]["c"] == "[REDACTED]"

    def test_plain_text_payload_is_redacted_as_text(self, tmp_path: object) -> None:
        """A non-JSON payload is redacted whole and wrapped as text."""
        trace.trace_event("p", "s", "lead", "error", "boom FAKE_API_TOKEN=abc done")
        stored = self._stored(tmp_path)["payload"]
        assert isinstance(stored, dict)
        assert "abc" not in stored["text"]
        assert "[REDACTED]" in stored["text"]
