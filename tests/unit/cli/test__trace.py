"""`docket trace <session>` rendering of one trace event."""

from __future__ import annotations

import pytest

from docket.cli import _trace

SUBJECT = "docket.cli._trace"


class TestRenderEvent:
    def test_model_text_with_markup_tags_prints_literally(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Model-written text is data: brackets survive and a stray closing tag cannot crash."""
        text = "ok [/bold] then [red]x[/red] for [task-1]"
        _trace._render_event(
            {
                "ts": "2026-01-01T00:00:00Z",
                "event_type": "tool_result",
                "agent_role": "reviewer",
                "payload": {"text": text},
                "cost_usd": 0.5,
            }
        )

        out = capsys.readouterr().out
        assert f"(reviewer)  text={text}" in out
        assert "[$0.5000]" in out
