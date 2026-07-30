"""ROADMAP Phase 16 W-4: cron-expression scheduling.

``core/schedule.py`` previously understood only ``@every <N><unit>`` and a
single daily ``HH:MM`` — this is the missing "real cron spec" support: a
standard 5-field ``minute hour dom month dow`` expression (``*``, a single
integer, an ``a-b`` range, a ``/step`` on either, and comma lists of any of
those), evaluated in UTC, numeric fields only (no ``JAN``/``MON`` name
aliases — see ``core/schedule.py``'s module docstring for the deliberate
scope cut). Stdlib-only, per ROADMAP §4.5's dependency ban.

Covers ``parse_cron`` (the field parser + malformed-spec rejection) and
``is_schedule_due``'s cron branch (fires once per matching minute, never
twice for the same minute, and does not collide with the pre-existing
``@every``/``HH:MM`` recognizers).
"""

from __future__ import annotations

import datetime as _dt

from docket.core import schedule as _sched


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
        # 2026-07-30 is a Thursday (cron dow 4).
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
