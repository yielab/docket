"""SUBJECT: interfaces.http.server._StopController -- the two-stage SIGINT/SIGTERM stop of `docket start`."""

from __future__ import annotations

import signal
import threading

import pytest

from docket.interfaces.http import sweeps as _sweeps

SUBJECT = "docket.interfaces.http.server"


def _controller(
    pending: int = 2,
) -> tuple[_sweeps._StopController, list[str], threading.Event, threading.Event]:
    calls: list[str] = []
    shut, abandoned = threading.Event(), threading.Event()
    ctl = _sweeps._StopController(
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
