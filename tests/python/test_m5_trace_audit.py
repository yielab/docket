"""M5 T5.4a tests: trace + audit.

Both subsystems read paths from docket.config at call time, so we repoint the
already-imported config attributes (TRACES_DIR, AUDIT_LOG, OPENCLAW_DIR,
SESSION_TIMEOUT) at a temp seed and drive the public surfaces in-process.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import docket.config as _cfg
from docket.cli import _audit as audit_cli
from docket.cli import _trace as trace_cli
from docket.core import audit as audit_core
from docket.core import trace as trace_core


@pytest.fixture()
def oc_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Temp ~/.openclaw with config paths repointed for trace + audit."""
    d = tmp_path / ".openclaw"
    d.mkdir()
    monkeypatch.setattr(_cfg, "OPENCLAW_DIR", d, raising=True)
    monkeypatch.setattr(_cfg, "DOCKET_HOME", d, raising=True)
    monkeypatch.setattr(_cfg, "TRACES_DIR", d / "traces", raising=True)
    monkeypatch.setattr(_cfg, "AUDIT_LOG", d / "audit.log", raising=True)
    monkeypatch.setattr(_cfg, "SESSION_TIMEOUT", 3600, raising=True)
    monkeypatch.delenv("DOCKET_NO_TRACE", raising=False)
    monkeypatch.delenv("DOCKET_NO_AUDIT", raising=False)
    return d


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

    def test_no_audit_env_disables(self, oc_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DOCKET_NO_AUDIT", "1")
        audit_core.audit_log("keys.add", "X")
        assert not (oc_dir / "audit.log").exists()

    def test_missing_dir_noop(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_cfg, "AUDIT_LOG", tmp_path / "nope" / "audit.log", raising=True)
        audit_core.audit_log("keys.add", "X")  # must not raise
        assert not (tmp_path / "nope").exists()

    def test_run_audit_no_log(self, oc_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
        rc = audit_cli.run_audit()
        out = capsys.readouterr().out
        assert rc == 0
        assert "No audit log yet." in out

    def test_run_audit_show_and_limit(
        self, oc_dir: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        for i in range(5):
            audit_core.audit_log("keys.add", f"KEY_{i}")
        rc = audit_cli.run_audit(limit=2)
        out = capsys.readouterr().out
        assert rc == 0
        assert "Audit log — last 2 change(s)" in out
        assert "KEY_4" in out
        assert "KEY_3" in out
        assert "KEY_0" not in out

    def test_run_audit_json_passthrough(
        self, oc_dir: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        audit_core.audit_log("scope.set", "myshop")
        rc = audit_cli.run_audit(json_out=True)
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
        assert ok is True
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
        assert ok is False
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
        monkeypatch.setenv("DOCKET_NO_TRACE", "1")
        assert trace_core.trace_event("p", "s", "r", "tool_call", "{}") is True
        assert not (oc_dir / "traces").exists()

    def test_show_renders_events(self, oc_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
        trace_core.trace_event("myshop", "abc", "programmer", "session_start", "{}")
        trace_core.trace_event("myshop", "abc", "programmer", "tool_call", '{"action": "edit"}')
        rc = trace_cli.run_trace("abc")
        out = capsys.readouterr().out
        assert rc == 0
        assert "Trace: abc" in out
        assert "session_start" in out
        assert "tool_call" in out
        assert "action=edit" in out

    def test_show_missing_session(self, oc_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
        rc = trace_cli.run_trace("ghost")
        assert rc == 1

    def test_export_passthrough_and_since(
        self, oc_dir: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # Write two events with known ts directly so the since filter is deterministic.
        pdir = oc_dir / "traces" / "myshop"
        pdir.mkdir(parents=True)
        (pdir / "s.jsonl").write_text(
            json.dumps({"ts": "2020-01-01T00:00:00Z", "event_type": "tool_call"})
            + "\n"
            + json.dumps({"ts": "2026-01-01T00:00:00Z", "event_type": "tool_result"})
            + "\n"
        )
        rc = trace_cli.run_trace("export", "myshop")
        out = capsys.readouterr().out
        assert rc == 0
        assert len([line for line in out.splitlines() if line.strip()]) == 2

        rc = trace_cli.run_trace("export", "myshop", since="2025-01-01")
        out = capsys.readouterr().out
        lines = [line for line in out.splitlines() if line.strip()]
        assert len(lines) == 1
        assert "2026-01-01" in lines[0]

    def test_export_missing_project(self, oc_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
        rc = trace_cli.run_trace("export", "nope")
        assert rc == 1

    def test_help_default(self, oc_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
        rc = trace_cli.run_trace()
        out = capsys.readouterr().out
        assert rc == 0
        assert "docket trace" in out


# ── trace: ingest + sweep ─────────────────────────────────────────────────────────


def _seed_daemon_session(oc_dir: Path, project: str, session: str, lines: list[dict]) -> Path:
    sdir = oc_dir / "agents" / project / "sessions"
    sdir.mkdir(parents=True, exist_ok=True)
    f = sdir / f"{session}.jsonl"
    f.write_text("".join(json.dumps(line) + "\n" for line in lines))
    return f


class TestTraceIngest:
    def test_ingest_projects_turns(self, oc_dir: Path) -> None:
        now = trace_core._now_iso()
        _seed_daemon_session(
            oc_dir,
            "myshop",
            "sess1",
            [
                {"type": "message", "timestamp": now, "id": "m1"},
                {"type": "tool_use", "timestamp": now, "id": "t1"},
                {"type": "tool_result", "timestamp": now, "id": "t1"},
            ],
        )
        trace_core.trace_ingest("myshop")
        tf = oc_dir / "traces" / "myshop" / "sess1.jsonl"
        assert tf.is_file()
        types = [r["event_type"] for r in trace_core.read_trace(tf)]
        # session_start + tool_call + tool_result (message is not projected).
        assert types == ["session_start", "tool_call", "tool_result"]

    def test_ingest_idempotent(self, oc_dir: Path) -> None:
        _seed_daemon_session(
            oc_dir,
            "myshop",
            "sess1",
            [{"type": "tool_use", "timestamp": trace_core._now_iso(), "id": "t1"}],
        )
        trace_core.trace_ingest("myshop")
        trace_core.trace_ingest("myshop")
        tf = oc_dir / "traces" / "myshop" / "sess1.jsonl"
        types = [r["event_type"] for r in trace_core.read_trace(tf)]
        assert types == ["session_start", "tool_call"]
        idx = json.loads((oc_dir / "traces" / "myshop" / ".ingest-index.json").read_text())
        assert idx["sess1"] == 1

    def test_ingest_incremental(self, oc_dir: Path) -> None:
        now = trace_core._now_iso()
        src = _seed_daemon_session(
            oc_dir,
            "myshop",
            "sess1",
            [{"type": "tool_use", "timestamp": now, "id": "t1"}],
        )
        trace_core.trace_ingest("myshop")
        with src.open("a") as f:
            f.write(json.dumps({"type": "tool_result", "timestamp": now}) + "\n")
        trace_core.trace_ingest("myshop")
        tf = oc_dir / "traces" / "myshop" / "sess1.jsonl"
        types = [r["event_type"] for r in trace_core.read_trace(tf)]
        assert types == ["session_start", "tool_call", "tool_result"]

    def test_ingest_timeout_session_end(
        self, oc_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(_cfg, "SESSION_TIMEOUT", 1, raising=True)
        _seed_daemon_session(
            oc_dir,
            "myshop",
            "old",
            [{"type": "tool_use", "timestamp": "2000-01-01T00:00:00Z", "id": "t1"}],
        )
        trace_core.trace_ingest("myshop")
        tf = oc_dir / "traces" / "myshop" / "old.jsonl"
        types = [r["event_type"] for r in trace_core.read_trace(tf)]
        assert types[-1] == "session_end"
        assert trace_core.read_trace(tf)[-1]["payload"]["status"] == "aborted"

    def test_ingest_missing_dir_noop(self, oc_dir: Path) -> None:
        trace_core.trace_ingest("ghost")  # must not raise
        assert not (oc_dir / "traces" / "ghost").exists()

    def test_run_trace_ingest_command(
        self, oc_dir: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _seed_daemon_session(
            oc_dir,
            "myshop",
            "sess1",
            [{"type": "tool_use", "timestamp": trace_core._now_iso(), "id": "t1"}],
        )
        rc = trace_cli.run_trace("ingest", "myshop")
        out = capsys.readouterr().out
        assert rc == 0
        assert "Ingest complete" in out
        assert (oc_dir / "traces" / "myshop" / "sess1.jsonl").is_file()


class TestTraceSweep:
    def test_sweep_closes_stale_open_trace(
        self, oc_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(_cfg, "SESSION_TIMEOUT", 1, raising=True)
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

    def test_sweep_leaves_closed_trace(self, oc_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_cfg, "SESSION_TIMEOUT", 1, raising=True)
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
        recent = trace_core._now_iso()
        (pdir / "fresh.jsonl").write_text(
            json.dumps({"ts": recent, "event_type": "tool_call"}) + "\n"
        )
        trace_core.sweep_all()
        types = [r["event_type"] for r in trace_core.read_trace(pdir / "fresh.jsonl")]
        assert types == ["tool_call"]
