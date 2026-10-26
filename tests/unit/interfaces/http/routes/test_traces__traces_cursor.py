"""The traces cursor: decoding, the page read directly and the session files it spans."""

from __future__ import annotations

import json
from pathlib import Path

from tests.support import traces_cursor_harness as _shared
from tests.support.traces_cursor_harness import (
    _FakeClock,
)

from docket.interfaces.http.routes import traces
from docket.observability import trace as _trace

SUBJECT = "docket.interfaces.http.routes.traces"

fake_clock = _shared.fake_clock
traces_home = _shared.traces_home


class TestCursorDecoding:
    def test_empty_since_means_from_the_start(self) -> None:
        assert traces._decode_trace_cursor("") == ("", 0)

    def test_minted_cursor_round_trips(self) -> None:
        ts, n = traces._decode_trace_cursor("2026-08-04T12:00:05Z:3")
        assert ts == "2026-08-04T12:00:05Z"
        assert n == 3

    def test_bare_caller_supplied_timestamp_is_accepted_with_zero_skip(self) -> None:
        """A human (or a first-time caller) passing a plain timestamp, not one
        of our minted cursors, must still work -- treated as `since` with
        nothing already delivered at that second."""
        ts, n = traces._decode_trace_cursor("2026-08-04T00:00:00Z")
        assert ts == "2026-08-04T00:00:00Z"
        assert n == 0

    def test_bare_timestamp_without_the_trailing_z_keeps_its_seconds(self) -> None:
        """A timestamp CONTAINS colons, so ":<digits>" alone can't mean
        "count": without requiring the ts half to end in `Z`,
        `"...T00:00:42"` would split as ts=`"...T00:00"`/n=42, eating the
        seconds as a skip count and over-delivering the whole minute.
        `kernel.clock.stamp()` always writes the trailing `Z`, which is what makes
        the hand-supplied bare-timestamp form distinguishable at all."""
        ts, n = traces._decode_trace_cursor("2026-08-04T00:00:42")
        assert ts == "2026-08-04T00:00:42"
        assert n == 0

    def test_a_digit_suffix_without_the_z_is_not_treated_as_a_count(self) -> None:
        ts, n = traces._decode_trace_cursor("2026-08-04T00:00:42:7")
        assert n == 0
        assert ts == "2026-08-04T00:00:42:7"


class TestTracesPageDirect:
    def test_empty_project_yields_empty_cursor(self, traces_home: Path) -> None:
        events, cursor = traces._traces_page("nobody-home", "")
        assert events == []
        assert cursor == ""

    def test_cursor_advances_past_a_second_boundary(
        self, traces_home: Path, fake_clock: _FakeClock
    ) -> None:
        _trace.trace_event("demo", "s1", "lead", "tool_call", json.dumps({"i": 0}))
        fake_clock.tick()
        events1, cursor1 = traces._traces_page("demo", "")
        assert len(events1) == 1

        _trace.trace_event("demo", "s1", "lead", "tool_call", json.dumps({"i": 1}))
        fake_clock.tick()
        events2, cursor2 = traces._traces_page("demo", cursor1)
        assert len(events2) == 1
        assert json.loads(events2[0])["payload"]["i"] == 1
        assert cursor2 != cursor1


class TestMultipleSessionFiles:
    """A real pod writes one trace file per task, so a project with history
    has several; ``export_lines`` concatenates them in sorted filename
    order (a session id is a uuid), so the stream is not chronological.
    The cursor scheme must anchor on the newest event in the page and
    count events sharing that second -- properties of the page's
    contents, not of file glob order."""

    def _write(self, session: str, i: int) -> None:
        _trace.trace_event("demo", session, "lead", "tool_call", json.dumps({"i": i}))

    def test_cursor_does_not_replay_when_a_project_has_several_sessions(
        self, traces_home: Path, fake_clock: _FakeClock
    ) -> None:
        # "zzz" sorts last by filename but is written first, so the newest
        # event does NOT land at the end of the concatenated stream.
        self._write("zzz-older-session", 0)
        fake_clock.tick()
        self._write("aaa-newer-session", 1)
        fake_clock.tick()

        events1, cursor1 = traces._traces_page("demo", "")
        assert len(events1) == 2, "first poll must return both sessions' events"

        events2, _cursor2 = traces._traces_page("demo", cursor1)
        assert events2 == [], (
            "nothing new was written, so a poll from the returned cursor must "
            f"yield nothing -- got {len(events2)} replayed event(s)"
        )

    def test_new_events_still_arrive_after_a_multi_session_cursor(
        self, traces_home: Path, fake_clock: _FakeClock
    ) -> None:
        self._write("zzz-older-session", 0)
        fake_clock.tick()
        self._write("aaa-newer-session", 1)
        fake_clock.tick()
        _events1, cursor1 = traces._traces_page("demo", "")

        self._write("zzz-older-session", 2)
        fake_clock.tick()

        events2, _cursor2 = traces._traces_page("demo", cursor1)
        assert [json.loads(e)["payload"]["i"] for e in events2] == [2]

    def test_a_page_spanning_sessions_is_delivered_in_time_order(
        self, traces_home: Path, fake_clock: _FakeClock
    ) -> None:
        self._write("zzz-older-session", 0)
        fake_clock.tick()
        self._write("aaa-newer-session", 1)
        fake_clock.tick()
        self._write("mmm-newest-session", 2)
        fake_clock.tick()

        events, _cursor = traces._traces_page("demo", "")
        assert [json.loads(e)["payload"]["i"] for e in events] == [0, 1, 2], (
            "a consumer folding events onto a board reads them in order"
        )


class TestCrossFileSameSecondRace:
    """The exact race the hold-back rule closes -- see the module comment
    above `_trace_line_ts` in serve.py for why filename-order concatenation
    makes this racy without it."""

    # Two DIFFERENT session files ("a", "b") each gain a line in the same
    # still-open second; "a" sorts before "b" regardless of which was
    # written first. Without the hold-back, a poll revealing "b" before "a"
    # exists mints a cursor whose "skip N" count is invalidated the moment
    # "a" lands, redelivering "b" and losing "a" for good. With it, neither
    # line is handed out until the second is closed, so both come back
    # together, exactly once.
    def test_delivers_both_lines_exactly_once_across_three_polls(
        self, traces_home: Path, fake_clock: _FakeClock
    ) -> None:
        _trace.trace_event("demo", "b", "lead", "tool_call", json.dumps({"who": "b"}))
        events1, cursor1 = traces._traces_page("demo", "")
        assert events1 == [], "the second this line landed in is still open"

        _trace.trace_event("demo", "a", "lead", "tool_call", json.dumps({"who": "a"}))
        events2, cursor2 = traces._traces_page("demo", cursor1)
        assert events2 == [], "still open -- a same-second write must not surface yet"
        assert cursor2 == cursor1, "no progress to report while the second stays open"

        fake_clock.tick()
        events3, cursor3 = traces._traces_page("demo", cursor2)
        delivered = {json.loads(e)["payload"]["who"] for e in events3}
        assert delivered == {"a", "b"}, f"expected both lines exactly once, got {events3}"
        assert cursor3 != cursor2

        events4, _cursor4 = traces._traces_page("demo", cursor3)
        assert events4 == [], "nothing left to redeliver on a fourth poll"
