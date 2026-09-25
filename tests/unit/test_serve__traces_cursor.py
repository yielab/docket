"""GET /traces/<project>?since=<cursor> — cursor'd raw trace read over HTTP.

See specs/data/serve-read-api.spec.md ("GET /traces/<project>") for the
cursor-semantics contract this suite pins -- why `serve._traces_page`
uses a compound `"<ts>:<n>"` cursor, not a bare timestamp.
`TestPollLoopBoundary` proves exactly-once delivery across a same-second
boundary. Also covers: auth rejection, missing project segment -> 400, a
project with no trace files -> 200 empty, verbatim passthrough, and the
cursor decoder accepting a bare timestamp too.
"""

from __future__ import annotations

import datetime as _dt
import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest
from tests.conftest import repoint_docket_home

import docket.config as _cfg
import docket.serve as serve
from docket.core import trace as _trace
from docket.serve import _DocketHandler

SUBJECT = "docket.serve"

_TEST_TOKEN = "test-serve-token-traces-p22-3"


def _get(url: str, token: str | None = None) -> tuple[int, dict]:  # type: ignore[type-arg]
    req = urllib.request.Request(url)
    if token is not None:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


@pytest.fixture()
def live_server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    home = tmp_path / ".docket"
    home.mkdir(exist_ok=True)
    repoint_docket_home(monkeypatch, home)
    approvals_dir = tmp_path / "approvals"
    approvals_dir.mkdir()
    monkeypatch.setattr(_cfg, "APPROVALS_DIR", approvals_dir, raising=True)

    class _Handler(_DocketHandler):
        serve_token = _TEST_TOKEN

    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{port}", _TEST_TOKEN
    srv.shutdown()


@pytest.fixture()
def traces_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / ".docket"
    home.mkdir(exist_ok=True)
    repoint_docket_home(monkeypatch, home)
    return home


class _FakeClock:
    """Deterministic stand-in for `trace._now_iso` and `serve._now`."""

    # Snapped to a whole second so tick() amounts land on an exact boundary,
    # with no fractional-second guesswork for callers.
    def __init__(self) -> None:
        self._current = _dt.datetime.now(_dt.UTC).replace(microsecond=0)

    def now(self) -> _dt.datetime:
        return self._current

    def now_iso(self) -> str:
        return self._current.strftime("%Y-%m-%dT%H:%M:%SZ")

    def tick(self, seconds: int | None = None) -> None:
        """Advance the clock -- default closes out the hold-back window."""
        # One second past `serve._TRACE_HOLD_BACK_S`: exactly enough that a
        # write-then-tick()-then-poll always sees the write delivered.
        if seconds is None:
            seconds = serve._TRACE_HOLD_BACK_S + 1
        self._current += _dt.timedelta(seconds=seconds)


@pytest.fixture()
def fake_clock(monkeypatch: pytest.MonkeyPatch) -> _FakeClock:
    clock = _FakeClock()
    monkeypatch.setattr(_trace, "_now_iso", clock.now_iso)
    monkeypatch.setattr(serve, "_now", clock.now)
    return clock


# ── auth + missing project ───────────────────────────────────────────────────


class TestAuth:
    def test_no_token_rejected(self, live_server: tuple[str, str]) -> None:
        url, _token = live_server
        status, body = _get(f"{url}/traces/demo")
        assert status == 401
        assert body["ok"] is False

    def test_wrong_token_rejected(self, live_server: tuple[str, str]) -> None:
        url, _token = live_server
        status, _body = _get(f"{url}/traces/demo", token="not-the-real-token")
        assert status == 401


class TestMissingProject:
    def test_bare_path_is_400(self, live_server: tuple[str, str]) -> None:
        url, token = live_server
        status, body = _get(f"{url}/traces", token=token)
        assert status == 400
        assert body["ok"] is False

    def test_trailing_slash_is_400(self, live_server: tuple[str, str]) -> None:
        url, token = live_server
        status, body = _get(f"{url}/traces/", token=token)
        assert status == 400
        assert body["ok"] is False


class TestEmptyProject:
    def test_no_traces_returns_empty_result_not_an_error(
        self, live_server: tuple[str, str]
    ) -> None:
        url, token = live_server
        status, body = _get(f"{url}/traces/never-seen-project", token=token)
        assert status == 200
        assert body == {"events": [], "next": ""}


# ── verbatim passthrough ─────────────────────────────────────────────────────


