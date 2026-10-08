"""Run cancellation: request it and signal any in-flight process groups."""

from __future__ import annotations

from docket import ui
from docket.core import runs as _runs


def _cancel(args: list[str]) -> int:
    """Request cancellation and signal any in-flight process groups."""
    if not args:
        ui.error("Usage: docket runs cancel <id>")
        return 1
    run_id = args[0]
    outcome = _runs.cancel_run(run_id)
    if not outcome.ok:
        ui.error(outcome.message)
        return 1
    ui.success(outcome.message)
    return 0
