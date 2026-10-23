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


def test_parse_epoch_reads_the_leading_seconds_of_any_stamp_as_utc() -> None:
    expected = datetime(2026, 10, 22, 9, 30, 5, tzinfo=UTC).timestamp()
    for text in (
        "2026-10-22T09:30:05",
        "2026-10-22T09:30:05Z",
        "2026-10-22T09:30:05.987Z",
        "2026-10-22T09:30:05.987654+00:00",
    ):
        assert clock.parse_epoch(text) == expected, text


def test_parse_epoch_is_none_for_anything_that_is_not_a_stamp() -> None:
    for value in ("", "yesterday", "2026-10-22", None, 7):
        assert clock.parse_epoch(value) is None, value


def test_parse_iso_makes_a_naive_stamp_utc_and_keeps_an_offset() -> None:
    naive = clock.parse_iso("2026-10-22T09:30:05")
    assert naive == datetime(2026, 10, 22, 9, 30, 5, tzinfo=UTC)
    shifted = clock.parse_iso("2026-10-22T09:30:05.5+02:00")
    assert shifted is not None and shifted.utcoffset() == timedelta(hours=2)
    assert clock.parse_iso(clock.iso()) is not None


def test_parse_iso_is_none_for_empty_or_unparseable_text() -> None:
    assert clock.parse_iso("") is None
    assert clock.parse_iso(None) is None
    assert clock.parse_iso("not a time") is None
