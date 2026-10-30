from __future__ import annotations

import concurrent.futures
import signal
import threading
from collections.abc import Callable
from typing import Any

from docket.hops.application import sweep as _sweep
from docket.kernel import threads as _threads
from docket.kernel.home import current_home
from docket.pipeline.application import schedule as _sched
from docket.tasks.application import routines as _routines
from docket.tasks.application import runs as _runs

_SWEEP_LOCK = threading.Lock()
sweep_inflight: dict[str, concurrent.futures.Future[None]] = {}
sweep_run_ids: dict[str, str] = {}
# How long a second stop signal waits for cancelled sweep runs to settle before exiting anyway.
SWEEP_ABANDON_WAIT_S = 5.0


def check_schedules(now_ts: float) -> None:
    """Trigger dispatch for pods whose schedule spec is due (also recognizes a standard 5-field
    cron expression, not just ``@every``/``HH:MM`` -- see ``pipeline/application/schedule.py``). The last-run
    timestamp is read from, and written back into, ``Home.schedule_file`` itself rather than an
    in-memory dict, so a restart does not re-fire every schedule on its first sweep. Each due
    project's run record is created before its daemon-thread dispatch starts, so the sweep loop
    is never blocked and no outcome is silently discarded. Routines (pod-dispatch.spec.md
    "Routines") fire first, on the same tick: they only enqueue, and the next sweep drains them."""

    try:
        _routines.fire_due(now_ts)
    except Exception as exc:
        print(f"[serve] sweep: routines failed: {exc}")
    schedules = _sched.load_schedules(current_home().schedule_file)
    last_run_map = _sched.load_last_run(current_home().schedule_file)
    for project, spec in schedules.items():
        reason = _sched.describe_spec_error(spec)
        if reason:
            # `is_schedule_due` would otherwise treat this as silently never-due, forever
            # -- print once per sweep so an operator running `docket start` sees the drop
            # instead of a schedule that quietly never fires (see `docket setup --fix` for the
            # equivalent standing report).
            print(f"[serve] sweep: schedule '{project}' skipped — {reason}")
            continue
        last_run = last_run_map.get(project, 0.0)
        if not _sched.is_schedule_due(spec, last_run, now_ts):
            continue
        _sched.record_last_run(current_home().schedule_file, project, now_ts)

        record = _runs.create_run("schedule", project)

        def _run(proj: str = project, run_id: str = record["id"]) -> None:
            # Process-wide timeout knobs (unset = no override) run inside the
            # run record, so a scheduled dispatch is both configurable and
            # observable rather than fire-and-forget.
            _runs.execute(
                run_id,
                lambda: _sweep.dispatch_pod(
                    proj,
                    turn_timeout=current_home().dispatch_turn_timeout_s,
                    verify_timeout=current_home().dispatch_verify_timeout_s,
                ),
            )

        _threads.start_thread(_run)


def _drain_sweeps(timeout: float | None = None) -> bool:
    """Wait for every in-flight pod sweep; True when none remain within *timeout*."""
    with _SWEEP_LOCK:
        pending = list(sweep_inflight.values())
    _done, not_done = concurrent.futures.wait(pending, timeout=timeout)
    return not not_done


def _pending_sweeps() -> int:
    with _SWEEP_LOCK:
        return len(sweep_inflight)


class _StopController:
    """Two-stage stop for ``run_serve``: the first signal stops accepting work and lets in-flight
    sweeps finish, the second abandons them. Handlers only flip state; slow work runs on threads."""

    def __init__(
        self,
        stop: threading.Event,
        shutdown_server: Callable[[], None],
        on_abandon: Callable[[], object],
        pending: Callable[[], int] = _pending_sweeps,
    ) -> None:
        self.stop = stop
        self.abandon = threading.Event()
        self.exit_code = 0
        self._shutdown_server = shutdown_server
        self._on_abandon = on_abandon
        self._pending = pending
        self._signals = 0

    @property
    def stopping(self) -> bool:
        return self.stop.is_set()

    def handle(self, signum: int, _frame: object = None) -> None:
        self._signals += 1
        if self._signals == 1:
            self.stop.set()
            print(
                f"stopping: waiting for {self._pending()} pod sweep(s); signal again to abandon",
                flush=True,
            )
            _threads.start_thread(self._shutdown_server)
        elif self._signals == 2:
            self.exit_code = 128 + signum
            self.abandon.set()
            _threads.start_thread(self._on_abandon)

    def install(self) -> dict[int, Any]:
        """Install SIGINT/SIGTERM handlers (main thread only); returns the previous handlers."""
        if threading.current_thread() is not threading.main_thread():
            return {}
        return {s: signal.signal(s, self.handle) for s in (signal.SIGINT, signal.SIGTERM)}
