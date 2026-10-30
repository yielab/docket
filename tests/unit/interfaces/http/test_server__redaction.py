"""Approval lifecycle trace events, and secret redaction in trace/approval data.

An approval's own action text and any stored secret value found in a trace
payload must never reach the trace log or the approval record verbatim.
Fixtures run in a `use_home` block on a temp seed and drive governance.approval/observability.trace
directly, in-process.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from docket.governance import approval as _ap
from docket.governance import secrets as _secrets
from docket.kernel.home import Home, current_home, use_home
from docket.observability import trace as _trace

SUBJECT = "docket.interfaces.http.server"


@pytest.fixture()
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Temp DOCKET_HOME with all docket-owned store paths repointed."""
    d = tmp_path / ".docket"
    d.mkdir()
    (d / "state").mkdir(parents=True, exist_ok=True)
    (d / "state" / "fleet.json").write_text(json.dumps({"agents": [], "bindings": []}))
    with use_home(Home(d)), use_home(dataclasses.replace(current_home(), approval_timeout=900)):
        monkeypatch.delenv("DOCKET_NO_TRACE", raising=False)
        monkeypatch.delenv("DOCKET_SECRETS_BACKEND", raising=False)
        yield d


# ── approval lifecycle emits trace events, action text redacted ────────────────


class TestApprovalTrace:
    def _events_for(self, home: Path, project: str) -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        for tf in (home / "state" / "traces" / project).glob("*.jsonl"):
            events.extend(_trace.read_trace(tf))
        return events

    def test_grant_emits_approval_granted(self, home: Path) -> None:
        token = _ap.approval_create("myshop", "programmer", "ship it")
        _ap.approval_grant(token)
        events = self._events_for(home, "myshop")
        grants = [e for e in events if e["event_type"] == "approval_granted"]
        assert len(grants) == 1
        assert grants[0]["payload"] == {"token": token}

    def test_deny_emits_approval_denied(self, home: Path) -> None:
        token = _ap.approval_create("myshop", "reviewer", "nope")
        _ap.approval_deny(token)
        events = self._events_for(home, "myshop")
        denies = [e for e in events if e["event_type"] == "approval_denied"]
        assert len(denies) == 1
        assert denies[0]["payload"] == {"token": token}

    def test_action_is_redacted_in_the_record(self, home: Path) -> None:
        action = "deploy with ANTHROPIC_API_KEY=sk-ant-abcdefghijklmnopqrstuvwxyz123456"
        token = _ap.approval_create("myshop", "programmer", action)
        rec = _ap.approval_get(token)
        assert "sk-ant-abcdefghijklmnopqrstuvwxyz123456" not in rec["action"]
        assert "[REDACTED]" in rec["action"]

    def test_trace_failure_never_breaks_approval(
        self, home: Path, monkeypatch: pytest.MonkeyPatch, real_tracer_except: Callable[..., None]
    ) -> None:
        def _boom(*_a: object, **_k: object) -> bool:
            raise RuntimeError("trace store down")

        monkeypatch.setattr(_trace, "trace_event", _boom, raising=True)
        real_tracer_except(trace_event=_boom)
        token = _ap.approval_create("myshop", "programmer", "still works")
        assert token.startswith("apr-")
        assert _ap.approval_get(token)["state"] == "pending"


# ── trace.redact strips a stored secret's value, not just its shape ────────────


class TestStoredSecretRedaction:
    def test_redacts_stored_secret_value(self, home: Path) -> None:
        # File-backend secrets.json maps KEY -> value.
        secret = "supersecretvalue1234567890"
        (home / "state" / "secrets.json").write_text(json.dumps({"MY_TOKEN": secret}))
        out = _secrets.redact(f"the token is {secret} ok")
        assert secret not in out
        assert "[REDACTED]" in out

    def test_short_stored_value_not_redacted(self, home: Path) -> None:
        # redact.sh only redacts stored values longer than 8 chars.
        (home / "state" / "secrets.json").write_text(json.dumps({"SHORT": "abc123"}))
        assert _secrets.redact("value abc123 here") == "value abc123 here"

    def test_redaction_in_trace_event(self, home: Path) -> None:
        secret = "anothersecretvalue0987654321"
        (home / "state" / "secrets.json").write_text(json.dumps({"K": secret}))
        _trace.trace_event("p", "s", "r", "tool_call", json.dumps({"text": f"x {secret} y"}))
        events = _trace.read_trace(home / "state" / "traces" / "p" / "s.jsonl")
        assert secret not in json.dumps(events)
