"""Scheduled dispatch — cron-like spec parsing for serve.

Schedules are read from ``SCHEDULE_FILE`` (default
``~/.openclaw/docket-schedules.json``):

  {"schedules": {"myproject": "@every 30m", "otherproject": "09:00"},
   "lastRun": {"myproject": 1721000000.0}}

Supported formats
-----------------
``@every <N><unit>``
    Fire every N seconds (s), minutes (m), or hours (h) since the last run.
``HH:MM``
    Fire once daily at the given UTC time.

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
