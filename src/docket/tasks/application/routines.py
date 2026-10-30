"""Routines: a pod creates its own tasks on a schedule.

``fire_due`` is called once per ``docket start --dispatch`` sweep. For each dispatchable pod it loads
the ``kind: routine`` documents of the pod's scopes, works out which slots are due since the routine
last fired, and enqueues one task for them with ``enqueue_task_once`` and an idempotency key per
slot. The last fired slot lives in ``Home.routines_state_file`` (written after the enqueue, so a
lost write fires the same key again and creates nothing). Slots are evaluated in the routine's
own zone with the cron and ``@every`` parsers of ``pipeline/application/schedule.py``. See
specs/functional/pod-dispatch.spec.md "Routines".
"""

from __future__ import annotations

import datetime as _dt
import json
import zoneinfo
from dataclasses import dataclass
from typing import Any

from docket.governance import audit as _audit
from docket.kernel import clock as _clock
from docket.kernel.errors import DispatchError
from docket.kernel.home import current_home
from docket.observability import trace as _trace
from docket.pipeline.application import schedule as _schedule
from docket.platform import read_json, read_modify_write
from docket.tasks.application import queue as _queue
from docket.tasks.application.repository import TaskRepository
from docket.tasks.domain.routine import CHANNEL, Routine, stamp
from docket.teams import config_docs as _config_docs

# Slots older than this are never examined, so a long outage costs a bounded scan.
LOOKBACK = _dt.timedelta(days=31)
# How far ahead `next_slot` looks for a cron schedule that matches rarely (29 February).
_HORIZON_DAYS = 366 * 8
_SCOPE_LABELS = ("pod", "operator")


@dataclass(frozen=True)
class Due:
    """The slots in a window: the first and the latest of them, and how many."""

    first: _dt.datetime
    latest: _dt.datetime
    count: int


def _day_slots(
    fields: tuple[frozenset[int], ...], zone: zoneinfo.ZoneInfo, day: _dt.date
) -> list[_dt.datetime]:
    """The slots of local date *day* as UTC instants. A local time the clock skips has none, and
    one it repeats has one, the first."""
    minute, hour, dom, month, dow = fields
    if day.day not in dom or day.month not in month:
        return []
    if day.isoweekday() % 7 not in {0 if v == 7 else v for v in dow}:
        return []
    slots: list[_dt.datetime] = []
    for h in sorted(hour):
        for m in sorted(minute):
            local = _dt.datetime(day.year, day.month, day.day, h, m, tzinfo=zone)
            utc = local.astimezone(_dt.UTC)
            if utc.astimezone(zone).replace(tzinfo=None) == local.replace(tzinfo=None):
                slots.append(utc)
    return slots


def _cron(routine: Routine) -> tuple[tuple[frozenset[int], ...], zoneinfo.ZoneInfo] | None:
    fields = _schedule.parse_cron(routine.schedule)
    return None if fields is None else (fields, zoneinfo.ZoneInfo(routine.tz))


