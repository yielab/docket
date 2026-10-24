"""Scheduled & webhook-triggered dispatch.

Acceptance criteria: a scheduled time fires a dispatch, a webhook POST
triggers a dispatch, unauthorized requests are rejected.

The last-run bookkeeping ``TestCheckSchedules`` exercises must be durable
state in the schedules file (``pipeline.application.schedule.load_last_run``/
``record_last_run``), never an in-memory ``_serve._schedule_state`` dict --
an in-memory dict resets on restart and re-fires every schedule
immediately. The restart-survival test lives here; per-dispatch run-record
coverage lives in ``test_dispatch_run_records.py``.
"""

from __future__ import annotations

import dataclasses
import json
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import pytest
from tests.support import http as _support_http

from docket.interfaces.http import sweeps as _sweeps
from docket.kernel.home import current_home, use_home
from docket.pipeline.application import schedule as _sched
from docket.tasks.application import runs as _runs

live_server = _support_http.live_server_in_tmp_home

SUBJECT = "docket.hops.application.sweep"

_TEST_TOKEN = "test-serve-token"


# ── fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def schedule_file(tmp_path: Path) -> Iterator[Path]:
    f = tmp_path / "docket-schedules.json"
    with use_home(
        dataclasses.replace(
            current_home(),
            schedule_file_override=f,
            runs_file_override=tmp_path / "docket-runs.json",
        )
    ):
        yield f


def _post(
    url: str,
    body: dict | None = None,  # type: ignore[type-arg]
    token: str | None = None,
) -> tuple[int, dict]:  # type: ignore[type-arg]
    data = json.dumps(body or {}).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Content-Length", str(len(data)))
    if token is not None:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


# ── schedule spec parsing ──────────────────────────────────────────────────────


class TestScheduleParsing:
    def test_interval_seconds(self) -> None:
        assert _sched.parse_interval("@every 30s") == 30

    def test_interval_minutes(self) -> None:
        assert _sched.parse_interval("@every 5m") == 300

    def test_interval_hours(self) -> None:
        assert _sched.parse_interval("@every 2h") == 7200

    def test_invalid_interval_returns_none(self) -> None:
        assert _sched.parse_interval("every 5m") is None
        assert _sched.parse_interval("@every 5x") is None
        assert _sched.parse_interval("09:00") is None

    def test_daily_time_valid(self) -> None:
        assert _sched.parse_daily_time("09:00") == (9, 0)
        assert _sched.parse_daily_time("23:59") == (23, 59)
        assert _sched.parse_daily_time("0:00") == (0, 0)

    def test_daily_time_invalid(self) -> None:
        assert _sched.parse_daily_time("@every 5m") is None
        assert _sched.parse_daily_time("25:00") is None
        assert _sched.parse_daily_time("12:60") is None

    def test_unrecognised_spec_not_due(self) -> None:
        assert not _sched.is_schedule_due("unknown format", 0.0, time.time())


class TestScheduleDue:
    def test_interval_due_after_elapsed(self) -> None:
        now = time.time()
        assert _sched.is_schedule_due("@every 60s", now - 61, now)

    def test_interval_not_due_before_elapsed(self) -> None:
        now = time.time()
        assert not _sched.is_schedule_due("@every 60s", now - 30, now)

    def test_interval_due_from_zero(self) -> None:
        assert _sched.is_schedule_due("@every 60s", 0.0, time.time())

    def test_daily_due_when_last_run_before_target(self) -> None:
        import datetime as _dt

        now_dt = _dt.datetime.now(_dt.UTC)
        # target = yesterday at 00:01
        target = now_dt.replace(hour=0, minute=1, second=0, microsecond=0)
        if target > now_dt:
            target -= _dt.timedelta(days=1)
        last_before = target - _dt.timedelta(minutes=5)
        assert _sched.is_schedule_due("00:01", last_before.timestamp(), now_dt.timestamp())

    def test_daily_not_due_when_last_run_after_target(self) -> None:
        import datetime as _dt

        now_dt = _dt.datetime.now(_dt.UTC)
        target = now_dt.replace(hour=0, minute=1, second=0, microsecond=0)
        if target > now_dt:
            target -= _dt.timedelta(days=1)
        last_after = target + _dt.timedelta(minutes=5)
        assert not _sched.is_schedule_due("00:01", last_after.timestamp(), now_dt.timestamp())


class TestLoadSchedules:
    def test_reads_schedules_from_file(self, schedule_file: Path) -> None:
        schedule_file.write_text(
            json.dumps({"schedules": {"proj1": "@every 5m", "proj2": "09:00"}}),
            encoding="utf-8",
        )
        result = _sched.load_schedules(schedule_file)
        assert result == {"proj1": "@every 5m", "proj2": "09:00"}

    def test_missing_file_returns_empty(self, schedule_file: Path) -> None:
        assert _sched.load_schedules(schedule_file) == {}

    def test_invalid_json_returns_empty(self, schedule_file: Path) -> None:
        schedule_file.write_text("not json", encoding="utf-8")
        assert _sched.load_schedules(schedule_file) == {}

    def test_missing_schedules_key_returns_empty(self, schedule_file: Path) -> None:
        schedule_file.write_text(json.dumps({"other": "data"}), encoding="utf-8")
        assert _sched.load_schedules(schedule_file) == {}


# ── durable last-run persistence (pipeline.application.schedule.load_last_run / record_last_run) ─────


class TestLastRunPersistence:
    def test_missing_file_returns_empty(self, schedule_file: Path) -> None:
        assert _sched.load_last_run(schedule_file) == {}

    def test_record_then_load_round_trips(self, schedule_file: Path) -> None:
        _sched.record_last_run(schedule_file, "proj1", 12345.0)
        assert _sched.load_last_run(schedule_file) == {"proj1": 12345.0}

    def test_record_preserves_existing_schedules_key(self, schedule_file: Path) -> None:
        schedule_file.write_text(
            json.dumps({"schedules": {"proj1": "@every 5m"}}), encoding="utf-8"
        )
        _sched.record_last_run(schedule_file, "proj1", 999.0)
        assert _sched.load_schedules(schedule_file) == {"proj1": "@every 5m"}
        assert _sched.load_last_run(schedule_file) == {"proj1": 999.0}

    def test_record_preserves_other_projects_last_run(self, schedule_file: Path) -> None:
        _sched.record_last_run(schedule_file, "proj1", 100.0)
        _sched.record_last_run(schedule_file, "proj2", 200.0)
        assert _sched.load_last_run(schedule_file) == {"proj1": 100.0, "proj2": 200.0}

    def test_invalid_json_returns_empty(self, schedule_file: Path) -> None:
        schedule_file.write_text("not json", encoding="utf-8")
        assert _sched.load_last_run(schedule_file) == {}

    def test_record_last_run_survives_a_simulated_restart(self, schedule_file: Path) -> None:
        """Last-run state must be readable by a process that has no shared
        memory with the one that wrote it — i.e. it lives in the file, not
        a module-level dict."""
        _sched.record_last_run(schedule_file, "proj1", 555.0)
        # Simulate "no in-memory state" by only ever reading through the file.
        reloaded = _sched.load_last_run(Path(str(schedule_file)))
        assert reloaded["proj1"] == 555.0


# ── check_schedules integration ──────────────────────────────────────────────


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


# ── POST /dispatch/<project> webhook ─────────────────────────────────────────


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
