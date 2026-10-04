"""Corrections ledger: deny reasons, REQUEST-CHANGES texts, declined answers."""

from __future__ import annotations

import json as _json
from typing import Any

import pytest

import docket.config as _cfg
from docket.core import corrections as _corrections

SUBJECT = "docket.core.corrections"


@pytest.fixture
def iso_now() -> str:
    """Sample ISO timestamp."""
    return "2026-10-04T14:30:45"


class TestRecord:
    """corrections.record() appends one JSON line to the ledger."""

    def test_record_appends_deny_reason(self, iso_now: str) -> None:
        """A deny reason is recorded with all fields."""
        project = "test-proj"
        _corrections.record(
            project,
            "deny_reason",
            task_id="task-123",
            role="reviewer",
            text="Needs more testing",
            source="cli",
            _now=iso_now,
        )

        path = _cfg.CORRECTIONS_DIR / f"{project}.jsonl"
        assert path.exists()
        lines = path.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 1

        record = _json.loads(lines[0])
        assert record["kind"] == "deny_reason"
        assert record["taskId"] == "task-123"
        assert record["role"] == "reviewer"
        assert record["text"] == "Needs more testing"
        assert record["source"] == "cli"
        assert record["ts"] == iso_now

    def test_record_appends_request_changes(self, iso_now: str) -> None:
        """A REQUEST-CHANGES text is recorded."""
        project = "test-proj-2"
        _corrections.record(
            project,
            "request_changes",
            task_id="task-456",
            role="reviewer",
            text="Please add error handling",
            source="reviewer",
            _now=iso_now,
        )

        path = _cfg.CORRECTIONS_DIR / f"{project}.jsonl"
        lines = path.read_text(encoding="utf-8").strip().split("\n")
        record = _json.loads(lines[0])
        assert record["kind"] == "request_changes"
        assert record["text"] == "Please add error handling"

    def test_record_appends_declined_answer(self, iso_now: str) -> None:
        """A declined answer is recorded."""
        project = "test-proj-3"
        _corrections.record(
            project,
            "declined_answer",
            task_id="task-789",
            role="operator",
            text="(declined)",
            source="answer",
            _now=iso_now,
        )

        path = _cfg.CORRECTIONS_DIR / f"{project}.jsonl"
        lines = path.read_text(encoding="utf-8").strip().split("\n")
        record = _json.loads(lines[0])
        assert record["kind"] == "declined_answer"

    def test_record_file_permissions(self, iso_now: str) -> None:
        """New correction file is created with 0600 permissions."""
        project = "test-proj-4"
        _corrections.record(
            project,
            "deny_reason",
            task_id="task-1",
            role="reviewer",
            text="Denied",
            source="cli",
            _now=iso_now,
        )

        path = _cfg.CORRECTIONS_DIR / f"{project}.jsonl"
        mode = path.stat().st_mode & 0o777
        assert mode == 0o600

    def test_record_text_redacted(self, iso_now: str) -> None:
        """Sensitive text in reason is redacted."""
        project = "test-proj-5"
        _corrections.record(
            project,
            "deny_reason",
            task_id="task-1",
            role="reviewer",
            text="env var DB_API_KEY=sk-ant-abcdefghijklmnopqrstuvwxyz0123456789 found",
            source="cli",
            _now=iso_now,
        )

        path = _cfg.CORRECTIONS_DIR / f"{project}.jsonl"
        record = _json.loads(path.read_text(encoding="utf-8").strip().split("\n")[0])
        assert "[REDACTED]" in record["text"]
        assert "sk-ant-" not in record["text"]

    def test_record_text_tail_bounded(self, iso_now: str) -> None:
        """Long text is tail-bounded to 4000 chars."""
        project = "test-proj-6"
        long_text = "x" * 5000
        _corrections.record(
            project,
            "request_changes",
            task_id="task-1",
            role="reviewer",
            text=long_text,
            source="reviewer",
            _now=iso_now,
        )

        path = _cfg.CORRECTIONS_DIR / f"{project}.jsonl"
        record = _json.loads(path.read_text(encoding="utf-8").strip().split("\n")[0])
        assert len(record["text"]) <= 4000

    def test_record_write_failure_does_not_raise(
        self, iso_now: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A failed write (OSError) is caught and logged, does not raise."""

        def raise_oserror(*args: Any, **kwargs: Any) -> None:
            raise OSError("Permission denied")

        monkeypatch.setattr("builtins.open", raise_oserror)
        # Should not raise, just log to stderr
        _corrections.record(
            "test-proj-7",
            "deny_reason",
            task_id="task-1",
            role="reviewer",
            text="Test",
            source="cli",
            _now=iso_now,
        )

    def test_multiple_records_same_file(self, iso_now: str) -> None:
        """Multiple records append to the same file."""
        project = "test-proj-8"
        for i in range(3):
            _corrections.record(
                project,
                "deny_reason",
                task_id=f"task-{i}",
                role="reviewer",
                text=f"Reason {i}",
                source="cli",
                _now=iso_now,
            )

        path = _cfg.CORRECTIONS_DIR / f"{project}.jsonl"
        lines = path.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 3


class TestRead:
    """corrections.read() returns the list of records."""

    def test_read_empty_when_missing(self) -> None:
        """Read returns empty list if file doesn't exist."""
        records = _corrections.read("nonexistent-proj")
        assert records == []

    def test_read_existing_records(self, iso_now: str) -> None:
        """Read returns all records from file."""
        project = "test-proj"
        _corrections.record(
            project,
            "deny_reason",
            task_id="task-1",
            role="reviewer",
            text="Reason 1",
            source="cli",
            _now=iso_now,
        )
        _corrections.record(
            project,
            "request_changes",
            task_id="task-2",
            role="reviewer",
            text="Reason 2",
            source="reviewer",
            _now=iso_now,
        )

        records = _corrections.read(project)
        assert len(records) == 2
        assert records[0]["kind"] == "deny_reason"
        assert records[1]["kind"] == "request_changes"

    def test_read_preserves_order(self, iso_now: str) -> None:
        """Records are returned in append order."""
        project = "test-proj"
        for i in range(5):
            _corrections.record(
                project,
                "deny_reason",
                task_id=f"task-{i}",
                role="reviewer",
                text=f"Reason {i}",
                source="cli",
                _now=iso_now,
            )

        records = _corrections.read(project)
        for i, record in enumerate(records):
            assert record["taskId"] == f"task-{i}"
