"""Command: serve — local HTTP endpoints for dashboards / monitoring.

Endpoint list, JSON/Prometheus schemas, and the auth model per endpoint: see
specs/data/serve-read-api.spec.md. Binds to 127.0.0.1 by default; ``run_serve``'s ``bind`` can
widen that, but nothing here recommends or automates it -- treat any non-loopback bind as an
explicit, on-you decision (no network ACL here, only the bearer token). A random Bearer token
(``DOCKET_SERVE_TOKEN`` pins a fixed one) gates every /approvals, /runs, /tasks, /traces, /pods
and /dispatch request, checked with ``secrets.compare_digest`` (never ``==``); printed at startup
or written to a 0600 file via ``--token-file``/``token_file=`` when stdout is unsafe (e.g. a
systemd journal).
Every dispatch is recorded in ``tasks.application.runs`` before it starts and folded to a terminal state when it
finishes, so "done"/"failed"/"never ran" stay distinguishable; no call site swallows it silently."""

from __future__ import annotations

import concurrent.futures
import contextlib
import json
import os
import signal
import sys
import threading
from pathlib import Path

from docket import bootstrap as _bootstrap
from docket.agent import conversations
from docket.governance import approval
from docket.interfaces.http import sweeps as _sweeps
from docket.interfaces.http.auth import authorize
from docket.interfaces.http.exchange import HttpExchange
from docket.interfaces.http.routes.health import SERVE_API_VERSION
from docket.interfaces.http.routes.table import ROUTES
from docket.interfaces.http.routing import find_route
from docket.interfaces.http.sweeps import (
    _SWEEP_LOCK,
    SWEEP_ABANDON_WAIT_S,
    _check_schedules,
    _drain_sweeps,
    _StopController,
)
from docket.interfaces.telegram.poll import _telegram_poll_loop
from docket.kernel import clock as _clock
from docket.kernel import threads as _threads
from docket.kernel.home import current_home
from docket.models import provider_lifecycle as _provider_lifecycle
from docket.observability import expire_old_traces, sweep_all
from docket.operator.notify import _flush_notify_channels
from docket.tasks.application import answers
from docket.tasks.application import queue as _queue
from docket.tasks.application import runs as _runs
from docket.tasks.application import sweep as _sweep

DEFAULT_PORT = _bootstrap.DEFAULT_PORT
DEFAULT_INTERVAL = _bootstrap.DEFAULT_INTERVAL


def render_health(dispatch_on: bool = False) -> str:
    """Render the /health body: status, API version and the dispatch block."""
    with _SWEEP_LOCK:
        inflight = sorted(_sweeps._sweep_inflight)
    body = {
        "status": "ok",
        "apiVersion": SERVE_API_VERSION,
        "dispatch": {
            "on": dispatch_on,
            "inflight": inflight,
            "stopping": _sweep_stop.is_set(),
            "workers": current_home().dispatch_sweep_workers,
        },
    }
    return json.dumps(body, separators=(",", ":")) + "\n"


_sweep_pool: tuple[int, concurrent.futures.ThreadPoolExecutor] | None = None
_sweep_stop = threading.Event()


def _sweep_one_pod(project: str) -> None:
    """One pod's sweep, on a pool worker: its own run record (source ``"sweep"``), then dispatch.

    An unset pod `approvalMode` resolves to "park" here (ADR 0016 SS2): a hop that would
    otherwise block on nobody for TOOL_APPROVAL_TIMEOUT parks instead of holding its worker."""

    try:
        record = _runs.create_run("sweep", project)
        with _SWEEP_LOCK:
            _sweeps._sweep_run_ids[project] = record["id"]
        _runs.execute(
            record["id"],
            lambda: _sweep.dispatch_pod(
                project,
                turn_timeout=current_home().dispatch_turn_timeout_s,
                verify_timeout=current_home().dispatch_verify_timeout_s,
                approval_default="park",
                resume=True,
                stop=_sweep_stop.is_set,
            ),
        )
    except Exception as exc:
        print(f"[serve] sweep: pod {project} failed: {exc}")
    finally:
        with _SWEEP_LOCK:
            _sweeps._sweep_inflight.pop(project, None)
            _sweeps._sweep_run_ids.pop(project, None)


