"""``docket metrics`` counts a dispatch's terminal task status, not a payload nothing writes."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from docket.cli import _metrics

SUBJECT = "docket.cli._metrics"


def _session(traces: Path, name: str, status: str) -> None:
    d = traces / "demo"
    d.mkdir(parents=True, exist_ok=True)
    events = [
        {"event_type": "session_start", "ts": "2026-10-01T10:00:00Z", "agent_role": "lead"},
        {
            "event_type": "session_end",
            "ts": "2026-10-01T10:00:05Z",
            "agent_role": "lead",
            "payload": {"status": status},
        },
    ]
    (d / f"{name}.jsonl").write_text("\n".join(json.dumps(e) for e in events) + "\n")


class TestTerminalTaskCounts:
    def test_dispatch_statuses_are_counted(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _session(tmp_path, "a", "done")
        _session(tmp_path, "b", "failed")
        _session(tmp_path, "c", "cancelled")

        _metrics._compute_and_print(str(tmp_path), "", "", 50)

        out = capsys.readouterr().out
        assert "1 success / 1 failure / 1 aborted" in out

    def test_a_parked_task_is_not_terminal(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _session(tmp_path, "a", "done")
        _session(tmp_path, "b", "waiting_input")

        _metrics._compute_and_print(str(tmp_path), "", "", 50)

        out = capsys.readouterr().out
        assert "1 success / 0 failure / 0 aborted" in out
        assert "window: 1 terminal" in out
