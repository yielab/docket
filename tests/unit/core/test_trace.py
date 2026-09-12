"""Secret-shape redaction (core/trace.py) -- pure-logic unit tests."""

from __future__ import annotations

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
