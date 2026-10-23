"""``kernel.clock`` -- every format equals the expression it replaces, and a block pins the time."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from docket.kernel import clock
from docket.kernel.clock import use_clock

SUBJECT = "docket.kernel.clock"

# Microseconds above .5s so a rounding implementation fails where a truncating one passes.
_MOMENT = datetime(2026, 10, 22, 9, 30, 5, 987654, tzinfo=UTC)


class _Manual:
    def __init__(self, moment: datetime) -> None:
        self.moment = moment
        self.ticks = 100.0

    def now(self) -> datetime:
        return self.moment

    def monotonic(self) -> float:
        return self.ticks


def test_each_format_equals_the_expression_it_replaces() -> None:
    with use_clock(_Manual(_MOMENT)):
        assert clock.iso() == _MOMENT.isoformat() == "2026-10-22T09:30:05.987654+00:00"
        assert clock.stamp() == _MOMENT.strftime("%Y-%m-%dT%H:%M:%SZ") == "2026-10-22T09:30:05Z"
        assert clock.stamp_ms() == "2026-10-22T09:30:05.987Z"
        assert clock.epoch() == _MOMENT.timestamp()
        assert clock.today() == date(2026, 10, 22)
        assert clock.today_iso() == "2026-10-22"


def test_stamp_ms_keeps_leading_zeros() -> None:
    with use_clock(_Manual(_MOMENT.replace(microsecond=7000))):
        assert clock.stamp_ms() == "2026-10-22T09:30:05.007Z"


def test_a_block_pins_the_time_and_restores_it() -> None:
    before = clock.now()
    manual = _Manual(_MOMENT)
    with use_clock(manual):
        assert clock.now() == _MOMENT
        manual.moment += timedelta(seconds=90)
        manual.ticks += 90
        assert clock.now() == _MOMENT + timedelta(seconds=90)
        assert clock.monotonic() == 190.0
    assert clock.now() >= before
    assert clock.now().tzinfo is UTC


def test_the_system_clock_is_utc_aware() -> None:
    assert clock.now().utcoffset() == timedelta(0)
    assert clock.stamp().endswith("Z")
    assert clock.monotonic() <= clock.monotonic()
