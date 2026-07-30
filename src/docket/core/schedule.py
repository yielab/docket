"""Scheduled dispatch — cron-like spec parsing for serve.

Schedules are read from ``SCHEDULE_FILE`` (default
``~/.openclaw/docket-schedules.json``):

  {"schedules": {"myproject": "@every 30m", "otherproject": "09:00",
                  "athird": "*/15 9-17 * * 1-5"},
   "lastRun": {"myproject": 1721000000.0}}

Supported formats
-----------------
``@every <N><unit>``
    Fire every N seconds (s), minutes (m), or hours (h) since the last run.
``HH:MM``
    Fire once daily at the given UTC time.
``<min> <hour> <dom> <month> <dow>`` (ROADMAP Phase 16 W-4)
    A standard 5-field cron expression, evaluated in UTC. Each field accepts
    ``*``, a single integer, a comma-separated list, an ``a-b`` range, and a
    ``/n`` step on either ``*`` or a range (e.g. ``*/15``, ``9-17/2``). Month
    and day-of-week are numeric only (1-12, 0-6 with 0 **and** 7 both meaning
    Sunday — the standard cron convention) — no name aliases (``JAN``,
    ``MON``) are recognised, keeping the parser small and stdlib-only per
    ROADMAP §4.5's dependency ban (a full cron grammar, including name
    aliases and the ``L``/``W``/``#`` extensions some implementations add, is
    deliberately out of scope). Due-ness is evaluated per-minute, not
    per-second: a cron schedule fires at most once for any given matching
    minute, the instant the sweep loop first observes that minute with a
    last-run timestamp still older than it — exactly like every other spec
    format here, this is a polling design (see ``is_schedule_due``), not a
    real-time trigger; a sweep interval longer than a minute can miss firing
    for a matching minute that fell entirely between two sweeps.

This module is pure-stdlib. The spec-parsing functions are side-effect-free
(no filesystem access). ``load_schedules``/``load_last_run`` are read-only I/O
entry points; ``record_last_run`` is the one write path — it persists into the
same file, under a ``lastRun`` key sitting alongside ``schedules``, via
``edges/store.py``'s locked read-modify-write (docket-owned JSON, single-writer
rule applies). Before R-3, the last-run timestamp lived only in an in-memory
``dict`` in ``serve.py``, so every ``docket serve`` restart re-fired every due
schedule immediately — persisting it here is what fixes that.
"""

from __future__ import annotations

import datetime as _dt
import json
import re
from pathlib import Path
from typing import Any

from docket.edges import store as _store


def parse_interval(spec: str) -> int | None:
    """Return the interval in seconds for an ``@every`` spec, or None."""
    m = re.match(r"@every\s+(\d+)([smh])$", spec.strip())
    if not m:
        return None
    n = int(m.group(1))
    return n * {"s": 1, "m": 60, "h": 3600}[m.group(2)]


def parse_daily_time(spec: str) -> tuple[int, int] | None:
    """Return ``(hour, minute)`` UTC for an ``HH:MM`` spec, or None."""
    m = re.match(r"^(\d{1,2}):(\d{2})$", spec.strip())
    if not m:
        return None
    h, mn = int(m.group(1)), int(m.group(2))
    if 0 <= h < 24 and 0 <= mn < 60:
        return h, mn
    return None


# (min, max) per cron field, in field order: minute hour dom month dow.
# dow's max is 7, not 6, so a literal "7" parses as an allowed value before
# _cron_matches normalizes it to 0 (both mean Sunday — the standard cron dow
# convention); a bare "*" already covers 0-6 either way.
_CRON_FIELD_RANGES: tuple[tuple[int, int], ...] = ((0, 59), (0, 23), (1, 31), (1, 12), (0, 7))


def _parse_cron_field(field: str, lo: int, hi: int) -> frozenset[int] | None:
    """Parse one cron field (``*``, ``N``, ``a-b``, a ``/step``, or a
    comma-list of any of those) into the concrete set of values it matches
    within ``[lo, hi]``, or None if the field is malformed or out of range."""
    values: set[int] = set()
    for part in field.split(","):
        part = part.strip()
        if not part:
            return None
        base, step = part, 1
        if "/" in part:
            base, step_s = part.split("/", 1)
            if not step_s.isdigit() or int(step_s) <= 0:
                return None
            step = int(step_s)
        if base == "*":
            start, end = lo, hi
        elif "-" in base:
            a_s, b_s = base.split("-", 1)
            if not (a_s.isdigit() and b_s.isdigit()):
                return None
            start, end = int(a_s), int(b_s)
        elif base.isdigit():
            start = end = int(base)
        else:
            return None
        if start > end or start < lo or end > hi:
            return None
        values.update(range(start, end + 1, step))
    return frozenset(values) if values else None


