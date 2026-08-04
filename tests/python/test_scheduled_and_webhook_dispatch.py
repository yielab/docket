"""Scheduled & webhook-triggered dispatch.

Acceptance criteria:
  - A scheduled time fires a dispatch
  - A webhook POST triggers a dispatch
  - Unauthorized requests are rejected
  - suite green

The last-run bookkeeping ``TestCheckSchedules`` exercises is durable state
persisted in the schedules file itself
(``core.schedule.load_last_run``/``record_last_run``), not an in-memory
``_serve._schedule_state`` dict — an in-memory dict resets on every ``docket
serve`` restart, which was a real bug that made every schedule re-fire
immediately after one. The dedicated restart-survival test lives here too;
per-dispatch run-record coverage lives in ``test_dispatch_run_records.py``.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

import docket.config as _cfg
import docket.serve as _serve
from docket.core import runs as _runs
from docket.core import schedule as _sched
from docket.serve import _DocketHandler

_TEST_TOKEN = "test-serve-token-cd6-xyz987"


# ── fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def schedule_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    f = tmp_path / "docket-schedules.json"
    monkeypatch.setattr(_cfg, "SCHEDULE_FILE", f, raising=True)
    monkeypatch.setattr(_cfg, "RUNS_FILE", tmp_path / "docket-runs.json", raising=True)
    return f


@pytest.fixture()
def live_server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Real server on a random port. Yields (base_url, token)."""
    # Minimal APPROVALS_DIR to satisfy any sweep that might run.
    d = tmp_path / "approvals"
    d.mkdir()
    monkeypatch.setattr(_cfg, "APPROVALS_DIR", d, raising=True)
    monkeypatch.setattr(_cfg, "RUNS_FILE", tmp_path / "docket-runs.json", raising=True)

    class _Handler(_DocketHandler):
        serve_token = _TEST_TOKEN

    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{port}", _TEST_TOKEN
    srv.shutdown()


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


# ── durable last-run persistence (core.schedule.load_last_run / record_last_run) ─────


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


# ── _check_schedules integration ──────────────────────────────────────────────


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

        monkeypatch.setattr("docket.core.dispatch.dispatch_pod", _record_and_return)
        _serve._check_schedules(time.time())
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

        monkeypatch.setattr("docket.core.dispatch.dispatch_pod", _record_and_return)
        # last run was just now — not due
        _sched.record_last_run(_cfg.SCHEDULE_FILE, "projB", time.time())
        _serve._check_schedules(time.time())
        time.sleep(0.1)
        assert dispatched == []

    def test_last_run_recorded_durably_after_dispatch(
        self, schedule_file: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The last-run timestamp is written into the schedules FILE
        (not an in-memory dict), so it is readable by a fresh
        `load_last_run` call — the same read path a restarted `docket serve`
        process would use."""
        schedule_file.write_text(
            json.dumps({"schedules": {"projC": "@every 1s"}}),
            encoding="utf-8",
        )
        monkeypatch.setattr(
            "docket.core.dispatch.dispatch_pod",
            lambda proj, **kw: [],
        )
        before = time.time()
        _serve._check_schedules(before)
        last_run = _sched.load_last_run(_cfg.SCHEDULE_FILE)
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
        """The bug this closes: before durable state, every `docket serve`
        restart reset last-run to 0.0 in memory, so every schedule looked
        newly-due on the very first post-restart sweep. Simulate a restart by
        calling `_check_schedules` again with nothing but the FILE as state
        (no shared process memory) and confirm a just-run schedule stays
        quiet."""
        schedule_file.write_text(
            json.dumps({"schedules": {"projD": "@every 3600s"}}),
            encoding="utf-8",
        )
        dispatched: list[str] = []

        def _record_and_return(proj: str, **kw: object) -> list[object]:
            dispatched.append(proj)
            return []

        monkeypatch.setattr("docket.core.dispatch.dispatch_pod", _record_and_return)
        now = time.time()
        _sched.record_last_run(_cfg.SCHEDULE_FILE, "projD", now)

        # "Restart": nothing in memory survives — load_last_run must read the
        # persisted value straight back off disk.
        _serve._check_schedules(now + 1)
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

        monkeypatch.setattr("docket.core.dispatch.dispatch_pod", _fake_dispatch_pod)

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

    def test_webhook_missing_project_returns_404(self, live_server: tuple[str, str]) -> None:
        url, token = live_server
        # /dispatch/ with empty project segment → trailing slash stripped → not found
        status, body = _post(f"{url}/dispatch/", token=token)
        assert status == 404
        assert body["ok"] is False
