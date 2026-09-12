"""`docket serve`'s periodic sweep: what it calls, in what order, and its effect.

core/trace.py's expire_old_traces() is tested in isolation by
test_trace_retention.py. This file pins the *wiring* -- that _run_sweeps calls
sweep_all then approval_sweep_expired, keeps going if one raises, and runs
once at startup -- and the retention *effect* that ordering exists to protect:
expire_old_traces only ever deletes an already-terminated trace, so a
stale-but-open trace must first receive sweep_all's synthetic session_end
before expiry can consider it eligible.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import docket.config as _cfg
from docket import serve
from docket.core import approval as _ap
from docket.core import trace as _trace

SUBJECT = "docket.serve"


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
        """Retention runs from session END, not from last activity."""
        # This trace is ancient and has NO session_end, so expiry alone would keep it
        # forever -- that is expire_old_traces' liveness rule and it is correct.
        # sweep_all terminates it, but the synthetic session_end it appends carries a
        # FRESH timestamp, so the trace's age resets and it survives this pass; it
        # becomes eligible one full retention window later. Deleting it the moment the
        # sweep first notices it would destroy the evidence of an abandoned session
        # exactly when someone would go looking for it, so this conservative behaviour
        # is deliberate: if this assertion ever flips, retention has started measuring
        # from last activity instead of session end.
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


class TestSweepWiring:
    """`_run_sweeps` calls both sweeps, in order, and survives either failing."""

    def test_run_sweeps_invokes_both(self, monkeypatch: pytest.MonkeyPatch) -> None:
        called: list[str] = []
        monkeypatch.setattr(_trace, "sweep_all", lambda: called.append("trace"))
        monkeypatch.setattr(_ap, "approval_sweep_expired", lambda: called.append("appr") or 0)
        serve._run_sweeps()
        assert called == ["trace", "appr"]

    def test_run_sweeps_best_effort(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _boom() -> None:
            raise RuntimeError("down")

        ok: list[str] = []
        monkeypatch.setattr(_trace, "sweep_all", _boom)
        monkeypatch.setattr(_ap, "approval_sweep_expired", lambda: ok.append("appr") or 0)
        serve._run_sweeps()
        assert ok == ["appr"]

    def test_run_serve_runs_sweeps_at_startup(self, monkeypatch: pytest.MonkeyPatch) -> None:
        ran: list[str] = []
        monkeypatch.setattr(serve, "_run_sweeps", lambda *_a: ran.append("startup"))

        class _FakeServer:
            def __init__(self, *_a: object, **_k: object) -> None:
                pass

            def serve_forever(self) -> None:
                raise KeyboardInterrupt

            def server_close(self) -> None:
                pass

        monkeypatch.setattr(serve, "ThreadingHTTPServer", _FakeServer)
        serve.run_serve(port=0, interval=30)
        assert ran == ["startup"]
