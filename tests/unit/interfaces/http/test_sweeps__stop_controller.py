"""SUBJECT: interfaces.http.server._StopController -- the two-stage SIGINT/SIGTERM stop of `docket start`."""

from __future__ import annotations

import pytest

from docket.interfaces.http import server as _server
from docket.interfaces.http import sweeps as _sweeps
from docket.tasks.application import runs as _runs

SUBJECT = "docket.interfaces.http.sweeps"


class TestAbandonSweeps:
    def test_requests_cancellation_of_each_recorded_run(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cancelled: list[str] = []
        monkeypatch.setattr(_runs, "cancel_run", lambda rid, **_: cancelled.append(rid))
        monkeypatch.setattr(_sweeps, "_sweep_run_ids", {"pod-a": "run-a", "pod-b": "run-b"})
        monkeypatch.setattr(_sweeps, "_sweep_inflight", {})
        monkeypatch.setattr(_server, "_sweep_pool", None)
        assert _server._abandon_sweeps(wait_s=0.1) is True
        assert sorted(cancelled) == ["run-a", "run-b"]
