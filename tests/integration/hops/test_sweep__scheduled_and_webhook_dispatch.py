"""Scheduled and webhook-triggered dispatch through the real sweep loop and HTTP server.

A due schedule fires a dispatch and records its last run durably (never in memory, which a
restart would reset), and a webhook POST dispatches only when authorised."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest
from tests.support import home as _support_home
from tests.support import http as _support_http

from docket.interfaces.http import sweeps as _sweeps
from docket.kernel.home import current_home
from docket.pipeline.application import schedule as _sched
from docket.tasks.application import runs as _runs

SUBJECT = "docket.hops.application.sweep"

live_server = _support_http.live_server_in_tmp_home
schedule_file = _support_home.schedule_file
_post = _support_http.post


class TestCheckSchedules:
    def test_due_project_triggers_dispatch(
        self, schedule_file: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        schedule_file.write_text(
            json.dumps({"schedules": {"projA": "@every 1s"}}),
            encoding="utf-8",
        )
        dispatched: list[str] = []

        def _record_and_return(proj: str, **kw: object) -> list[object]:
            dispatched.append(proj)
            return []

        monkeypatch.setattr("docket.hops.application.sweep.dispatch_pod", _record_and_return)
        _sweeps.check_schedules(time.time())
        # Allow daemon thread to run
        deadline = time.time() + 2
        while not dispatched and time.time() < deadline:
            time.sleep(0.05)
        assert dispatched == ["projA"]

    def test_not_yet_due_project_skipped(
        self, schedule_file: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        schedule_file.write_text(
            json.dumps({"schedules": {"projB": "@every 3600s"}}),
            encoding="utf-8",
        )
        dispatched: list[str] = []

        def _record_and_return(proj: str, **kw: object) -> list[object]:
            dispatched.append(proj)
            return []

        monkeypatch.setattr("docket.hops.application.sweep.dispatch_pod", _record_and_return)
        # last run was just now — not due
        _sched.record_last_run(current_home().schedule_file, "projB", time.time())
        _sweeps.check_schedules(time.time())
        time.sleep(0.1)
        assert dispatched == []

    def test_unrecognized_spec_logs_once_per_sweep_and_is_skipped(
        self,
        schedule_file: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A silently never-due bad spec now prints one skip line per sweep naming the
        project and reason, instead of firing nothing forever with no operator-visible
        trace."""
        schedule_file.write_text(
            json.dumps({"schedules": {"projC": "@every 3x"}}),
            encoding="utf-8",
        )
        dispatched: list[str] = []

        def _record_and_return(proj: str, **kw: object) -> list[object]:
            dispatched.append(proj)
            return []

        monkeypatch.setattr("docket.hops.application.sweep.dispatch_pod", _record_and_return)
        _sweeps.check_schedules(time.time())
        time.sleep(0.1)
        out = capsys.readouterr().out
        assert dispatched == []
        lines = [line for line in out.splitlines() if "projC" in line]
        assert len(lines) == 1
        assert "3x" in lines[0]

    def test_last_run_recorded_durably_after_dispatch(
        self, schedule_file: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The last-run timestamp is written into the schedules FILE, not an
        in-memory dict, so a fresh `load_last_run` call reads it -- the
        same path a restarted `docket start` process uses."""
        schedule_file.write_text(
            json.dumps({"schedules": {"projC": "@every 1s"}}),
            encoding="utf-8",
        )
        monkeypatch.setattr(
            "docket.hops.application.sweep.dispatch_pod",
            lambda proj, **kw: [],
        )
        before = time.time()
        _sweeps.check_schedules(before)
        last_run = _sched.load_last_run(current_home().schedule_file)
        assert last_run.get("projC", 0.0) >= before

        # Drain the daemon thread this spawned before the test ends and
        # monkeypatch tears down `dispatch_pod` -- otherwise a slow-scheduled
        # thread can still be holding the *current* (about to be reverted)
        # fake and fire into a LATER test's monkeypatch window instead,
        # corrupting that test's assertions.
        deadline = time.time() + 2
        records = _runs.list_runs("projC")
        while records and records[0]["state"] not in ("succeeded", "failed"):
            if time.time() > deadline:
                raise AssertionError("projC dispatch thread never reached a terminal state")
            time.sleep(0.02)
            records = _runs.list_runs("projC")

    def test_restart_does_not_immediately_refire_a_recently_run_schedule(
        self, schedule_file: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A restart MUST NOT reset last-run to 0.0 and make every schedule
        look newly-due. Simulates a restart via `check_schedules` with
        only the FILE as state (no shared process memory)."""
        schedule_file.write_text(
            json.dumps({"schedules": {"projD": "@every 3600s"}}),
            encoding="utf-8",
        )
        dispatched: list[str] = []

        def _record_and_return(proj: str, **kw: object) -> list[object]:
            dispatched.append(proj)
            return []

        monkeypatch.setattr("docket.hops.application.sweep.dispatch_pod", _record_and_return)
        now = time.time()
        _sched.record_last_run(current_home().schedule_file, "projD", now)

        # "Restart": nothing in memory survives — load_last_run must read the
        # persisted value straight back off disk.
        _sweeps.check_schedules(now + 1)
        time.sleep(0.1)
        assert dispatched == [], "schedule re-fired immediately after a simulated restart"


class TestWebhookDispatch:
    def test_webhook_triggers_dispatch(
        self,
        live_server: tuple[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        url, token = live_server
        dispatched: list[str] = []
        event = threading.Event()

        def _fake_dispatch_pod(proj: str, **kw: object) -> list[object]:
            dispatched.append(proj)
            event.set()
            return []

        monkeypatch.setattr("docket.hops.application.sweep.dispatch_pod", _fake_dispatch_pod)

        status, body = _post(f"{url}/dispatch/myproject", token=token)
        assert status == 200
        assert body["ok"] is True
        assert body["project"] == "myproject"
        assert body["status"] == "dispatched"
        # The webhook hands back a queryable run id before any work runs.
        assert isinstance(body["run"], str) and body["run"].startswith("run-")

        # Wait for the daemon thread to call dispatch
        assert event.wait(timeout=3), "dispatch_pod not called within 3 s"
        assert dispatched == ["myproject"]

        rec = _runs.get_run(body["run"])
        assert rec is not None
        assert rec["source"] == "webhook"
        assert rec["project"] == "myproject"

    def test_webhook_no_auth_rejected(self, live_server: tuple[str, str]) -> None:
        url, _ = live_server
        status, body = _post(f"{url}/dispatch/myproject")
        assert status == 401
        assert body["ok"] is False

    def test_webhook_wrong_token_rejected(self, live_server: tuple[str, str]) -> None:
        url, _ = live_server
        status, _ = _post(f"{url}/dispatch/myproject", token="wrong")
        assert status == 401

    def test_webhook_missing_project_returns_400(self, live_server: tuple[str, str]) -> None:
        url, token = live_server
        # /dispatch/ with an empty project segment (or bare /dispatch) still
        # reaches auth, then names the missing segment -- not a pre-auth 404.
        status, body = _post(f"{url}/dispatch/", token=token)
        assert status == 400
        assert body["ok"] is False