def _submit_pod_sweep(project: str) -> bool:
    """Start a sweep of *project* on the bounded pool unless one is still in flight.

    The pool holds ``DISPATCH_SWEEP_WORKERS`` threads; a pod past that limit is claimed but
    waits for a free worker. Returns whether a sweep was started."""
    global _sweep_pool
    workers = max(1, current_home().dispatch_sweep_workers)
    stale = None
    with _SWEEP_LOCK:
        if project in _sweeps._sweep_inflight:
            return False
        if _sweep_pool is None or _sweep_pool[0] != workers:
            stale = _sweep_pool
            _sweep_pool = (
                workers,
                concurrent.futures.ThreadPoolExecutor(
                    max_workers=workers, thread_name_prefix="docket-sweep"
                ),
            )
        _sweeps._sweep_inflight[project] = _threads.submit(_sweep_pool[1], _sweep_one_pod, project)
    if stale is not None:
        stale[1].shutdown(wait=False)
    return True


def _abandon_sweeps(wait_s: float = SWEEP_ABANDON_WAIT_S) -> bool:
    """Request cancellation of every in-flight sweep run, drop queued sweeps, and wait up to
    *wait_s* for the running ones to settle; True when none remain."""

    with _SWEEP_LOCK:
        run_ids = list(_sweeps._sweep_run_ids.values())
        pool = _sweep_pool
    if pool is not None:
        pool[1].shutdown(wait=False, cancel_futures=True)
    for run_id in run_ids:
        with contextlib.suppress(Exception):
            _runs.cancel_run(run_id, source="serve")
    return _drain_sweeps(timeout=wait_s)


def _run_sweeps(dispatch: bool = False) -> None:
    """Run the periodic sweeps once, each best-effort and independently guarded so one failure
    never aborts the others or the server.

    Coerces stale-open traces to aborted, deletes terminated traces past TRACE_RETENTION_S, and
    expires pending approvals past APPROVAL_TIMEOUT. Retention is measured from when a session
    ENDED, not last active: an abandoned trace is terminated first and only then starts its
    retention clock, so it survives a full window after the sweep notices it -- the alternative
    would delete evidence of an abandoned session at the exact moment an operator would go
    looking for it. ``audit.log`` is never swept: telemetry is lossy by design, an audit log must
    not be.

    Also prunes terminal run records, resolved approval records and closed conversations past
    the same ``TRACE_RETENTION_S`` window -- live/pending/active records are never touched
    regardless of age, matching the trace sweep's own liveness rule.

    When *dispatch* is set (opt-in, real budget-gated agent turns, never part of the read-only
    monitor), also refreshes the limits each registered provider's ``/models`` publishes (once a
    day per provider; ``models.catalog.refresh_observed_models_due``) and drains every dispatchable pod's queue (one run record per pod, source
    ``"sweep"``) and checks due schedules. Each pod is swept on a pool worker (at most
    ``DISPATCH_SWEEP_WORKERS`` at once) and a pod whose previous sweep is still running is
    skipped, so this returns without waiting for the turns; ``_drain_sweeps`` waits."""

    with contextlib.suppress(Exception):
        sweep_all()
    with contextlib.suppress(Exception):
        expire_old_traces()
    with contextlib.suppress(Exception):
        approval.approval_sweep_expired()
    with contextlib.suppress(Exception):
        answers.sweep_expired_questions()
    with contextlib.suppress(Exception):
        _runs.prune_terminal()
    with contextlib.suppress(Exception):
        approval.prune_resolved()
    with contextlib.suppress(Exception):
        conversations.prune_closed_durable()
    if dispatch:
        with contextlib.suppress(Exception):
            _provider_lifecycle.refresh_observed_models_due()
        try:
            pods_to_dispatch = _queue.dispatchable_pods()
        except Exception as exc:
            print(f"[serve] sweep: could not list dispatchable pods: {exc}")
            pods_to_dispatch = []
        for project in pods_to_dispatch:
            _submit_pod_sweep(project)
        try:
            _check_schedules(_clock.epoch())
        except Exception as exc:
            print(f"[serve] sweep: schedule check failed: {exc}")

    with contextlib.suppress(Exception):
        _flush_notify_channels()


def _sweep_loop(interval: int, stop: threading.Event, dispatch: bool = False) -> None:
    """Run _run_sweeps every *interval* seconds until *stop* is set, then wait for in-flight sweeps."""
    while not stop.wait(interval):
        _run_sweeps(dispatch)
    _drain_sweeps()


