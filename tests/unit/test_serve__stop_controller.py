"""SUBJECT: docket.serve._StopController -- the two-stage SIGINT/SIGTERM stop of `docket start`."""

from __future__ import annotations

import signal
import threading

import pytest

from docket import serve as _serve
from docket.core import runs as _runs

SUBJECT = "docket.serve"


def _controller(
    pending: int = 2,
) -> tuple[_serve._StopController, list[str], threading.Event, threading.Event]:
    calls: list[str] = []
    shut, abandoned = threading.Event(), threading.Event()
    ctl = _serve._StopController(
        threading.Event(),
        lambda: (calls.append("shutdown"), shut.set()),
        lambda: (calls.append("abandon"), abandoned.set()),
        pending=lambda: pending,
    )
    return ctl, calls, shut, abandoned


class TestStopController:
    def test_first_signal_sets_stop_only_and_prints_one_notice(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        ctl, calls, shut, _abandoned = _controller(pending=3)
        ctl.handle(signal.SIGINT)
        assert shut.wait(5)
        assert ctl.stop.is_set() and not ctl.abandon.is_set()
        assert calls == ["shutdown"]
        assert ctl.exit_code == 0
        out = capsys.readouterr().out
        assert out.strip() == "stopping: waiting for 3 pod sweep(s); signal again to abandon"

    @pytest.mark.parametrize(("sig", "code"), [(signal.SIGINT, 130), (signal.SIGTERM, 143)])
    def test_second_signal_abandons_and_sets_the_exit_code(
        self, sig: signal.Signals, code: int
    ) -> None:
        ctl, calls, _shut, abandoned = _controller()
        ctl.handle(sig)
        ctl.handle(sig)
        assert abandoned.wait(5)
        assert ctl.abandon.is_set() and ctl.exit_code == code
        assert sorted(calls) == ["abandon", "shutdown"]

    def test_a_third_signal_does_not_abandon_twice(self) -> None:
        ctl, calls, _shut, abandoned = _controller()
        for _ in range(3):
            ctl.handle(signal.SIGINT)
        assert abandoned.wait(5)
        assert calls.count("abandon") == 1


class TestAbandonSweeps:
    def test_requests_cancellation_of_each_recorded_run(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cancelled: list[str] = []
        monkeypatch.setattr(_runs, "cancel_run", lambda rid: cancelled.append(rid))
        monkeypatch.setattr(_serve, "_sweep_run_ids", {"pod-a": "run-a", "pod-b": "run-b"})
        monkeypatch.setattr(_serve, "_sweep_inflight", {})
        monkeypatch.setattr(_serve, "_sweep_pool", None)
        assert _serve._abandon_sweeps(wait_s=0.1) is True
        assert sorted(cancelled) == ["run-a", "run-b"]
