"""The secrets store keeps its two files in the current Home, read at call time."""

from __future__ import annotations

import dataclasses
import time
from pathlib import Path

import pytest

from docket.governance import secrets
from docket.governance import secrets as _secrets
from docket.kernel.home import current_home, use_home

SUBJECT = "docket.governance.secrets"


def test_the_store_follows_the_current_home(tmp_path: Path) -> None:
    first, second = tmp_path / "first", tmp_path / "second"
    with use_home(dataclasses.replace(current_home(), root=first)):
        _secrets.save_secrets({"A_KEY": "one"})
        _secrets.touch_meta("A_KEY", "added")
    with use_home(dataclasses.replace(current_home(), root=second)):
        assert _secrets.load_secrets() == {}
        assert _secrets.load_secrets_meta() == {}
        _secrets.save_secrets({"B_KEY": "two"})
    assert (first / "secrets.json").exists() and (first / "secrets.meta.json").exists()
    assert (second / "secrets.json").exists() and not (second / "secrets.meta.json").exists()
    with use_home(dataclasses.replace(current_home(), root=first)):
        assert _secrets.secret_value("A_KEY") == "one"


class TestRedactPerformance:
    def test_long_alphanumeric_run_redacts_in_linear_time(self) -> None:
        text = "Z" * 40_000  # no secret shape present anywhere in this run
        start = time.perf_counter()
        secrets.redact(text)
        elapsed = time.perf_counter() - start
        assert elapsed < 0.5, f"redact() took {elapsed:.2f}s on a 40,000-char alnum run"


def test_an_env_sourced_credential_value_is_redacted(monkeypatch) -> None:
    """A key exported in the shell never rests in `secrets.json`, so the value itself must be
    on the redaction list, not only the `NAME=value` shape."""
    monkeypatch.setenv("DOCKET_LLM_API_KEY", "envsourcedvalue0123456789")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456789:AAbbccddeeffgghhiijjkkllmmnnooppqqrrss1")
    out = secrets.redact(
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
    assert bare not in secrets.redact(f"saw {bare} in output")


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
    out = secrets.redact(text)
    assert "[REDACTED]" in out
    assert leaked not in out


@pytest.mark.parametrize(
    ("text", "leaked"),
    [
        ("ghp_abcdefghijklmnopqrstuvwxyz0123456789", "abcdefghijklmnopqrstuvwxyz0123456789"),
        ("github_pat_11ABCDEFG0123456789_abcdefghijklmnop", "11ABCDEFG0123456789"),
        ("key id AKIAIOSFODNN7EXAMPLE here", "AKIAIOSFODNN7EXAMPLE"),
        ("DB_PASSWORD=hunter2hunter2", "hunter2hunter2"),
        (
            "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dBjftJeZ4CVPmB92K27uhbUJU1p1r",
            "eyJzdWIiOiIxMjM0NTY3ODkwIn0",
        ),
        (
            "-----BEGIN RSA PRIVATE KEY-----\nMIIEvQIBADAN\n-----END RSA PRIVATE KEY-----",
            "MIIEvQIBADAN",
        ),
        ("-----BEGIN PRIVATE KEY-----\nMIIEvQIBADAN, never closed", "-----BEGIN PRIVATE KEY"),
        ("Authorization: Bearer abc.def-ghi_jkl", "abc.def-ghi_jkl"),
    ],
)
def test_the_fixed_secret_shapes_are_masked(text: str, leaked: str) -> None:
    out = secrets.redact(text)

    assert "[REDACTED]" in out
    assert leaked not in out


def test_prose_that_only_mentions_the_words_is_left_alone() -> None:
    for text in ("reset the password policy", "an AKIA prefix is 4 letters", "Bearer of bad news"):
        assert secrets.redact(text) == text


def test_short_value_and_plain_text_are_left_alone() -> None:
    assert secrets.redact("value abc123 here") == "value abc123 here"
    assert secrets.redact('{"action": "edit"}') == '{"action": "edit"}'


class TestRedactionWordBoundary:
    """Redaction patterns must match only at word boundaries."""

    def test_task_field_is_not_redacted_as_a_secret(self) -> None:
        """task=... should not match task's 'sk' inside, or 'key' as part of 'task'."""
        text = "task=task-8d627c86-9a63-4379-beee-ee3b2afff6f7"
        assert secrets.redact(text) == text

    def test_risk_field_is_not_redacted_as_a_secret(self) -> None:
        """risk=... should not match the 'sk' in 'risk'."""
        text = "risk=" + "a" * 24
        assert secrets.redact(text) == text

    def test_api_key_with_underscore_is_redacted(self) -> None:
        """api_key=<value> should be redacted even with underscore."""
        text = "api_key=" + "A" * 24
        out = secrets.redact(text)
        assert "[REDACTED]" in out
        assert "A" * 24 not in out

    def test_key_after_colon_is_redacted(self) -> None:
        """key: <value> should be redacted (colon separator)."""
        text = "key: " + "A" * 24
        out = secrets.redact(text)
        assert "[REDACTED]" in out
        assert "A" * 24 not in out

    def test_bearer_token_is_redacted(self) -> None:
        """Bearer <value> should be redacted (space separator)."""
        text = "Bearer " + "A" * 24
        out = secrets.redact(text)
        assert "[REDACTED]" in out
        assert "A" * 24 not in out

    def test_tok_equals_is_redacted(self) -> None:
        """tok=<value> should be redacted."""
        text = "tok=" + "A" * 24
        out = secrets.redact(text)
        assert "[REDACTED]" in out
        assert "A" * 24 not in out