class _DocketHandler(HttpExchange):
    """Dispatches a request through the route table; the handlers live in ``routes/``. The two
    hooks below are how a route reaches the state this module owns: the sweep pool and its stop
    flag."""

    def _submit_sweep(self, project: str) -> bool:
        return _submit_pod_sweep(project)

    def _render_health(self) -> str:
        return render_health(self.dispatch_on)

    def _route(self, method: str) -> bool:
        """Run the table row for *method* and this path; False when no row matches."""
        path = self.path.split("?", 1)[0].rstrip("/")
        found = find_route(ROUTES, method, path)
        if found is None:
            return False
        route, arg = found
        if route.auth and not authorize(self):
            return True
        route.handler(self, arg)
        return True

    def do_GET(self) -> None:
        if not self._route("GET"):
            self._send(b"not found\n", "text/plain", status=404)

    def do_POST(self) -> None:
        if not self._route("POST"):
            self._send_json_error("not found", 404)

    def do_HEAD(self) -> None:
        self.do_GET()


def _write_token_file(path: Path, token: str) -> None:
    """Write *token* to *path* with 0600 perms. Uses ``os.open`` with an
    explicit mode so the file is never briefly world-/group-readable between
    creation and a follow-up ``chmod``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(token + "\n")
    finally:
        with contextlib.suppress(OSError):
            os.chmod(path, 0o600)


def run_serve(
    port: int | None = None,
    *,
    bind: str = "127.0.0.1",
    interval: int = DEFAULT_INTERVAL,
    dispatch: bool = False,
    telegram: bool = False,
    token_file: str | None = None,
) -> None:
    """Start the docket HTTP server (blocking) — public CLI entry point.

    Binds to *bind* (default 127.0.0.1) on *port* (default 7331); runs sweeps once at startup and
    then every *interval* seconds in a daemon thread, until interrupted. ``telegram``, opt-in
    like ``dispatch``, starts docket's own Telegram long-poll loop in a daemon thread, degrading
    to an idle, periodically-retried wait rather than failing to start if no bot token is
    configured. ``token_file`` writes the bearer token to that path (0600) instead of stdout, for
    a context less private than a terminal (e.g. a systemd journal)."""
    plan = _bootstrap.build_server(
        current_home(),
        port=port,
        bind=bind,
        interval=interval,
        dispatch=dispatch,
        telegram=telegram,
        token_file=token_file,
    )
    actual_port = plan.port

    class _BoundHandler(_DocketHandler):
        serve_token = plan.token
        dispatch_on = plan.dispatch

    global _sweep_stop
    stop = _sweep_stop = threading.Event()
    server_ready = threading.Event()
    servers: list[_threads.ContextHTTPServer] = []

    def _shutdown_server() -> None:
        server_ready.wait()
        servers[0].shutdown()

    controller = _StopController(stop, _shutdown_server, _abandon_sweeps)
    previous = controller.install()
    _run_sweeps(dispatch)
    sweeper = _threads.start_thread(_sweep_loop, (interval, stop, dispatch))

    if telegram:
        _threads.start_thread(_telegram_poll_loop, (stop,))

    server = _threads.ContextHTTPServer((bind, actual_port), _BoundHandler)
    servers.append(server)
    server_ready.set()
    disp = "  dispatch=on" if dispatch else ""
    tg = "  telegram=on" if telegram else ""
    print(f"docket start  port={actual_port}  refresh={interval}s{disp}{tg}  (Ctrl-C to stop)")
    print(f"Endpoints at http://localhost:{actual_port}/")
    for route in ROUTES:
        print(f"  {route.method:<5} {route.shown}")
    loopback = bind in ("127.0.0.1", "localhost", "::1")
    bind_note = "loopback-only" if loopback else "WARNING: not loopback — reachable off this host"
    print(f"Bind: {bind}  ({bind_note})")
    if dispatch:
        unreached = plan.channels.unreached_warning()
        if unreached:
            print(f"WARNING: {unreached}")
    if token_file:
        token_path = Path(token_file)
        _write_token_file(token_path, plan.token)
        print(f"Approval API token written to {token_path} (0600)  (override: DOCKET_SERVE_TOKEN)")
    else:
        print(f"Approval API token: {plan.token}  (override: DOCKET_SERVE_TOKEN)")
    print("")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        while sweeper.is_alive() and not controller.abandon.is_set():
            sweeper.join(0.2)
        if controller.abandon.is_set():
            _abandon_sweeps()
            server.server_close()
            sys.stdout.flush()
            os._exit(controller.exit_code)
        server.server_close()
        _sweep_stop = threading.Event()
        for signum, handler in previous.items():
            signal.signal(signum, handler)