def due(routine: Routine, after: _dt.datetime, until: _dt.datetime) -> Due | None:
    """The slots of *routine* after *after* up to and including *until*, or ``None`` when there
    are none. An ``@every`` routine has a slot every interval from *after*."""
    after = max(after, until - LOOKBACK)
    interval = _schedule.parse_interval(routine.schedule)
    if interval is not None:
        count = int((until - after).total_seconds() // interval)
        if count < 1:
            return None
        step = _dt.timedelta(seconds=interval)
        return Due(after + step, after + count * step, count)
    parsed = _cron(routine)
    if parsed is None:
        return None
    fields, zone = parsed
    slots: list[_dt.datetime] = []
    day = after.astimezone(zone).date()
    last_day = until.astimezone(zone).date()
    while day <= last_day:
        slots.extend(s for s in _day_slots(fields, zone, day) if after < s <= until)
        day += _dt.timedelta(days=1)
    return Due(slots[0], slots[-1], len(slots)) if slots else None


def next_slot(routine: Routine, after: _dt.datetime) -> _dt.datetime | None:
    """The first slot of *routine* after *after*, or ``None`` when its schedule has no slot in
    the next eight years."""
    interval = _schedule.parse_interval(routine.schedule)
    if interval is not None:
        return after + _dt.timedelta(seconds=interval)
    parsed = _cron(routine)
    if parsed is None:
        return None
    fields, zone = parsed
    day = after.astimezone(zone).date()
    for _ in range(_HORIZON_DAYS):
        for slot in _day_slots(fields, zone, day):
            if slot > after:
                return slot
        day += _dt.timedelta(days=1)
    return None


def load_routines(pod: str) -> tuple[list[Routine], list[str]]:
    """The routines *pod* resolves, by name, nearest scope first (the pod's overlay, then the
    operator's), and one line for each file that does not load."""
    found: dict[str, Routine] = {}
    problems: list[str] = []
    for label, directory in zip(
        _SCOPE_LABELS, current_home().scopes("routines", pod), strict=False
    ):
        if not directory.is_dir():
            continue
        for path in sorted([*directory.glob("*.yaml"), *directory.glob("*.yml")]):
            try:
                document = _config_docs.load_document(path, kind="routine")
            except _config_docs.ConfigDocError as exc:
                problems.append(str(exc))
                continue
            if document.kind != "routine":
                problems.append(f"{path}: kind {document.kind!r} is not a routine")
                continue
            found.setdefault(
                document.name, Routine.from_document(document.doc, scope=label, path=str(path))
            )
    return [found[name] for name in sorted(found)], problems


def routine_state(pod: str, name: str) -> dict[str, str]:
    """What the state file holds for *pod*'s routine *name*: ``seen`` and ``lastSlot``."""
    entry = read_json(current_home().routines_state_file).get("routines", {}).get(f"{pod}/{name}")
    return {k: str(v) for k, v in entry.items()} if isinstance(entry, dict) else {}


def _record(pod: str, name: str, **fields: str) -> None:
    def _fn(doc: dict[str, Any]) -> dict[str, Any]:
        routines = doc.setdefault("routines", {})
        routines.setdefault(f"{pod}/{name}", {}).update(fields)
        return doc

    read_modify_write(current_home().routines_state_file, _fn)


def _skipped(pod: str, routine: Routine, slot: _dt.datetime, reason: str) -> None:
    _trace.trace_event(
        pod,
        f"routine:{pod}:{routine.name}",
        "lead",
        "step_skipped",
        json.dumps({"routine": routine.name, "slot": stamp(slot), "reason": reason}),
    )


def _unfinished(pod: str, routine: Routine, key: str) -> bool:
    """Whether a task this routine fired for another slot has not finished."""
    return any(
        r.idempotency_key is not None
        and r.idempotency_key.startswith(routine.key_prefix)
        and r.idempotency_key != key
        and not r.is_terminal
        for r in TaskRepository.for_pod(pod).list()
    )


def _window(pod: str, routine: Routine, moment: _dt.datetime) -> Due | None:
    """The slots of *routine* due at *moment* since it last fired; the first sighting is recorded."""
    state = routine_state(pod, routine.name)
    seen = _clock.parse_iso(state.get("seen"))
    last = _clock.parse_iso(state.get("lastSlot"))
    if seen is None and last is None:
        seen = moment.replace(microsecond=0)
        _record(pod, routine.name, seen=stamp(seen))
    base = last or seen
    assert base is not None
    interval = _schedule.parse_interval(routine.schedule)
    if last is None and interval is not None:
        base -= _dt.timedelta(seconds=interval)  # the moment it is first seen is its first slot
    return due(routine, base, moment)


def _fire(pod: str, routine: Routine, moment: _dt.datetime) -> list[str]:
    window = _window(pod, routine, moment)
    if window is None:
        return []
    slot = window.latest
    key = routine.key_for(slot)
    missed = window.count - 1
    description = routine.task_description
    if missed and routine.catch_up == "once":
        description += (
            f"\n\n(catch-up: {window.count} scheduled runs were missed; "
            "this one run stands for all of them)"
        )
    created: list[str] = []
    if routine.overlap == "skip" and _unfinished(pod, routine, key):
        _skipped(pod, routine, slot, "overlap")
    else:
        try:
            task, is_new = _queue.enqueue_task_once(
                pod,
                description,
                routine.priority,
                channel=CHANNEL,
                idempotency_key=key,
                pipeline=routine.pipeline,
                variables=routine.variables or None,
            )
        except DispatchError as exc:
            _skipped(pod, routine, slot, f"refused: {exc}")
        else:
            if is_new:
                created.append(task.id)
                _audit.audit_log(
                    "routine.fire",
                    f"project={pod} routine={routine.name} slot={stamp(slot)} task={task.id}",
                )
            if missed and routine.catch_up == "skip":
                _skipped(pod, routine, slot, f"missed {missed} earlier slot(s)")
    _record(pod, routine.name, lastSlot=stamp(slot))
    return created


def fire_due(now: float | None = None) -> list[str]:
    """Enqueue the task of every enabled routine of every dispatchable pod that has a slot due at
    *now* (epoch seconds, default the kernel clock); the ids of the tasks created."""
    moment = _dt.datetime.fromtimestamp(_clock.epoch() if now is None else now, tz=_dt.UTC)
    created: list[str] = []
    for pod in _queue.dispatchable_pods():
        routines, _problems = load_routines(pod)
        for routine in routines:
            if routine.enabled:
                created.extend(_fire(pod, routine, moment))
    return created


def status(pod: str, routine: Routine, now: _dt.datetime) -> dict[str, Any]:
    """One routine as ``docket pod routine list`` shows it: its fields, the next slot (UTC) and
    the last fired slot (``None`` when it never fired)."""
    last = routine_state(pod, routine.name).get("lastSlot")
    last_at = _clock.parse_iso(last)
    if _schedule.parse_interval(routine.schedule) is None:
        upcoming = next_slot(routine, now)
    else:  # an @every routine is due at once when it never fired, else one interval after
        upcoming = next_slot(routine, last_at) if last_at is not None else now
    return {
        "name": routine.name,
        "schedule": routine.schedule,
        "tz": routine.tz,
        "scope": routine.scope,
        "enabled": routine.enabled,
        "catchUp": routine.catch_up,
        "overlap": routine.overlap,
        "next": stamp(upcoming) if upcoming is not None else None,
        "last": last,
    }
