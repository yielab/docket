"""`docket start`'s periodic sweep: what it calls, in what order, and its effect.

observability/trace.py's expire_old_traces() is tested in isolation by
test_trace_retention.py. This file pins the *wiring* -- that _run_sweeps calls
sweep_all then approval_sweep_expired, keeps going if one raises, and runs
once at startup -- and the retention *effect* that ordering exists to protect:
expire_old_traces only ever deletes an already-terminated trace, so a
stale-but-open trace must first receive sweep_all's synthetic session_end
before expiry can consider it eligible.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from tests.support.trace import write_trace as _write_trace

from docket.governance import approval as _ap
from docket.interfaces.http import server as _server
from docket.interfaces.http import sweeps as _sweeps
from docket.kernel import threads as _threads
from docket.kernel.home import Home, current_home, use_home
from docket.observability import trace as _trace

SUBJECT = "docket.interfaces.http.server"


@pytest.fixture()
def swept_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Temp DOCKET_HOME with the sweep's paths and windows repointed."""
    d = tmp_path / ".docket"
    d.mkdir()
    with (
        use_home(Home(d)),
        use_home(
            dataclasses.replace(current_home(), session_timeout=3600, trace_retention_days=30)
        ),
    ):
        monkeypatch.delenv("DOCKET_NO_TRACE", raising=False)
        yield d


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

        _server._run_sweeps()

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

        _server._run_sweeps()

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

        _server._run_sweeps()

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

        _server._run_sweeps()

        assert audit.read_text(encoding="utf-8") == "seed-entry\n"


class TestSweepWiring:
    """`_run_sweeps` calls both sweeps, in order, and survives either failing."""

    def test_run_sweeps_invokes_both(self, monkeypatch: pytest.MonkeyPatch) -> None:
        called: list[str] = []
        monkeypatch.setattr(_trace, "sweep_all", lambda: called.append("trace"))
        monkeypatch.setattr(_ap, "approval_sweep_expired", lambda: called.append("appr") or 0)
        _server._run_sweeps()
        assert called == ["trace", "appr"]

    def test_run_sweeps_best_effort(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _boom() -> None:
            raise RuntimeError("down")

        ok: list[str] = []
        monkeypatch.setattr(_trace, "sweep_all", _boom)
        monkeypatch.setattr(_ap, "approval_sweep_expired", lambda: ok.append("appr") or 0)
        _server._run_sweeps()
        assert ok == ["appr"]

    def test_run_serve_runs_sweeps_at_startup(self, monkeypatch: pytest.MonkeyPatch) -> None:
        ran: list[str] = []
        monkeypatch.setattr(_server, "_run_sweeps", lambda *_a: ran.append("startup"))

        class _FakeServer:
            def __init__(self, *_a: object, **_k: object) -> None:
                pass

            def serve_forever(self) -> None:
                raise KeyboardInterrupt

            def server_close(self) -> None:
                pass

        monkeypatch.setattr(_threads, "ContextHTTPServer", _FakeServer)
        _server.run_serve(port=0, interval=30)
        assert ran == ["startup"]


class TestSweepRefreshesObservedModels:
    @staticmethod
    def _stub(monkeypatch: pytest.MonkeyPatch) -> list[int]:
        from docket.models import provider_lifecycle as _provider_lifecycle
        from docket.tasks.application import queue as _queue

        calls: list[int] = []
        monkeypatch.setattr(
            _provider_lifecycle, "refresh_observed_models_due", lambda: calls.append(1) or []
        )
        monkeypatch.setattr(_queue, "dispatchable_pods", lambda: [])
        monkeypatch.setattr(_sweeps, "check_schedules", lambda now: None)
        return calls

    def test_only_a_dispatching_sweep_refreshes_the_providers_limits(
        self, swept_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = self._stub(monkeypatch)
        _server._run_sweeps()
        assert calls == []
        _server._run_sweeps(dispatch=True)
        assert calls == [1]

    def test_a_failing_refresh_does_not_stop_the_sweep(
        self, swept_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from docket.models import provider_lifecycle as _provider_lifecycle
        from docket.tasks.application import queue as _queue

        def boom() -> list[str]:
            raise RuntimeError("provider down")

        seen: list[int] = []
        monkeypatch.setattr(_provider_lifecycle, "refresh_observed_models_due", boom)
        monkeypatch.setattr(_queue, "dispatchable_pods", lambda: seen.append(1) or [])
        monkeypatch.setattr(_sweeps, "check_schedules", lambda now: None)
        _server._run_sweeps(dispatch=True)
        assert seen == [1]