def parse_cron(spec: str) -> tuple[frozenset[int], ...] | None:
    """Parse a 5-field ``minute hour dom month dow`` cron expression.

    Returns a 5-tuple of value sets (one per field, in that order), or None
    if *spec* is not a well-formed 5-field cron expression — including
    "doesn't even look like one" (not exactly 5 whitespace-separated
    fields), so this doubles as the format's recognizer: a caller can try
    this after ``parse_interval``/``parse_daily_time`` both return None
    without needing a separate "is this a cron spec" check.
    """
    fields = spec.strip().split()
    if len(fields) != 5:
        return None
    parsed = []
    for field, (lo, hi) in zip(fields, _CRON_FIELD_RANGES, strict=True):
        values = _parse_cron_field(field, lo, hi)
        if values is None:
            return None
        parsed.append(values)
    return tuple(parsed)


def _cron_matches(fields: tuple[frozenset[int], ...], moment: _dt.datetime) -> bool:
    """Whether *moment* (a UTC datetime) falls on one of *fields*'s matches."""
    minute, hour, dom, month, dow = fields
    cron_dow = moment.isoweekday() % 7  # Python Mon=1..Sun=7 -> cron Sun=0..Sat=6
    dow_norm = frozenset(0 if v == 7 else v for v in dow)
    return (
        moment.minute in minute
        and moment.hour in hour
        and moment.day in dom
        and moment.month in month
        and cron_dow in dow_norm
    )


def _floor_to_minute(ts: float) -> float:
    """*ts* truncated down to the start of its minute (seconds/micros zeroed)."""
    dt = _dt.datetime.fromtimestamp(ts, tz=_dt.UTC).replace(second=0, microsecond=0)
    return dt.timestamp()


def is_schedule_due(spec: str, last_run_ts: float, now_ts: float) -> bool:
    """Return True if *spec* is due for a run given the last-run timestamp.

    ``last_run_ts`` and ``now_ts`` are POSIX timestamps (float seconds since
    epoch). Pass ``0.0`` as ``last_run_ts`` to force the first fire.

    An unrecognised spec is silently treated as not due (never fires) so bad
    specs don't crash the sweep loop.
    """
    interval = parse_interval(spec)
    if interval is not None:
        return (now_ts - last_run_ts) >= interval

    daily = parse_daily_time(spec)
    if daily is not None:
        h, mn = daily
        now_dt = _dt.datetime.fromtimestamp(now_ts, tz=_dt.UTC)
        # The most recent occurrence of HH:MM before *now*.
        target = now_dt.replace(hour=h, minute=mn, second=0, microsecond=0)
        if target > now_dt:
            target -= _dt.timedelta(days=1)
        last_dt = _dt.datetime.fromtimestamp(last_run_ts, tz=_dt.UTC)
        return last_dt < target

    cron = parse_cron(spec)
    if cron is not None:
        now_dt = _dt.datetime.fromtimestamp(now_ts, tz=_dt.UTC)
        if not _cron_matches(cron, now_dt):
            return False
        # Fire at most once per matching minute: due only the first time this
        # minute is observed with a last-run timestamp still older than it.
        return last_run_ts < _floor_to_minute(now_ts)

    return False  # unrecognised format — silently skip


def load_schedules(path: Path) -> dict[str, str]:
    """Read ``{project: spec}`` from *path*. Returns ``{}`` on any error."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {str(k): str(v) for k, v in data.get("schedules", {}).items()}
    except Exception:
        return {}


def load_last_run(path: Path) -> dict[str, float]:
    """Read ``{project: epoch-seconds}`` of last dispatch attempt from *path*.

    Returns ``{}`` on any error (missing file, malformed JSON, wrong shape) —
    the same tolerance as ``load_schedules``, so a corrupt or absent schedules
    file never crashes the sweep loop; a project simply looks like it has
    never run (fires on the next due check, same as today's fresh-start
    behaviour).
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        raw = data.get("lastRun", {})
        return {str(k): float(v) for k, v in raw.items()}
    except Exception:
        return {}


def record_last_run(path: Path, project: str, ts: float) -> None:
    """Persist *project*'s last-dispatch-attempt timestamp into *path*.

    A locked read-modify-write (``edges/store.py``) against the same file
    ``load_schedules``/``load_last_run`` read — the ``schedules`` key is
    preserved untouched, only ``lastRun[project]`` is updated. This is what
    makes the due-check survive a ``docket serve`` restart instead of
    re-firing every schedule on the first sweep.
    """

    def _fn(doc: dict[str, Any]) -> dict[str, Any]:
        schedules_raw = doc.get("schedules")
        schedules = schedules_raw if isinstance(schedules_raw, dict) else {}
        last_run_raw = doc.get("lastRun")
        last_run_current = last_run_raw if isinstance(last_run_raw, dict) else {}
        last_run = dict(last_run_current)
        last_run[project] = ts
        return {"schedules": schedules, "lastRun": last_run}

    _store.read_modify_write(path, _fn)
