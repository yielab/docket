"""Cron-expression scheduling.

Covers the standard 5-field ``minute hour dom month dow`` cron support
beyond ``core/schedule.py``'s ``@every``/``HH:MM`` forms: ``*``, integers,
``a-b`` ranges, ``/step``, and comma lists, evaluated in UTC, numeric
fields only (no ``JAN``/``MON`` aliases -- see that module's docstring for
the scope cut). Stdlib-only, per ROADMAP §4.5's dependency ban. Exercises
``parse_cron`` and ``is_schedule_due``'s cron branch (fires once per
matching minute, doesn't collide with ``@every``/``HH:MM``).
"""

from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path

import pytest

from docket.core import schedule as _sched

SUBJECT = "docket.core.schedule"


class TestParseCronField:
    def test_every_minute(self) -> None:
        fields = _sched.parse_cron("* * * * *")
        assert fields is not None
        minute, hour, dom, month, dow = fields
        assert minute == frozenset(range(0, 60))
        assert hour == frozenset(range(0, 24))
        assert dom == frozenset(range(1, 32))
        assert month == frozenset(range(1, 13))
        assert dow == frozenset(range(0, 8))

    def test_single_values(self) -> None:
        fields = _sched.parse_cron("5 9 1 6 3")
        assert fields is not None
        minute, hour, dom, month, dow = fields
        assert minute == frozenset({5})
        assert hour == frozenset({9})
        assert dom == frozenset({1})
        assert month == frozenset({6})
        assert dow == frozenset({3})

    def test_range(self) -> None:
        fields = _sched.parse_cron("0 9-17 * * *")
        assert fields is not None
        assert fields[1] == frozenset(range(9, 18))

    def test_step_on_star(self) -> None:
        fields = _sched.parse_cron("*/15 * * * *")
        assert fields is not None
        assert fields[0] == frozenset({0, 15, 30, 45})

    def test_step_on_range(self) -> None:
        fields = _sched.parse_cron("0 9-17/2 * * *")
        assert fields is not None
        assert fields[1] == frozenset({9, 11, 13, 15, 17})

    def test_comma_list(self) -> None:
        fields = _sched.parse_cron("0,15,30,45 * * * *")
        assert fields is not None
        assert fields[0] == frozenset({0, 15, 30, 45})

    def test_comma_list_mixing_ranges_and_singles(self) -> None:
        fields = _sched.parse_cron("0 0-5,12,20-22 * * *")
        assert fields is not None
        assert fields[1] == frozenset({0, 1, 2, 3, 4, 5, 12, 20, 21, 22})

    def test_dow_seven_means_sunday(self) -> None:
        """Standard cron convention: both 0 and 7 mean Sunday."""
        fields = _sched.parse_cron("0 0 * * 7")
        assert fields is not None
        assert fields[4] == frozenset({7})


class TestParseCronRejects:
    def test_wrong_field_count_is_not_cron(self) -> None:
        assert _sched.parse_cron("* * * *") is None
        assert _sched.parse_cron("* * * * * *") is None

    def test_out_of_range_value_rejected(self) -> None:
        assert _sched.parse_cron("60 * * * *") is None
        assert _sched.parse_cron("0 24 * * *") is None
        assert _sched.parse_cron("0 0 32 * *") is None
        assert _sched.parse_cron("0 0 * 13 *") is None
        assert _sched.parse_cron("0 0 * * 8") is None

    def test_backwards_range_rejected(self) -> None:
        assert _sched.parse_cron("50-10 * * * *") is None

    def test_non_numeric_field_rejected(self) -> None:
        assert _sched.parse_cron("JAN * * * *") is None
        assert _sched.parse_cron("MON * * * *") is None

    def test_zero_or_negative_step_rejected(self) -> None:
        assert _sched.parse_cron("*/0 * * * *") is None
        assert _sched.parse_cron("*/-5 * * * *") is None

    def test_empty_comma_part_rejected(self) -> None:
        assert _sched.parse_cron("1,,2 * * * *") is None

    def test_at_every_spec_is_not_cron(self) -> None:
        assert _sched.parse_cron("@every 5m") is None

    def test_daily_time_spec_is_not_cron(self) -> None:
        assert _sched.parse_cron("09:00") is None

    def test_garbage_is_not_cron(self) -> None:
        assert _sched.parse_cron("not a cron expression") is None


