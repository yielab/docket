"""GET /traces/<project>?since=<cursor> — cursor'd raw trace read over HTTP.

Phase 22 (P22-3): this is P20-3's deferral trigger firing -- "grep over
JSONL is adequate" was true for a human operator, false for a programmatic
consumer (Tack) that must resume a poll loop from a cursor without silently
re-ingesting or silently skipping an event. Built entirely on
`core.trace.export_lines(project, since)` (owned elsewhere this wave, used
as-is): raw JSONL lines out, verbatim, one project, one cursor -- no
fleet-wide query, no filtering by event type/role/session.

`export_lines`' own `since` filter is `ts >= since` -- inclusive -- and `ts`
is second-granularity (`%Y-%m-%dT%H:%M:%SZ`). A cursor that is just the last
delivered line's raw ts would therefore either redeliver everything from
that exact second (if reused verbatim) or silently drop later same-second
events (if naively treated as exclusive). `serve._traces_page` compensates
with a compound cursor -- see its docstring and the module-level comment
above it in `src/docket/serve.py` -- and this file's `TestPollLoopBoundary`
class is the test that actually proves it: N events (all but guaranteed to
land in the same wall-clock second in a tight test loop) followed by M more,
read via two polls, asserting the second poll yields exactly M with zero
overlap.

Covers:
  - auth rejection (401)
  - missing project segment -> 400 (both "/traces" and "/traces/")
  - a project with no trace files -> 200, {"events": [], "next": ""}
  - verbatim passthrough (the HTTP response's event strings round-trip
    byte-for-byte through json.loads to the same dict export_lines produced)
  - the poll-loop boundary: exactly-once delivery across a since cursor,
    including the same-second collision case
  - the cursor decoder accepting a bare caller-supplied timestamp too
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
import docket.serve as serve
from docket.core import trace as _trace
from docket.serve import _DocketHandler

_TEST_TOKEN = "test-serve-token-traces-p22-3"


def _point_at(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_cfg, "DOCKET_HOME", home, raising=True)
    monkeypatch.setattr(_cfg, "TRACES_DIR", home / "traces", raising=True)


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
    _point_at(home, monkeypatch)
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
    _point_at(home, monkeypatch)
    return home


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
        self, live_server: tuple[str, str], traces_home: Path
    ) -> None:
        url, token = live_server
        _trace.trace_event(
            "demo", "sess-1", "lead", "session_start", json.dumps({"source": "test"})
        )
        _trace.trace_event(
            "demo", "sess-1", "implementer", "tool_call", json.dumps({"tool": "read"})
        )

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
        self, live_server: tuple[str, str], traces_home: Path
    ) -> None:
        """P22-3 explicitly rejects a fleet-wide query UI with filtering --
        every event for the project comes back, regardless of type/role/
        session, leaving aggregation to the consumer (Tack)."""
        url, token = live_server
        _trace.trace_event("demo", "sess-a", "lead", "session_start", "{}")
        _trace.trace_event("demo", "sess-b", "tester", "verdict_rejected", "{}")

        status, body = _get(f"{url}/traces/demo", token=token)
        assert status == 200
        roles = {json.loads(e)["agent_role"] for e in body["events"]}
        assert roles == {"lead", "tester"}


# ── the boundary that matters most: exactly-once delivery across a poll loop ──


class TestPollLoopBoundary:
    def test_second_poll_from_returned_cursor_yields_exactly_the_new_events(
        self, live_server: tuple[str, str], traces_home: Path
    ) -> None:
        url, token = live_server
        n = 6
        for i in range(n):
            _trace.trace_event("demo", "sess-1", "lead", "tool_call", json.dumps({"i": i}))

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
        self, live_server: tuple[str, str], traces_home: Path
    ) -> None:
        """Directly targets export_lines' second-granularity ts: writes two
        batches back to back with no delay, which routinely land in the same
        wall-clock second, and proves the compound cursor still separates
        them instead of collapsing to duplicate-everything or skip-everything.
        """
        url, token = live_server
        for i in range(5):
            _trace.trace_event("demo", "sess-1", "lead", "tool_call", json.dumps({"i": i}))
        _, body = _get(f"{url}/traces/demo", token=token)
        cursor = body["next"]

        for i in range(5, 9):
            _trace.trace_event("demo", "sess-1", "lead", "tool_call", json.dumps({"i": i}))
        _, body2 = _get(f"{url}/traces/demo?since={cursor}", token=token)
        second_batch = [json.loads(e)["payload"]["i"] for e in body2["events"]]
        assert second_batch == [5, 6, 7, 8]

    def test_three_polls_in_a_row_ingest_every_event_exactly_once(
        self, live_server: tuple[str, str], traces_home: Path
    ) -> None:
        url, token = live_server
        seen: list[int] = []
        cursor = ""
        for wave in range(3):
            for i in range(3):
                _trace.trace_event(
                    "demo", "sess-1", "lead", "tool_call", json.dumps({"wave": wave, "n": i})
                )
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
        """A timestamp CONTAINS colons, so ":<digits>" alone cannot mean "count".

        Without requiring the ts half to end in `Z`, `"...T00:00:42"` splits as
        ts=`"...T00:00"` / n=42: the seconds are eaten as a skip count and the
        cursor silently rewinds to the start of the minute, re-delivering
        everything in it. Over-delivery rather than loss, but it breaks the
        hand-supplied form `_decode_trace_cursor` documents as supported.
        `core/trace.py`'s `_now_iso()` always writes the trailing `Z`, which is
        what makes the two forms distinguishable at all.
        """
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

    def test_cursor_advances_past_a_second_boundary(self, traces_home: Path) -> None:
        _trace.trace_event("demo", "s1", "lead", "tool_call", json.dumps({"i": 0}))
        events1, cursor1 = serve._traces_page("demo", "")
        assert len(events1) == 1

        time.sleep(1.05)
        _trace.trace_event("demo", "s1", "lead", "tool_call", json.dumps({"i": 1}))
        events2, cursor2 = serve._traces_page("demo", cursor1)
        assert len(events2) == 1
        assert json.loads(events2[0])["payload"]["i"] == 1
        assert cursor2 != cursor1