class TestVerbatimPassthrough:
    def test_http_events_round_trip_to_the_same_dicts_export_lines_produced(
        self, live_server: tuple[str, str], traces_home: Path, fake_clock: _FakeClock
    ) -> None:
        url, token = live_server
        _trace.trace_event(
            "demo", "sess-1", "lead", "session_start", json.dumps({"source": "test"})
        )
        _trace.trace_event(
            "demo", "sess-1", "implementer", "tool_call", json.dumps({"tool": "read"})
        )
        fake_clock.tick()

        expected = [json.loads(line) for line in _trace.export_lines("demo")]

        status, body = _get(f"{url}/traces/demo", token=token)
        assert status == 200
        events = body["events"]
        assert len(events) == 2
        # Each element is the raw JSONL line text -- a JSON string -- not a
        # reshaped/re-keyed object. Parsing it must reproduce exactly what
        # export_lines itself returned, field for field.
        assert all(isinstance(e, str) for e in events)
        got = [json.loads(e) for e in events]
        assert got == expected
        assert got[0]["event_type"] == "session_start"
        assert got[1]["event_type"] == "tool_call"
        assert got[1]["agent_role"] == "implementer"

    def test_no_filtering_by_event_type_role_or_session(
        self, live_server: tuple[str, str], traces_home: Path, fake_clock: _FakeClock
    ) -> None:
        """This route deliberately rejects a fleet-wide query UI with filtering --
        every event for the project comes back, regardless of type/role/
        session, leaving aggregation to the consumer (Tack)."""
        url, token = live_server
        _trace.trace_event("demo", "sess-a", "lead", "session_start", "{}")
        _trace.trace_event("demo", "sess-b", "tester", "verdict_rejected", "{}")
        fake_clock.tick()

        status, body = _get(f"{url}/traces/demo", token=token)
        assert status == 200
        roles = {json.loads(e)["agent_role"] for e in body["events"]}
        assert roles == {"lead", "tester"}


# ── the boundary that matters most: exactly-once delivery across a poll loop ──


class TestPollLoopBoundary:
    def test_second_poll_from_returned_cursor_yields_exactly_the_new_events(
        self, live_server: tuple[str, str], traces_home: Path, fake_clock: _FakeClock
    ) -> None:
        url, token = live_server
        n = 6
        for i in range(n):
            _trace.trace_event("demo", "sess-1", "lead", "tool_call", json.dumps({"i": i}))
        fake_clock.tick()

        status, body = _get(f"{url}/traces/demo", token=token)
        assert status == 200
        first_batch = [json.loads(e)["payload"]["i"] for e in body["events"]]
        assert first_batch == list(range(n)), (
            "first poll must return every event written so far, in order"
        )
        cursor = body["next"]
        assert cursor, "a non-empty result must hand back a resumable cursor"

        # Polling again immediately (nothing new written) must be a no-op --
        # not a duplicate of the last event the inclusive `ts >= since`
        # filter would naively re-include.
        status_again, body_again = _get(f"{url}/traces/demo?since={cursor}", token=token)
        assert status_again == 200
        assert body_again["events"] == []
        assert body_again["next"] == cursor

        m = 4
        for i in range(n, n + m):
            _trace.trace_event("demo", "sess-1", "lead", "tool_call", json.dumps({"i": i}))
        fake_clock.tick()

        status2, body2 = _get(f"{url}/traces/demo?since={cursor}", token=token)
        assert status2 == 200
        second_batch = [json.loads(e)["payload"]["i"] for e in body2["events"]]

        # The one that matters most: exactly the M new events, no overlap
        # with the first batch, nothing skipped.
        assert second_batch == list(range(n, n + m)), (
            f"expected exactly the {m} new events with no duplicates and no "
            f"gaps, got {second_batch}"
        )
        assert set(first_batch).isdisjoint(second_batch)
        assert len(first_batch) + len(second_batch) == n + m

    def test_boundary_holds_when_every_event_shares_one_second(
        self, live_server: tuple[str, str], traces_home: Path, fake_clock: _FakeClock
    ) -> None:
        """A poll of a still-open second must reveal nothing; once it closes,
        every event landed in it must come back exactly once."""
        url, token = live_server
        for i in range(5):
            _trace.trace_event("demo", "sess-1", "lead", "tool_call", json.dumps({"i": i}))
        _, body = _get(f"{url}/traces/demo", token=token)
        assert body["events"] == [], "the still-open second must not be revealed yet"
        cursor = body["next"]

        for i in range(5, 9):
            _trace.trace_event("demo", "sess-1", "lead", "tool_call", json.dumps({"i": i}))
        fake_clock.tick()
        _, body2 = _get(f"{url}/traces/demo?since={cursor}", token=token)
        second_batch = [json.loads(e)["payload"]["i"] for e in body2["events"]]
        assert second_batch == [0, 1, 2, 3, 4, 5, 6, 7, 8]

    def test_three_polls_in_a_row_ingest_every_event_exactly_once(
        self, live_server: tuple[str, str], traces_home: Path, fake_clock: _FakeClock
    ) -> None:
        url, token = live_server
        seen: list[int] = []
        cursor = ""
        for wave in range(3):
            for i in range(3):
                _trace.trace_event(
                    "demo", "sess-1", "lead", "tool_call", json.dumps({"wave": wave, "n": i})
                )
            fake_clock.tick()
            status, body = _get(f"{url}/traces/demo?since={cursor}", token=token)
            assert status == 200
            for e in body["events"]:
                payload = json.loads(e)["payload"]
                seen.append(payload["wave"] * 100 + payload["n"])
            cursor = body["next"]

        assert sorted(seen) == seen, "events must come back in order"
        assert len(seen) == len(set(seen)), f"duplicate delivered: {seen}"
        assert len(seen) == 9