class TestCronIsDue:
    def test_matching_minute_first_observation_is_due(self) -> None:
        # 2026-07-30T09:15:00Z matches "*/15 9-17 * * *".
        now = _dt.datetime(2026, 7, 30, 9, 15, 0, tzinfo=_dt.UTC).timestamp()
        last_run = 0.0
        assert _sched.is_schedule_due("*/15 9-17 * * *", last_run, now)

    def test_matching_minute_already_fired_this_minute_is_not_due_again(self) -> None:
        now = _dt.datetime(2026, 7, 30, 9, 15, 30, tzinfo=_dt.UTC).timestamp()
        # last run was earlier in the SAME matching minute (:15:05).
        last_run = _dt.datetime(2026, 7, 30, 9, 15, 5, tzinfo=_dt.UTC).timestamp()
        assert not _sched.is_schedule_due("*/15 9-17 * * *", last_run, now)

    def test_non_matching_minute_is_not_due(self) -> None:
        now = _dt.datetime(2026, 7, 30, 9, 16, 0, tzinfo=_dt.UTC).timestamp()
        assert not _sched.is_schedule_due("*/15 9-17 * * *", 0.0, now)

    def test_matching_minute_after_a_prior_different_minute_fires_again(self) -> None:
        now = _dt.datetime(2026, 7, 30, 9, 30, 0, tzinfo=_dt.UTC).timestamp()
        last_run = _dt.datetime(2026, 7, 30, 9, 15, 5, tzinfo=_dt.UTC).timestamp()
        assert _sched.is_schedule_due("*/15 9-17 * * *", last_run, now)

    def test_weekday_field_respected(self) -> None:
        now = _dt.datetime(2026, 7, 30, 9, 0, 0, tzinfo=_dt.UTC).timestamp()
        assert _sched.is_schedule_due("0 9 * * 4", 0.0, now)
        assert not _sched.is_schedule_due("0 9 * * 1", 0.0, now)

    def test_malformed_cron_like_spec_is_never_due(self) -> None:
        assert not _sched.is_schedule_due("99 99 99 99 99", 0.0, 1000.0)

    def test_cron_does_not_shadow_at_every(self) -> None:
        """A well-formed `@every` spec must still resolve as an interval, not
        be mistaken for (or fall through to) the cron branch."""
        now = _dt.datetime(2026, 7, 30, 9, 0, 0, tzinfo=_dt.UTC).timestamp()
        assert _sched.is_schedule_due("@every 30s", now - 31, now)

    def test_cron_does_not_shadow_daily_time(self) -> None:
        now = _dt.datetime(2026, 7, 30, 9, 0, 0, tzinfo=_dt.UTC).timestamp()
        assert _sched.is_schedule_due("09:00", 0.0, now)


class TestDescribeSpecError:
    """`describe_spec_error` names the reason `is_schedule_due` drops silently."""

    def test_recognized_every_spec_has_no_error(self) -> None:
        assert _sched.describe_spec_error("@every 30m") is None

    def test_recognized_daily_spec_has_no_error(self) -> None:
        assert _sched.describe_spec_error("09:00") is None

    def test_recognized_cron_spec_has_no_error(self) -> None:
        assert _sched.describe_spec_error("*/15 9-17 * * 1-5") is None

    def test_bad_every_unit_is_named(self) -> None:
        reason = _sched.describe_spec_error("@every 3x")
        assert reason is not None
        assert "3x" in reason

    def test_garbage_spec_is_named(self) -> None:
        reason = _sched.describe_spec_error("not a schedule")
        assert reason is not None
        assert "not a schedule" in reason


class TestScheduleWriter:
    """`set_schedule`/`unset_schedule`: the writer `docket-schedules.json` lacked."""

    def test_set_schedule_validates_and_persists(self, tmp_path: Path) -> None:
        path = tmp_path / "docket-schedules.json"
        _sched.set_schedule(path, "shop", "@every 30m")
        doc = json.loads(path.read_text())
        assert doc["schedules"] == {"shop": "@every 30m"}

    def test_set_schedule_rejects_unrecognized_spec(self, tmp_path: Path) -> None:
        path = tmp_path / "docket-schedules.json"
        with pytest.raises(_sched.ScheduleError, match="3x"):
            _sched.set_schedule(path, "shop", "@every 3x")
        assert not path.exists()

    def test_set_schedule_preserves_last_run_and_other_projects(self, tmp_path: Path) -> None:
        path = tmp_path / "docket-schedules.json"
        _sched.set_schedule(path, "shop", "@every 30m")
        _sched.record_last_run(path, "shop", 1000.0)
        _sched.set_schedule(path, "other", "09:00")
        doc = json.loads(path.read_text())
        assert doc["schedules"] == {"shop": "@every 30m", "other": "09:00"}
        assert doc["lastRun"] == {"shop": 1000.0}

    def test_unset_schedule_removes_only_that_project(self, tmp_path: Path) -> None:
        path = tmp_path / "docket-schedules.json"
        _sched.set_schedule(path, "shop", "@every 30m")
        _sched.set_schedule(path, "other", "09:00")
        _sched.unset_schedule(path, "shop")
        doc = json.loads(path.read_text())
        assert doc["schedules"] == {"other": "09:00"}

    def test_unset_schedule_is_a_no_op_when_absent(self, tmp_path: Path) -> None:
        path = tmp_path / "docket-schedules.json"
        _sched.unset_schedule(path, "shop")
        doc = json.loads(path.read_text())
        assert doc["schedules"] == {}


class TestFindScheduleProblems:
    """`find_schedule_problems`: what `docket doctor` surfaces."""

    def test_no_file_has_no_problems(self, tmp_path: Path) -> None:
        assert _sched.find_schedule_problems(tmp_path / "docket-schedules.json") == []

    def test_valid_schedules_have_no_problems(self, tmp_path: Path) -> None:
        path = tmp_path / "docket-schedules.json"
        _sched.set_schedule(path, "shop", "@every 30m")
        assert _sched.find_schedule_problems(path) == []

    def test_unrecognized_spec_is_reported_by_project_key(self, tmp_path: Path) -> None:
        path = tmp_path / "docket-schedules.json"
        path.write_text(json.dumps({"schedules": {"shop": "@every 3x"}}))
        problems = _sched.find_schedule_problems(path)
        assert len(problems) == 1
        key, reason = problems[0]
        assert key == "shop"
        assert "3x" in reason

    def test_malformed_json_is_reported_by_file(self, tmp_path: Path) -> None:
        path = tmp_path / "docket-schedules.json"
        path.write_text("{not json")
        problems = _sched.find_schedule_problems(path)
        assert len(problems) == 1
        assert problems[0][0] == str(path)
