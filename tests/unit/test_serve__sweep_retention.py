"""`docket serve`'s periodic sweep actually runs trace retention.

core/trace.py's expire_old_traces() is tested in isolation by
test_trace_retention.py. This file pins the *wiring*: that serve.py's
_run_sweeps calls it at all, and that it calls it AFTER sweep_all.

The ordering is the part worth a test rather than a comment. expire_old_traces
only ever deletes an already-terminated trace, so a stale-but-open trace must
first receive sweep_all's synthetic session_end before expiry can consider it.
Wire them the other way round and nothing fails loudly -- every stale-open
trace simply waits an extra sweep interval to become eligible, which is the
kind of silent latency bug that survives for months.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import docket.config as _cfg
from docket import serve


@pytest.fixture()
def swept_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Temp DOCKET_HOME with the sweep's paths and windows repointed."""
    d = tmp_path / ".docket"
    d.mkdir()
    monkeypatch.setattr(_cfg, "DOCKET_HOME", d, raising=True)
    monkeypatch.setattr(_cfg, "TRACES_DIR", d / "traces", raising=True)
    monkeypatch.setattr(_cfg, "AUDIT_LOG", d / "audit.log", raising=True)
    monkeypatch.setattr(_cfg, "APPROVALS_DIR", d / "approvals", raising=True)
    monkeypatch.setattr(_cfg, "SESSIONS_DIR", d / "sessions", raising=True)
    monkeypatch.setattr(_cfg, "SESSION_TIMEOUT", 3600, raising=True)
    monkeypatch.setattr(_cfg, "TRACE_RETENTION_DAYS", 30, raising=True)
    monkeypatch.setattr(_cfg, "TRACE_RETENTION_S", 30 * 86400, raising=True)
    monkeypatch.delenv("DOCKET_NO_TRACE", raising=False)
    return d


def _write_trace(pdir: Path, name: str, lines: list[dict[str, object]]) -> Path:
    pdir.mkdir(parents=True, exist_ok=True)
    tf = pdir / f"{name}.jsonl"
    tf.write_text("\n".join(json.dumps(r) for r in lines) + "\n", encoding="utf-8")
    return tf


class TestSweepRunsRetention:
    def test_sweep_expires_an_old_terminated_trace(self, swept_home: Path) -> None:
        pdir = swept_home / "traces" / "myshop"
        tf = _write_trace(
            pdir,
            "ancient",
            [
                {"ts": "2000-01-01T00:00:00Z", "event_type": "session_start"},
                {"ts": "2000-01-01T00:05:00Z", "event_type": "session_end"},
            ],
        )

        serve._run_sweeps()

        assert not tf.exists()

    def test_sweep_keeps_a_recent_terminated_trace(self, swept_home: Path) -> None:
        import datetime as dt

        now = dt.datetime.now(dt.UTC)
        pdir = swept_home / "traces" / "myshop"
        tf = _write_trace(
            pdir,
            "fresh",
            [
                {"ts": now.isoformat(), "event_type": "session_start"},
                {"ts": now.isoformat(), "event_type": "session_end"},
            ],
        )

        serve._run_sweeps()

        assert tf.exists()

    def test_stale_open_trace_is_terminated_but_not_expired_in_the_same_sweep(
        self, swept_home: Path
    ) -> None:
        """Retention runs from session END, not from last activity.

        This trace is ancient and has NO session_end, so expiry alone would
        keep it forever -- that is expire_old_traces' liveness rule and it is
        correct. sweep_all terminates it, but the synthetic session_end it
        appends carries a FRESH _now_iso() timestamp, so the trace's age
        immediately resets and it survives this pass. It becomes eligible one
        full retention window later.

        Worth pinning because the intuitive reading is the opposite: an
        operator seeing a year-old abandoned trace would expect it deleted on
        sight. Deleting it at the moment the sweep first notices it would
        destroy the evidence of an abandoned session exactly when someone
        would go looking for it, so the conservative behaviour is deliberate.
        If this assertion ever flips, retention has started measuring from
        last activity and abandoned sessions are being deleted on discovery.
        """
        pdir = swept_home / "traces" / "myshop"
        tf = _write_trace(
            pdir,
            "stale-open",
            [
                {"ts": "2000-01-01T00:00:00Z", "event_type": "session_start"},
                {"ts": "2000-01-01T00:05:00Z", "event_type": "tool_call"},
            ],
        )

        serve._run_sweeps()

        assert tf.exists()
        records = [json.loads(ln) for ln in tf.read_text(encoding="utf-8").splitlines() if ln]
        assert records[-1]["event_type"] == "session_end"
        assert records[-1]["payload"]["status"] == "aborted"

    def test_sweep_never_touches_the_audit_log(self, swept_home: Path) -> None:
        """Retention is telemetry-only; the audit log is not sampled or expired."""
        audit = swept_home / "audit.log"
        audit.write_text("seed-entry\n", encoding="utf-8")
        pdir = swept_home / "traces" / "myshop"
        _write_trace(
            pdir,
            "ancient",
            [
                {"ts": "2000-01-01T00:00:00Z", "event_type": "session_start"},
                {"ts": "2000-01-01T00:05:00Z", "event_type": "session_end"},
            ],
        )

        serve._run_sweeps()

        assert audit.read_text(encoding="utf-8") == "seed-entry\n"
