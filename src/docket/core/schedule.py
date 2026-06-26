"""Scheduled dispatch — cron-like spec parsing for serve.

Schedules are read from ``SCHEDULE_FILE`` (default
``~/.openclaw/docket-schedules.json``):

  {"schedules": {"myproject": "@every 30m", "otherproject": "09:00"}}

Supported formats
-----------------
``@every <N><unit>``
    Fire every N seconds (s), minutes (m), or hours (h) since the last run.
``HH:MM``
    Fire once daily at the given UTC time.

This module is pure-stdlib and side-effect-free (no filesystem access in the
parsing functions). ``load_schedules`` is the only I/O entry-point.
"""

from __future__ import annotations

import datetime as _dt
import json
import re
from pathlib import Path


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
