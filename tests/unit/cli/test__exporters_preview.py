"""`docket exporters preview` -- the pure argument-parsing, classification and display helpers.

The CLI integration test (`tests/integration/test_exporters_cli.py::TestPreview`) only
exercises these through a real seeded session; covered here in isolation the same way
`tests/unit/cli/test__exporters.py` covers its neighbour module's pure helpers.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from docket.cli import _exporters_preview as _preview

SUBJECT = "docket.cli._exporters_preview"


class TestParseOpts:
    def test_splits_positionals_from_key_value_and_key_equals_value(self) -> None:
        pos, opts = _preview._parse_opts(["langfuse", "--session", "sess-1", "--level=actions"])
        assert pos == ["langfuse"]
        assert opts == {"session": "sess-1", "level": "actions"}


class TestAttributeClass:
    def test_a_table_attribute_resolves_to_its_declared_class(self) -> None:
        assert _preview._attribute_class("gen_ai.tool.call.arguments") == "toolArguments"
        assert _preview._attribute_class("gen_ai.tool.call.result") == "toolResults"
        assert _preview._attribute_class("docket.error.message") == "errors"

    def test_the_per_part_message_attribute_is_its_own_row(self) -> None:
        assert _preview._attribute_class("gen_ai.input.messages") == "per part"

    def test_an_unlisted_attribute_is_structure(self) -> None:
        assert _preview._attribute_class("gen_ai.request.model") == "structure"
        assert _preview._attribute_class("docket.session_id") == "structure"


class TestDisplay:
    def test_short_text_is_unchanged(self) -> None:
        assert _preview._display("hello") == "hello"

    def test_long_text_is_cut_with_a_visible_marker(self) -> None:
        text = "x" * 250
        out = _preview._display(text)
        assert out.startswith("x" * 200)
        assert "[+50 chars]" in out

    def test_non_string_values_are_stringified(self) -> None:
        assert _preview._display(True) == "True"
        assert _preview._display(7) == "7"


class TestRecordedContent:
    def test_false_when_no_llm_call_carries_a_content_key(self) -> None:
        records = [
            {"event_type": "session_start", "payload": {}},
            {"event_type": "llm_call", "payload": {"model": "x", "ok": True}},
        ]
        assert _preview._recorded_content(records) is False

    def test_true_when_an_llm_call_carries_input_messages(self) -> None:
        records = [
            {"event_type": "llm_call", "payload": {"inputMessages": [{"role": "user"}]}},
        ]
        assert _preview._recorded_content(records) is True

    def test_an_empty_content_value_does_not_count(self) -> None:
        records = [{"event_type": "llm_call", "payload": {"inputMessages": []}}]
        assert _preview._recorded_content(records) is False


class TestNewestTraceFile:
    def test_none_when_traces_dir_has_no_sessions(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(_preview._cfg, "TRACES_DIR", tmp_path / "traces", raising=True)
        assert _preview._newest_trace_file() is None

    def test_picks_the_most_recently_modified_file_across_projects(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        traces = tmp_path / "traces"
        monkeypatch.setattr(_preview._cfg, "TRACES_DIR", traces, raising=True)
        older = traces / "proj-a" / "sess-old.jsonl"
        newer = traces / "proj-b" / "sess-new.jsonl"
        older.parent.mkdir(parents=True)
        newer.parent.mkdir(parents=True)
        older.write_text("{}\n")
        newer.write_text("{}\n")
        newer.touch()
        import os
        import time

        old_time = time.time() - 100
        os.utime(older, (old_time, old_time))

        assert _preview._newest_trace_file() == newer
