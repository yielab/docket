"""The traces cursor endpoint over a real loopback server: auth, empty projects, passthrough and the poll loop."""

from __future__ import annotations

import dataclasses
import json
import threading
from pathlib import Path

import pytest
from tests.support import traces_cursor_harness as _shared
from tests.support.http import get as _get
from tests.support.traces_cursor_harness import (
    _ClockedHandler,
    _FakeClock,
)

from docket.kernel.home import Home, current_home, use_home
from docket.kernel.threads import ContextHTTPServer
from docket.observability import trace as _trace

SUBJECT = "docket.interfaces.http.routes.traces"

fake_clock = _shared.fake_clock
traces_home = _shared.traces_home


_TEST_TOKEN = "test-serve-token-traces-p22-3"


@pytest.fixture()
def live_server(tmp_path: Path):  # type: ignore[no-untyped-def]
    home = tmp_path / ".docket"
    home.mkdir(exist_ok=True)
    with use_home(Home(home)):
        approvals_dir = tmp_path / "approvals"
        approvals_dir.mkdir()
        with use_home(dataclasses.replace(current_home(), approvals_dir_override=approvals_dir)):

            class _Handler(_ClockedHandler):
                serve_token = _TEST_TOKEN

            srv = ContextHTTPServer(("127.0.0.1", 0), _Handler)
            port = srv.server_address[1]
            t = threading.Thread(target=srv.serve_forever, daemon=True)
            t.start()
            yield f"http://127.0.0.1:{port}", _TEST_TOKEN
            srv.shutdown()


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
        _trace.trace_event("demo", "sess-b", "reviewer", "verdict_rejected", "{}")
        fake_clock.tick()

        status, body = _get(f"{url}/traces/demo", token=token)
        assert status == 200
        roles = {json.loads(e)["agent_role"] for e in body["events"]}
        assert roles == {"lead", "reviewer"}


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
