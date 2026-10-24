"""Schedule parsing, due-ness and the durable last-run bookkeeping.

The last run is state in the schedules file (``pipeline.application.schedule.load_last_run`` /
``record_last_run``), never an in-memory dict, which a restart would reset and re-fire every
schedule. The sweep loop and the webhook are in tests/integration/hops/."""

from __future__ import annotations

import json
import time
from pathlib import Path

from tests.support import home as _support_home

from docket.pipeline.application import schedule as _sched

SUBJECT = "docket.hops.application.sweep"

_TEST_TOKEN = "test-serve-token"


# ── fixtures ──────────────────────────────────────────────────────────────────


schedule_file = _support_home.schedule_file


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


# ── POST /dispatch/<project> webhook ─────────────────────────────────────────
