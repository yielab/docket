from __future__ import annotations

import datetime as _dt
import json
import urllib.parse as _urlparse

from docket.interfaces.http.exchange import HttpExchange
from docket.kernel import clock as _clock
from docket.observability import trace as _trace

# ── /traces/<project> cursor paging ─────────────────────────────────────────
#
# Built entirely on `observability.trace.export_lines(project, since)` — owned by
# another card this wave, used here exactly as it stands. That function's
# `since` filter is `ts >= since`: inclusive, and second-granularity (`ts` is
# `%Y-%m-%dT%H:%M:%SZ`). Both properties matter for a poll loop that must
# ingest every event exactly once:
#
#   * Inclusive means the naive cursor — "next = last event's ts" — would
#     redeliver that same last event (and anything else sharing its second)
#     on the very next poll.
#   * Second granularity means several events sharing one timestamp is
#     routine, not an edge case (a single dispatch hop can emit several trace
#     events inside the same wall-clock second), so "ts > cursor" instead of
#     "ts >= cursor" would silently DROP any same-second event that arrives
#     after the poll that first saw that second, rather than deliver it late.
#
# The cursor this module mints is therefore a compound "<ts>:<n>" token: n is
# how many lines carrying that exact ts have already gone out. Re-querying at
# ts re-fetches that whole second (inclusive filter), and the first n of them
# — stable, since trace files are append-only and never reordered — are
# exactly the ones already delivered, so they're dropped before the response
# is built. See `_traces_page`.
#
# That "stable, never reordered" premise holds only within one poll's page —
# NOT across two polls, because `export_lines` concatenates session files in
# *filename* order, and a brand-new file can sort earlier than one already on
# disk. A page delivering ts=S from file "b" and minting "S:1" can be followed
# by a write to file "a" at that same ts=S; the next poll's concatenation puts
# "a" before "b", so "skip the first 1 line at S" now skips "a" instead of
# "b" — redelivering "b" and permanently losing "a". The one-second hold-back
# below closes that race: nothing with ts >= now - 1s is ever handed out, so
# by the time any line at ts=S is delivered, no writer can still be mid-write
# for that second and every same-second sibling is already on disk.


# Seconds a trace event must have aged before `_traces_page` will hand it
# out -- see the hold-back rationale above.
_TRACE_HOLD_BACK_S = 1


def _trace_line_ts(line: str) -> str:
    """Best-effort ts extraction for cursor bookkeeping -- mirrors
    `export_lines`' own parsing exactly so "which second" never diverges from
    the filter it compensates for. Returns "" when unkeyable."""
    try:
        parsed = json.loads(line)
    except (json.JSONDecodeError, RecursionError):
        return ""
    if not isinstance(parsed, dict):
        return ""
    return str(parsed.get("ts", ""))


def _decode_trace_cursor(raw: str) -> tuple[str, int]:
    """Decode a `since` value into (ts, lines already delivered at ts).

    Accepts both a minted `"<ts>:<n>"` cursor and a bare ISO timestamp a caller supplies by hand
    (n=0). Requires the ts half to end in `Z` to tell them apart: a timestamp CONTAINS colons, so
    a bare `"...T12:34:56"`'s own trailing seconds would otherwise misparse as the digit count,
    silently rewinding the cursor and re-delivering that minute. See
    specs/data/serve-read-api.spec.md (cursor semantics)."""
    if not raw:
        return "", 0
    ts, sep, tail = raw.rpartition(":")
    if sep and tail.isdigit() and ts.endswith("Z"):
        return ts, int(tail)
    return raw, 0


def _traces_page(project: str, since: str) -> tuple[list[str], str]:
    """One cursor'd page of *project*'s raw trace JSONL, delivered exactly once (sorted by ts
    across session files, held back within `_TRACE_HOLD_BACK_S` of now, verbatim otherwise
    unfiltered). Returns (lines, next_cursor); cursor contract:
    specs/data/serve-read-api.spec.md (GET /traces/<project>).

    A trailing line this module cannot key on (`_trace_line_ts` returns "") is a pre-existing
    `export_lines` limitation, not fixed here: it is always returned (nothing already-fetched is
    silently dropped), but the next cursor anchors on the last line this function CAN key on,
    never on "" -- which would collapse the filter and replay the whole project's trace."""
    cursor_ts, already = _decode_trace_cursor(since)
    # `export_lines` concatenates session files in sorted FILENAME order, and a
    # session id is a uuid -- so with more than one session (any project with
    # history) the raw stream is not chronological. Everything below anchors the
    # cursor on the newest event in the page and counts the run sharing that
    # second, which is only correct on an ordered page; without this sort a
    # multi-session project replays the events that happened to follow the
    # anchor in glob order. Stable, so same-second lines keep their file order,
    # and unkeyable ("") lines sort to the front where the skip loop expects them.
    lines = sorted(_trace.export_lines(project, cursor_ts), key=_trace_line_ts)

    # Hold back anything from a second that might not be closed yet (see the
    # rationale above `_TRACE_HOLD_BACK_S`) -- an unkeyable ("") line always passes through,
    # same as everywhere else in this function.
    threshold = (_clock.now() - _dt.timedelta(seconds=_TRACE_HOLD_BACK_S)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    lines = [ln for ln in lines if (ts := _trace_line_ts(ln)) == "" or ts < threshold]

    if already:
        skipped = 0
        i = 0
        while i < len(lines) and skipped < already:
            ts = _trace_line_ts(lines[i])
            if ts == cursor_ts:
                skipped += 1
                i += 1
            elif ts == "":
                # Always re-included regardless of position (see docstring)
                # -- pass over without spending the skip budget on it.
                i += 1
            else:
                break
        lines = lines[i:]

    if not lines:
        return [], since

    anchor_idx = -1
    anchor_ts = ""
    for idx in range(len(lines) - 1, -1, -1):
        ts = _trace_line_ts(lines[idx])
        if ts:
            anchor_idx, anchor_ts = idx, ts
            break
    if anchor_idx == -1:
        # Nothing in this page has a usable ts -- cannot safely advance past
        # the incoming cursor without risking a full replay next time.
        return lines, since

    # How many lines, counting backward from anchor_idx, carry that exact ts
    # -- the size of the trailing same-second run the next poll must skip.
    count_at_anchor = 0
    for idx in range(anchor_idx, -1, -1):
        if _trace_line_ts(lines[idx]) != anchor_ts:
            break
        count_at_anchor += 1
    if anchor_ts == cursor_ts:
        count_at_anchor += already
    return lines, f"{anchor_ts}:{count_at_anchor}"


def get_traces(h: HttpExchange, project: str) -> None:
    """``GET /traces/<pod>?since=<cursor>``; the bare ``/traces`` is the missing-project `400`."""
    if not project:
        h._send_json_error("Missing project", 400)
        return
    if h._reject_bad_project_id(project):
        return
    query = _urlparse.parse_qs(_urlparse.urlsplit(h.path).query)
    since_values = query.get("since")
    since = since_values[0] if since_values else ""
    events, next_cursor = _traces_page(project, since)
    body = json.dumps({"events": events, "next": next_cursor}).encode("utf-8")
    h._send(body, "application/json")
