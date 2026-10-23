"""trace + audit.

Both subsystems read paths from current_home() at call time, so each test runs in a
`use_home` block on a temp seed (traces_dir, audit_log, session_timeout) and drives the public
surfaces in-process.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from docket.governance import audit as audit_core
from docket.interfaces.cli.commands import log as audit_cli
from docket.kernel import clock as _clock
from docket.kernel.home import Home, current_home, use_home
from docket.observability import trace as trace_core

SUBJECT = "docket.governance"


@pytest.fixture()
def oc_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Temp DOCKET_HOME with config paths repointed for trace + audit."""
    d = tmp_path / ".docket"
    d.mkdir()
    with use_home(Home(d)), use_home(dataclasses.replace(current_home(), session_timeout=3600)):
        monkeypatch.delenv("DOCKET_NO_TRACE", raising=False)
        monkeypatch.delenv("DOCKET_NO_AUDIT", raising=False)
        yield d


# ── audit ────────────────────────────────────────────────────────────────────────


class TestAudit:
    def test_append_creates_log_0600(self, oc_dir: Path) -> None:
        audit_core.audit_log("keys.add", "ANTHROPIC_API_KEY")
        logf = oc_dir / "audit.log"
        assert logf.is_file()
        assert (logf.stat().st_mode & 0o777) == 0o600
        entries = audit_core.read_audit()
        assert len(entries) == 1
        e = entries[0]
        assert e["action"] == "keys.add"
        assert e["detail"] == "ANTHROPIC_API_KEY"
        assert e["ts"].endswith("Z")
        assert e["user"]
        assert isinstance(e["pid"], int)

    def test_append_appends_in_order(self, oc_dir: Path) -> None:
        audit_core.audit_log("gates.enable", "")
        audit_core.audit_log("agent.delete", "myshop")
        actions = [e["action"] for e in audit_core.read_audit()]
        assert actions == ["gates.enable", "agent.delete"]

    def test_no_audit_env_no_longer_disables(
        self, oc_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """DOCKET_NO_AUDIT has no effect: audit recording is best-effort but can never be
        silently switched off by an unauthenticated env var."""
        monkeypatch.setenv("DOCKET_NO_AUDIT", "1")
        audit_core.audit_log("keys.add", "X")
        assert (oc_dir / "audit.log").exists()
        entries = audit_core.read_audit()
        assert len(entries) == 1
        assert entries[0]["action"] == "keys.add"

    def test_missing_dir_is_created(self, tmp_path: Path) -> None:
        """A missing AUDIT_LOG parent means "first-ever docket write", not "docket isn't
        installed": nothing external bootstraps DOCKET_HOME, so audit_log must create its own
        parent directory, or the log would silently lose its first entry on a fresh ~/.docket."""
        with use_home(Home(tmp_path / "fresh")):
            audit_core.audit_log("keys.add", "X")  # must not raise
            logf = tmp_path / "fresh" / "audit.log"
            assert logf.is_file()
            assert audit_core.read_audit()[0]["action"] == "keys.add"

    def test_run_audit_no_log(self, oc_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
        rc = audit_cli.show_log()
        out = capsys.readouterr().out
        assert rc == 0
        assert "No log yet." in out

    def test_run_audit_show_and_limit(
        self, oc_dir: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        for i in range(5):
            audit_core.audit_log("keys.add", f"KEY_{i}")
        rc = audit_cli.show_log(limit=2)
        out = capsys.readouterr().out
        assert rc == 0
        assert "last 2 change(s)" in out
        assert "KEY_4" in out
        assert "KEY_3" in out
        assert "KEY_0" not in out

    def test_run_audit_json_passthrough(
        self, oc_dir: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        audit_core.audit_log("scope.set", "myshop")
        rc = audit_cli.show_log(json_out=True)
        out = capsys.readouterr().out
        assert rc == 0
        parsed = [json.loads(line) for line in out.splitlines() if line.strip()]
        assert parsed[0]["action"] == "scope.set"


# ── trace: record / list ─────────────────────────────────────────────────────────


class TestTraceRecord:
    def test_record_creates_session_file_0600(self, oc_dir: Path) -> None:
        ok = trace_core.trace_event(
            "myshop", "sess1", "programmer", "tool_call", '{"action": "edit"}'
        )
        assert ok == "written"
        tf = oc_dir / "traces" / "myshop" / "sess1.jsonl"
        assert tf.is_file()
        assert (tf.stat().st_mode & 0o777) == 0o600
        records = trace_core.read_trace(tf)
        assert len(records) == 1
        assert records[0]["event_type"] == "tool_call"
        assert records[0]["payload"] == {"action": "edit"}
        assert records[0]["agent_role"] == "programmer"

    def test_record_invalid_event_rejected(self, oc_dir: Path) -> None:
        ok = trace_core.trace_event("myshop", "s", "r", "not_a_type", "{}")
        assert ok == "rejected"
        assert not (oc_dir / "traces" / "myshop").exists()

    def test_record_non_json_payload_wrapped(self, oc_dir: Path) -> None:
        trace_core.trace_event("p", "s", "r", "error", "boom happened")
        rec = trace_core.read_trace(oc_dir / "traces" / "p" / "s.jsonl")[0]
        assert rec["payload"] == {"text": "boom happened"}

    def test_record_redacts_secret_shapes(self, oc_dir: Path) -> None:
        trace_core.trace_event(
            "p", "s", "r", "tool_call", "api_key=sk-ant-abcdefghijklmnopqrstuvwxyz0123"
        )
        rec = trace_core.read_trace(oc_dir / "traces" / "p" / "s.jsonl")[0]
        assert "[REDACTED]" in rec["payload"]["text"]
        assert "sk-ant-abcdefghijklmnopqrstuvwxyz0123" not in rec["payload"]["text"]

    def test_record_cost_and_duration(self, oc_dir: Path) -> None:
        trace_core.trace_event(
            "p", "s", "r", "cost_charged", "{}", cost_usd="0.5", duration_ms="120"
        )
        rec = trace_core.read_trace(oc_dir / "traces" / "p" / "s.jsonl")[0]
        assert rec["cost_usd"] == 0.5
        assert rec["duration_ms"] == 120

    def test_no_trace_env_disables(self, oc_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """A suppressed write is now distinguishable from a real one."""
        monkeypatch.setenv("DOCKET_NO_TRACE", "1")
        assert trace_core.trace_event("p", "s", "r", "tool_call", "{}") == "suppressed"
        assert not (oc_dir / "traces").exists()


# ── trace: sweep ──────────────────────────────────────────────────────────────────


class TestTraceSweep:
    def test_sweep_closes_stale_open_trace(self, oc_dir: Path) -> None:
        with use_home(dataclasses.replace(current_home(), session_timeout=1)):
            pdir = oc_dir / "traces" / "myshop"
            pdir.mkdir(parents=True)
            (pdir / "stale.jsonl").write_text(
                json.dumps(
                    {"ts": "2000-01-01T00:00:00Z", "event_type": "tool_call", "project": "myshop"}
                )
                + "\n"
            )
            trace_core.sweep_all()
            types = [r["event_type"] for r in trace_core.read_trace(pdir / "stale.jsonl")]
            assert types[-1] == "session_end"

    def test_sweep_leaves_closed_trace(self, oc_dir: Path) -> None:
        with use_home(dataclasses.replace(current_home(), session_timeout=1)):
            pdir = oc_dir / "traces" / "myshop"
            pdir.mkdir(parents=True)
            (pdir / "done.jsonl").write_text(
                json.dumps({"ts": "2000-01-01T00:00:00Z", "event_type": "session_end"}) + "\n"
            )
            trace_core.sweep_all()
            types = [r["event_type"] for r in trace_core.read_trace(pdir / "done.jsonl")]
            assert types == ["session_end"]

    def test_sweep_leaves_fresh_trace(self, oc_dir: Path) -> None:
        pdir = oc_dir / "traces" / "myshop"
        pdir.mkdir(parents=True)
        recent = _clock.stamp()
        (pdir / "fresh.jsonl").write_text(
            json.dumps({"ts": recent, "event_type": "tool_call"}) + "\n"
        )
        trace_core.sweep_all()
        types = [r["event_type"] for r in trace_core.read_trace(pdir / "fresh.jsonl")]
        assert types == ["tool_call"]