# ── unit-level cursor semantics (direct, no HTTP round trip) ────────────────


class TestCursorDecoding:
    def test_empty_since_means_from_the_start(self) -> None:
        assert serve._decode_trace_cursor("") == ("", 0)

    def test_minted_cursor_round_trips(self) -> None:
        ts, n = serve._decode_trace_cursor("2026-08-04T12:00:05Z:3")
        assert ts == "2026-08-04T12:00:05Z"
        assert n == 3

    def test_bare_caller_supplied_timestamp_is_accepted_with_zero_skip(self) -> None:
        """A human (or a first-time caller) passing a plain timestamp, not one
        of our minted cursors, must still work -- treated as `since` with
        nothing already delivered at that second."""
        ts, n = serve._decode_trace_cursor("2026-08-04T00:00:00Z")
        assert ts == "2026-08-04T00:00:00Z"
        assert n == 0

    def test_bare_timestamp_without_the_trailing_z_keeps_its_seconds(self) -> None:
        """A timestamp CONTAINS colons, so ":<digits>" alone can't mean
        "count": without requiring the ts half to end in `Z`,
        `"...T00:00:42"` would split as ts=`"...T00:00"`/n=42, eating the
        seconds as a skip count and over-delivering the whole minute.
        `_now_iso()` always writes the trailing `Z`, which is what makes
        the hand-supplied bare-timestamp form distinguishable at all."""
        ts, n = serve._decode_trace_cursor("2026-08-04T00:00:42")
        assert ts == "2026-08-04T00:00:42"
        assert n == 0

    def test_a_digit_suffix_without_the_z_is_not_treated_as_a_count(self) -> None:
        ts, n = serve._decode_trace_cursor("2026-08-04T00:00:42:7")
        assert n == 0
        assert ts == "2026-08-04T00:00:42:7"


class TestTracesPageDirect:
    def test_empty_project_yields_empty_cursor(self, traces_home: Path) -> None:
        events, cursor = serve._traces_page("nobody-home", "")
        assert events == []
        assert cursor == ""

    def test_cursor_advances_past_a_second_boundary(
        self, traces_home: Path, fake_clock: _FakeClock
    ) -> None:
        _trace.trace_event("demo", "s1", "lead", "tool_call", json.dumps({"i": 0}))
        fake_clock.tick()
        events1, cursor1 = serve._traces_page("demo", "")
        assert len(events1) == 1

        _trace.trace_event("demo", "s1", "lead", "tool_call", json.dumps({"i": 1}))
        fake_clock.tick()
        events2, cursor2 = serve._traces_page("demo", cursor1)
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

        events1, cursor1 = serve._traces_page("demo", "")
        assert len(events1) == 2, "first poll must return both sessions' events"

        events2, _cursor2 = serve._traces_page("demo", cursor1)
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
        _events1, cursor1 = serve._traces_page("demo", "")

        self._write("zzz-older-session", 2)
        fake_clock.tick()

        events2, _cursor2 = serve._traces_page("demo", cursor1)
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

        events, _cursor = serve._traces_page("demo", "")
        assert [json.loads(e)["payload"]["i"] for e in events] == [0, 1, 2], (
            "a consumer folding events onto a board reads them in order"
        )


# ── the hold-back rule: a still-open second is never split across a race ────


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
        events1, cursor1 = serve._traces_page("demo", "")
        assert events1 == [], "the second this line landed in is still open"

        _trace.trace_event("demo", "a", "lead", "tool_call", json.dumps({"who": "a"}))
        events2, cursor2 = serve._traces_page("demo", cursor1)
        assert events2 == [], "still open -- a same-second write must not surface yet"
        assert cursor2 == cursor1, "no progress to report while the second stays open"

        fake_clock.tick()
        events3, cursor3 = serve._traces_page("demo", cursor2)
        delivered = {json.loads(e)["payload"]["who"] for e in events3}
        assert delivered == {"a", "b"}, f"expected both lines exactly once, got {events3}"
        assert cursor3 != cursor2

        events4, _cursor4 = serve._traces_page("demo", cursor3)
        assert events4 == [], "nothing left to redeliver on a fourth poll"
