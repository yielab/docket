"""``docket notify`` -- manually flush operator events to every enabled channel, or preview
what a flush would send without delivering (``--dry-run``).

``serve.py``'s sweep and ``docket run`` already call `core.notify.flush` after
every real state change (ADR 0016 SS7); this command exists for an operator who wants to force
one between those points, or inspect what is pending first.
"""

from __future__ import annotations

import datetime as _dt

from docket import ui
from docket.core import channel as _channel
from docket.core import inbox as _inbox
from docket.core import notify as _notify
from docket.edges.adapters import channels as _channels


def _utc_now() -> str:
    return _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _run_dry_run() -> int:
    now = _utc_now()
    prev = _notify.read_state()
    inbox = _inbox.build_inbox(now=now)
    events, _snapshot = _notify.diff_events(prev, inbox, now)

    ui.header("Notify (dry run)")
    ui.console.print()
    if not events:
        ui.dim("  Nothing to send.")
        return 0
    for event in events:
        ui.console.print(f"  {event.kind}  pod={event.pod}  subject={event.subject}")
    ui.console.print()
    ui.dim("  Nothing delivered -- the persisted snapshot was not touched.")
    return 0


def _run_flush() -> int:
    specs = list(_channel.load_catalog().entries.values())
    report = _notify.flush(specs, _channels.sink_for, now=_utc_now())
    if report.events == 0:
        ui.dim("Nothing to send.")
        return 0
    ui.success(
        f"Flushed: {report.events} event(s), {report.delivered} delivered, "
        f"{report.failed} failed, {report.skipped} skipped"
    )
    return 1 if report.failed else 0


def run_notify(action: str, args: list[str]) -> int:
    """Dispatch one ``docket notify <action> ...`` call. Returns a process exit code."""
    if action != "flush":
        shown = f"Unknown notify action '{action}'." if action else "notify needs an action."
        ui.error(f"{shown}\nUsage:\n  docket notify flush [--dry-run]")
        return 2
    if "--dry-run" in args:
        return _run_dry_run()
    return _run_flush()
