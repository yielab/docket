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
import secrets
import signal
import sys
import threading
import urllib.parse as _urlparse
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any

from docket.governance import audit as _audit
from docket.interfaces.http.routes.health import (
    SERVE_API_VERSION,
    _with_token_budget,
    render_status,
)
from docket.interfaces.http.routes.metrics import render_metrics
from docket.interfaces.http.routes.traces import _traces_page
from docket.interfaces.telegram.poll import _telegram_poll_loop
from docket.kernel import clock as _clock
from docket.kernel import threads as _threads
from docket.kernel.home import current_home
from docket.operator import contract as _oc
from docket.operator.notify import _flush_notify_channels
from docket.tasks.domain import options as _task_options
from docket.teams import fleet
from docket.teams import provisioning as _prov

DEFAULT_PORT = 7331
DEFAULT_INTERVAL = 30

# The channels the HTTP transport itself may claim on POST /approvals/<token>.
# This is narrower than governance.approval.APPROVAL_CHANNELS: "cli", "mcp" and
# "telegram" belong to their own surfaces, and "timeout" is the fail-closed
# expiry path -- an HTTP Bearer holder must not be able to forge a decision
# as coming from any of those. "tack" is the one named HTTP client (Tack's
# board); "http" is the untagged default.
_HTTP_APPROVAL_CHANNELS: frozenset[str] = frozenset({"http", "tack"})


def render_health(dispatch_on: bool = False) -> str:
    """Render the /health body: status, API version and the dispatch block."""
    with _SWEEP_LOCK:
        inflight = sorted(_sweep_inflight)
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


_SWEEP_LOCK = threading.Lock()
_sweep_inflight: dict[str, concurrent.futures.Future[None]] = {}
_sweep_pool: tuple[int, concurrent.futures.ThreadPoolExecutor] | None = None
_sweep_run_ids: dict[str, str] = {}
_sweep_stop = threading.Event()
# How long a second stop signal waits for cancelled sweep runs to settle before exiting anyway.
SWEEP_ABANDON_WAIT_S = 5.0


def _check_schedules(now_ts: float) -> None:
    """Trigger dispatch for pods whose schedule spec is due (also recognizes a standard 5-field
    cron expression, not just ``@every``/``HH:MM`` -- see ``pipeline/application/schedule.py``). The last-run
    timestamp is read from, and written back into, ``Home.schedule_file`` itself rather than an
    in-memory dict, so a restart does not re-fire every schedule on its first sweep. Each due
    project's run record is created before its daemon-thread dispatch starts, so the sweep loop
    is never blocked and no outcome is silently discarded."""
    from docket.pipeline.application import schedule as _sched
    from docket.tasks.application import runs as _runs
    from docket.tasks.application import sweep as _sweep

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


def _sweep_one_pod(project: str) -> None:
    """One pod's sweep, on a pool worker: its own run record (source ``"sweep"``), then dispatch.

    An unset pod `approvalMode` resolves to "park" here (ADR 0016 SS2): a hop that would
    otherwise block on nobody for TOOL_APPROVAL_TIMEOUT parks instead of holding its worker."""
    from docket.tasks.application import runs as _runs
    from docket.tasks.application import sweep as _sweep

    try:
        record = _runs.create_run("sweep", project)
        with _SWEEP_LOCK:
            _sweep_run_ids[project] = record["id"]
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
            _sweep_inflight.pop(project, None)
            _sweep_run_ids.pop(project, None)


def _submit_pod_sweep(project: str) -> bool:
    """Start a sweep of *project* on the bounded pool unless one is still in flight.

    The pool holds ``DISPATCH_SWEEP_WORKERS`` threads; a pod past that limit is claimed but
    waits for a free worker. Returns whether a sweep was started."""
    global _sweep_pool
    workers = max(1, current_home().dispatch_sweep_workers)
    stale = None
    with _SWEEP_LOCK:
        if project in _sweep_inflight:
            return False
        if _sweep_pool is None or _sweep_pool[0] != workers:
            stale = _sweep_pool
            _sweep_pool = (
                workers,
                concurrent.futures.ThreadPoolExecutor(
                    max_workers=workers, thread_name_prefix="docket-sweep"
                ),
            )
        _sweep_inflight[project] = _threads.submit(_sweep_pool[1], _sweep_one_pod, project)
    if stale is not None:
        stale[1].shutdown(wait=False)
    return True


def _drain_sweeps(timeout: float | None = None) -> bool:
    """Wait for every in-flight pod sweep; True when none remain within *timeout*."""
    with _SWEEP_LOCK:
        pending = list(_sweep_inflight.values())
    _done, not_done = concurrent.futures.wait(pending, timeout=timeout)
    return not not_done


def _abandon_sweeps(wait_s: float = SWEEP_ABANDON_WAIT_S) -> bool:
    """Request cancellation of every in-flight sweep run, drop queued sweeps, and wait up to
    *wait_s* for the running ones to settle; True when none remain."""
    from docket.tasks.application import runs as _runs

    with _SWEEP_LOCK:
        run_ids = list(_sweep_run_ids.values())
        pool = _sweep_pool
    if pool is not None:
        pool[1].shutdown(wait=False, cancel_futures=True)
    for run_id in run_ids:
        with contextlib.suppress(Exception):
            _runs.cancel_run(run_id, source="serve")
    return _drain_sweeps(timeout=wait_s)


def _pending_sweeps() -> int:
    with _SWEEP_LOCK:
        return len(_sweep_inflight)


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

    from docket.agent import conversations
    from docket.governance import approval
    from docket.observability import trace
    from docket.tasks.application import answers
    from docket.tasks.application import runs as _runs

    with contextlib.suppress(Exception):
        trace.sweep_all()
    with contextlib.suppress(Exception):
        trace.expire_old_traces()
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
        from docket.models import catalog as _provider
        from docket.tasks.application import queue as _queue

        with contextlib.suppress(Exception):
            _provider.refresh_observed_models_due()
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


# Cap on a POST request body this server will read -- above it, `_read_body`
# sends 413 without touching `rfile`, so a caller cannot pin a handler thread
# by promising (and trickling) an unbounded body.
MAX_POST_BODY_BYTES = 1024 * 1024


# POST /tasks body name -> enqueue_task_once option, for the addressable-task fields.
_TASK_OPTION_FIELDS: tuple[tuple[str, str], ...] = (
    ("external_ref", "externalRef"),
    ("idempotency_key", "idempotencyKey"),
    ("base_ref", "baseRef"),
    ("pipeline", "pipeline"),
    ("gate", "gate"),
    ("max_tokens", "maxTokens"),
    ("prepare", "prepare"),
    ("restrictions", "restrictions"),
)


class _DocketHandler(BaseHTTPRequestHandler):
    """Serves the docket endpoints; builds responses on demand. ``serve_token``
    (a `run_serve` subclass attribute) empty means "disallow all auth" --
    never an accidental unauthenticated pass-through."""

    serve_token: str = ""
    dispatch_on: bool = False
    # Bounds every blocking socket read (request line, headers, body) so a
    # client that opens a connection and never finishes sending cannot pin a
    # handler thread forever.
    timeout = 30

    def log_message(self, fmt: str, *args: Any) -> None:
        return

    def _send(self, body: bytes, content_type: str, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _read_body(self) -> bytes | None:
        """Read a POST body up to `MAX_POST_BODY_BYTES`, sending `413` and
        returning `None` without touching `rfile` above the cap."""
        # An absent/zero Content-Length reads as `b"{}"`, matching every
        # caller's existing no-body behavior.
        try:
            length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            length = 0
        if length > MAX_POST_BODY_BYTES:
            self._send_json_error("Request body too large", 413)
            return None
        if length <= 0:
            return b"{}"
        return self.rfile.read(length)

    def _check_auth(self) -> bool:
        if not self.serve_token:
            return False
        auth = self.headers.get("Authorization", "")
        expected = f"Bearer {self.serve_token}"
        # Timing-safe compare — a plain `==` short-circuits on
        # the first mismatched byte, leaking token-length/prefix information
        # to an attacker who can measure response latency.
        return secrets.compare_digest(auth, expected)

    def _send_json(self, payload: dict[str, Any], status: int = 200) -> None:
        self._send(json.dumps(payload).encode(), "application/json", status)

    def _send_json_error(self, msg: str, status: int = 400) -> None:
        body = json.dumps({"ok": False, "error": msg}).encode()
        self._send(body, "application/json", status)

    def _reject_bad_project_id(self, project: str) -> bool:
        """Send a `400` and return `True` if *project* fails `validate_project_id` --
        every project-path-segment handler but `_handle_post_pods` (whose `400` comes
        from `provision_pod`'s own boundary check) calls this right after auth."""
        try:
            _prov.validate_project_id(project)
        except _prov.ProjectIdError as exc:
            self._send_json_error(str(exc), 400)
            return True
        return False

    def _send_pod_read(self, path: str) -> None:
        """``GET /pods`` and ``GET /pods/<p>`` (operator-api.spec.md "Pod answers")."""
        from docket.tasks.application import queue as _queue
        from docket.tasks.domain import task as _task
        from docket.teams import pod_settings as _pod_settings
        from docket.teams import report as _pod_report

        project = path[len("/pods/") :] if path.startswith("/pods/") else ""
        if path == "/pods":
            pods = [_pod_report.pod_summary(p) for p in _queue.dispatchable_pods()]
            self._send(json.dumps({"pods": pods}).encode("utf-8"), "application/json")
            return
        if self._reject_bad_project_id(project):
            return
        if project not in _queue.dispatchable_pods():
            self._send_json_error(f"Unknown pod: {project}", 404)
            return
        try:
            detail = _pod_report.pod_detail(project)
        except (_task.DispatchError, _pod_settings.PodSettingsError) as exc:
            self._send_json_error(str(exc), 500)
            return
        self._send(json.dumps(detail).encode("utf-8"), "application/json")

    def do_GET(self) -> None:
        full_path = self.path
        path = full_path.split("?", 1)[0].rstrip("/")
        if path == "/status.json":
            self._send(render_status().encode("utf-8"), "application/json")
        elif path == "/metrics":
            self._send((render_metrics() + "\n").encode("utf-8"), "text/plain; version=0.0.4")
        elif path == "/health":
            self._send(render_health(self.dispatch_on).encode("utf-8"), "application/json")
        elif path == "/approvals":
            if not self._check_auth():
                self._send_json_error("Unauthorized", 401)
                return
            from docket.governance import approval

            body = json.dumps({"pending": approval.list_pending()}).encode("utf-8")
            self._send(body, "application/json")
        elif path == "/inbox":
            if not self._check_auth():
                self._send_json_error("Unauthorized", 401)
                return
            from docket.operator import inbox as _inbox

            query = _urlparse.parse_qs(_urlparse.urlsplit(full_path).query)
            since_values = query.get("since")
            since = since_values[0] if since_values else None
            view = _inbox.build_inbox(now=_clock.stamp(), since=since)
            body = json.dumps(view.model_dump(by_alias=True, mode="json")).encode("utf-8")
            self._send(body, "application/json")
        elif path == "/runs":
            if not self._check_auth():
                self._send_json_error("Unauthorized", 401)
                return
            from docket.tasks.application import runs as _runs

            query = _urlparse.parse_qs(_urlparse.urlsplit(full_path).query)
            project_values = query.get("project")
            project = project_values[0] if project_values else None
            body = json.dumps({"runs": _runs.list_runs(project)}).encode("utf-8")
            self._send(body, "application/json")
        elif path.startswith("/runs/"):
            if not self._check_auth():
                self._send_json_error("Unauthorized", 401)
                return
            run_id = path[len("/runs/") :]
            if not run_id:
                self._send_json_error("Missing run id", 400)
                return
            from docket.tasks.application import runs as _runs

            rec = _runs.get_run(run_id)
            if rec is None:
                self._send_json_error(f"Unknown run: {run_id}", 404)
                return
            self._send(json.dumps(rec).encode("utf-8"), "application/json")
        elif path == "/tasks":
            # `path` already had trailing slashes stripped above, so both
            # bare "/tasks" and "/tasks/" (an empty project segment) land
            # here as "Missing project" rather than falling through to a
            # generic 404.
            if not self._check_auth():
                self._send_json_error("Unauthorized", 401)
                return
            self._send_json_error("Missing project", 400)
        elif path.startswith("/tasks/") and path.endswith("/diff"):
            self._send_task_diff(path[len("/tasks/") : -len("/diff")])
        elif path.startswith("/tasks/") and path.endswith("/evidence"):
            if not self._check_auth():
                self._send_json_error("Unauthorized", 401)
                return
            project, _, task_id = path[len("/tasks/") : -len("/evidence")].partition("/")
            if self._reject_bad_project_id(project):
                return
            from docket.tasks.application import evidence as _evidence

            try:
                doc = _evidence.task_evidence(project, task_id, "1.1.0")
            except _evidence.EvidenceNotFound as exc:
                self._send_json_error(str(exc), 404)
                return
            self._send(doc.model_dump_json(by_alias=True).encode("utf-8"), "application/json")
        elif path.startswith("/tasks/"):
            if not self._check_auth():
                self._send_json_error("Unauthorized", 401)
                return
            project, _, task_id = path[len("/tasks/") :].partition("/")
            if self._reject_bad_project_id(project):
                return
            from docket.tasks.application import queue as _queue

            if task_id:
                self._send_one_task(project, task_id)
                return
            query = _urlparse.parse_qs(_urlparse.urlsplit(full_path).query)
            tasks = self._filter_tasks(_queue.read_tasks(project), query)
            if tasks is None:
                return
            listed = [_with_token_budget(task) for task in tasks]
            self._send(json.dumps({"tasks": listed}).encode("utf-8"), "application/json")
        elif path.startswith("/pods/") and path.endswith("/corrections"):
            if not self._check_auth():
                self._send_json_error("Unauthorized", 401)
                return
            project = path[len("/pods/") : -len("/corrections")]
            if self._reject_bad_project_id(project):
                return
            from docket.tasks.application import corrections as _corrections
            from docket.tasks.application import queue as _queue

            if project not in _queue.dispatchable_pods():
                self._send_json_error(f"no pod '{project}'", 404)
                return
            query = _urlparse.parse_qs(_urlparse.urlsplit(full_path).query)
            since = (query.get("since") or [""])[0]
            if since:
                try:
                    since = _corrections.utc_cursor(since)
                except ValueError:
                    self._send_json_error("since must be an ISO-8601 timestamp with an offset", 400)
                    return
            records = _corrections.read(project, since)
            next_cursor = _corrections.utc_z(str(records[-1].get("ts", "")) if records else since)
            body = json.dumps({"corrections": records, "next": next_cursor}).encode("utf-8")
            self._send(body, "application/json")
        elif path == "/pods" or path.startswith("/pods/"):
            if not self._check_auth():
                self._send_json_error("Unauthorized", 401)
                return
            self._send_pod_read(path)
        elif path == "/traces":
            # Same rationale as the bare "/tasks" branch above.
            if not self._check_auth():
                self._send_json_error("Unauthorized", 401)
                return
            self._send_json_error("Missing project", 400)
        elif path.startswith("/traces/"):
            if not self._check_auth():
                self._send_json_error("Unauthorized", 401)
                return
            project = path[len("/traces/") :]
            if self._reject_bad_project_id(project):
                return
            query = _urlparse.parse_qs(_urlparse.urlsplit(full_path).query)
            since_values = query.get("since")
            since = since_values[0] if since_values else ""
            events, next_cursor = _traces_page(project, since)
            body = json.dumps({"events": events, "next": next_cursor}).encode("utf-8")
            self._send(body, "application/json")
        else:
            self._send(b"not found\n", "text/plain", status=404)

    def do_POST(self) -> None:
        path = self.path.split("?", 1)[0].rstrip("/")
        # A bare prefix (no trailing segment survives `rstrip("/")`) still
        # routes to its handler -- slicing the missing segment off yields ""
        # the same as an explicit empty one, so auth is checked before the
        # handler's own "Missing ..." `400`, instead of a `404` pre-auth.
        if path == "/approvals" or path.startswith("/approvals/"):
            self._handle_post_approvals(path)
        elif path == "/tasks" or path.startswith("/tasks/"):
            self._handle_post_tasks(path)
        elif path == "/dispatch" or path.startswith("/dispatch/"):
            self._handle_post_dispatch(path)
        elif path.startswith("/pods/") and path.endswith("/apply"):
            self._handle_post_pod_apply(path[len("/pods/") : -len("/apply")])
        elif path == "/pods":
            self._handle_post_pods()
        else:
            self._send_json_error("not found", 404)

    def _handle_post_approvals(self, path: str) -> None:
        if not self._check_auth():
            self._send_json_error("Unauthorized", 401)
            return
        approval_token = path[len("/approvals/") :]
        if not approval_token:
            self._send_json_error("Missing approval token", 400)
            return
        raw = self._read_body()
        if raw is None:
            return
        try:
            req_body: dict[str, object] = json.loads(raw)
        except (json.JSONDecodeError, RecursionError):
            self._send_json_error("Invalid JSON body", 400)
            return
        if not isinstance(req_body, dict):
            self._send_json_error("Invalid JSON body", 400)
            return
        action = str(req_body.get("action", ""))
        if action not in ("grant", "deny"):
            self._send_json_error('action must be "grant" or "deny"', 400)
            return
        from docket.governance import approval
        from docket.tasks.application import actions as _actions

        # `channel` identifies the surface this decision came through, tagged
        # onto the hash-chained audit log entry (`governance/approval.py`'s
        # `approval_grant`/`approval_deny`). Default stays "http" (every caller
        # before this field existed keeps identical behaviour). Validated
        # against `_HTTP_APPROVAL_CHANNELS`, not the full `approval.
        # APPROVAL_CHANNELS` -- the HTTP transport may not claim a channel
        # ("cli", "mcp", "telegram", "timeout") that belongs to another
        # surface or to the fail-closed expiry path.
        channel = req_body.get("channel", "http")
        if not isinstance(channel, str) or channel not in _HTTP_APPROVAL_CHANNELS:
            self._send_json_error(f"Unrecognised channel: {channel!r}", 400)
            return

        option = req_body.get("option", "")
        if (action != "grant" and option) or option not in ("", "approve_once", "approve_task"):
            self._send_json_error(
                'option must be "approve_once" or "approve_task" (grant only)', 400
            )
            return
        decision = "granted" if action == "grant" else "denied"
        reason = req_body.get("reason", "")
        if not isinstance(reason, str):
            reason = ""
        # Only pass actor when there's a reason to record
        actor = channel if reason else ""
        try:
            if action == "grant":
                if option == "approve_task":
                    approval.approval_set_option(approval_token, option)
                approval.approval_grant(approval_token, channel=channel, actor=actor, reason=reason)
            else:
                approval.approval_deny(approval_token, channel=channel, actor=actor, reason=reason)
            # If this token gated a dispatch task, genuinely resume
            # (grant) or kill (deny) it — see core/dispatch.py's
            # resolve_waiting_approval. A no-op for any other approval.
            _, note = _actions.resolve_waiting_approval_detail(
                approval_token, decision, channel=channel, actor=actor, reason=reason
            )
            rec = approval.approval_get(approval_token)
            payload: dict[str, object] = {
                "ok": True,
                "token": approval_token,
                "state": rec["state"],
            }
            if note:
                payload["note"] = note
            resp_body = json.dumps(payload).encode()
            self._send(resp_body, "application/json")
        except approval.ApprovalNoop as exc:
            _actions.resolve_waiting_approval(approval_token, decision)
            self._send_json_error(exc.message, 409)
        except approval.ApprovalConflict as exc:
            # The opposite decision already resolved this token (grant-after-deny or
            # deny-after-grant) -- a real conflict over an existing token, not a missing
            # one, so 409 naming the winning state rather than 404.
            self._send_json_error(str(exc), 409)
        except approval.ApprovalError as exc:
            self._send_json_error(str(exc), 404)

    def _send_one_task(self, project: str, task_id: str) -> None:
        from docket.tasks.application import queue as _queue

        for task in _queue.read_tasks(project):
            if task.get("id") == task_id:
                body = json.dumps(_with_token_budget(task))
                self._send(body.encode("utf-8"), "application/json")
                return
        self._send_json_error(f"no task '{task_id}' in pod '{project}'", 404)

    def _filter_tasks(
        self, tasks: list[dict[str, Any]], query: dict[str, list[str]]
    ) -> list[dict[str, Any]] | None:
        """Apply ``externalRef`` / ``status``; answers 400 and returns None on an unknown status."""
        status = query.get("status", [""])[0]
        if status and status not in _task_options.TASK_STATUSES:
            self._send_json_error(f"unknown task status '{status}'", 400)
            return None
        ref = query.get("externalRef", [""])[0]
        return [
            t
            for t in tasks
            if (not status or t.get("status") == status)
            and (not ref or t.get("externalRef") == ref)
        ]

    def _handle_post_tasks(self, path: str) -> None:
        if not self._check_auth():
            self._send_json_error("Unauthorized", 401)
            return
        rest = path[len("/tasks/") :]
        if rest.endswith("/answer"):
            self._handle_post_task_answer(rest[: -len("/answer")])
            return
        if rest.endswith("/pregrants"):
            self._handle_post_task_pregrant(rest[: -len("/pregrants")])
            return
        if rest.endswith("/cancel") or rest.endswith("/retry"):
            suffix = "/cancel" if rest.endswith("/cancel") else "/retry"
            project, _, task_id = rest[: -len(suffix)].partition("/")
            if self._reject_bad_project_id(project):
                return
            if suffix == "/cancel":
                self._handle_post_task_cancel(project, task_id)
            else:
                self._handle_post_task_retry(project, task_id)
            return
        project = rest
        if not project:
            self._send_json_error("Missing project", 400)
            return
        if self._reject_bad_project_id(project):
            return
        raw = self._read_body()
        if raw is None:
            return
        try:
            task_body: Any = json.loads(raw)
        except (json.JSONDecodeError, RecursionError):
            self._send_json_error("Invalid JSON body", 400)
            return
        if not isinstance(task_body, dict):
            self._send_json_error("Request body must be a JSON object", 400)
            return

        description = task_body.get("description", "")
        if not isinstance(description, str) or not description:
            self._send_json_error("description is required", 400)
            return
        priority_raw = task_body.get("priority", "normal")
        priority = str(priority_raw) if priority_raw else "normal"
        # `trusted` (optional) overrides the `pre_input` policy check's trust
        # flag for this enqueue only — see tasks.application.queue.enqueue_task_once. Absent
        # (None) leaves every existing caller's behaviour byte-for-byte
        # unchanged; this is the only place that field is threaded through.
        trusted_raw = task_body.get("trusted")
        trusted = bool(trusted_raw) if trusted_raw is not None else None

        from docket.tasks.application import queue as _queue
        from docket.tasks.domain import task as _task

        # `brief` (optional): a `TaskBrief` document, the HTTP counterpart of `docket pod
        # <p> delegate --brief`. Validated here regardless, so a malformed one is always
        # `422` before anything is enqueued.
        brief_raw = task_body.get("brief")
        brief: dict[str, Any] | None = None
        if brief_raw is not None:
            if not isinstance(brief_raw, dict):
                self._send_json_error("brief must be an object", 400)
                return
            from pydantic import ValidationError

            try:
                _oc.TaskBrief.model_validate(brief_raw)
            except ValidationError as exc:
                self._send_json_error(f"invalid brief: {exc}", 422)
                return
            brief = brief_raw

        options = {
            key: task_body.get(name) for key, name in _TASK_OPTION_FIELDS if name in task_body
        }
        try:
            task, created = _queue.enqueue_task_once(
                project,
                description,
                priority,
                channel="http",
                trusted=trusted,
                brief=brief,
                **options,
            )
        except _task.TaskRestrictionError as exc:
            self._send_json_error(str(exc), 422)
            return
        except _task.DispatchError as exc:
            msg = str(exc)
            # DispatchError here is: no pod (404), a wrongly shaped option or a `block`
            # pre_input verdict naming its policy id (400) -- never swallowed into 500.
            status = 404 if msg.startswith("no pod for") else 400
            self._send_json_error(msg, status)
            return

        task_resp: dict[str, Any] = {
            "ok": True,
            "created": created,
            "task": task["id"],
            "project": project,
            "status": task["status"],
        }
        # A `require_approval` pre_input verdict leaves the task itself
        # created but gated — surface its real status and token rather than
        # a 200 that implies it is queued to run (see enqueue_task_once, which
        # already sets both on the returned dict for this case).
        if task["status"] == "waiting_approval":
            task_resp["approvalToken"] = task.get("approvalToken", "")
        elif created and self.dispatch_on:
            _submit_pod_sweep(project)
        self._send(
            json.dumps(task_resp).encode(), "application/json", status=201 if created else 200
        )

    def _send_task_diff(self, rest: str) -> None:
        """`GET /tasks/<pod>/<id>/diff` (operator-api.spec.md "Task diff")."""
        if not self._check_auth():
            self._send_json_error("Unauthorized", 401)
            return
        project, _, task_id = rest.partition("/")
        if self._reject_bad_project_id(project):
            return
        from docket.tasks.application import lifecycle as _lifecycle
        from docket.tasks.domain import task as _task

        try:
            doc = _lifecycle.task_diff(project, task_id)
        except _task.TaskNotFoundError as exc:
            self._send_json_error(str(exc), 404)
            return
        except _task.DispatchError as exc:
            self._send_json({"ok": False, "error": str(exc), "reason": str(exc)}, 409)
            return
        self._send_json(doc)

    def _handle_post_task_cancel(self, project: str, task_id: str) -> None:
        """`POST /tasks/<pod>/<id>/cancel`; body optional `{"reason"?, "actor"?}`."""
        raw = self._read_body()
        if raw is None:
            return
        try:
            body: Any = json.loads(raw)
        except (json.JSONDecodeError, RecursionError):
            self._send_json_error("Invalid JSON body", 400)
            return
        if not isinstance(body, dict):
            self._send_json_error("Request body must be a JSON object", 400)
            return
        reason, actor = body.get("reason"), body.get("actor")
        from docket.tasks.application import lifecycle as _lifecycle
        from docket.tasks.domain import task as _task

        try:
            outcome = _lifecycle.cancel_task(
                project,
                task_id,
                channel="http",
                actor=actor if isinstance(actor, str) and actor else "http",
                reason=reason if isinstance(reason, str) else "",
            )
        except _task.TaskNotFoundError as exc:
            self._send_json_error(str(exc), 404)
            return
        if not outcome.cancelled:
            self._send_json_error(f"task {task_id} is {outcome.status}; nothing to cancel", 409)
            return
        self._send_json({"ok": True, "task": task_id, "status": outcome.status})

    def _handle_post_task_retry(self, project: str, task_id: str) -> None:
        """`POST /tasks/<pod>/<id>/retry`: a `blocked` or `failed` task flips to `pending`."""
        from docket.tasks.application import lifecycle as _lifecycle
        from docket.tasks.application import queue as _queue

        task = next((t for t in _queue.read_tasks(project) if t.get("id") == task_id), None)
        if task is None:
            self._send_json_error(f"task {task_id!r} not found in pod {project!r}", 404)
            return
        if not _lifecycle.retry_task(project, task_id):
            self._send_json_error(
                f"task {task_id} is {task.get('status')}; only failed or blocked tasks retry", 409
            )
            return
        self._send_json({"ok": True, "task": task_id, "status": "pending"})

    def _handle_post_task_answer(self, task_id: str) -> None:
        """`POST /tasks/<id>/answer` -- the HTTP counterpart of `docket task answer`.
        Body: `{"pod", "action", "content"?, "actor"?}`; `actor` is a label only, and the
        channel is always `"http"`."""
        if not task_id:
            self._send_json_error("Missing task id", 400)
            return
        raw = self._read_body()
        if raw is None:
            return
        try:
            body: Any = json.loads(raw)
        except (json.JSONDecodeError, RecursionError):
            self._send_json_error("Invalid JSON body", 400)
            return
        if not isinstance(body, dict):
            self._send_json_error("Request body must be a JSON object", 400)
            return

        project = body.get("pod")
        if not isinstance(project, str) or not project:
            self._send_json_error("pod is required", 400)
            return
        if self._reject_bad_project_id(project):
            return
        action = body.get("action")
        if not isinstance(action, str) or not action:
            self._send_json_error("action is required", 400)
            return
        content = body.get("content")
        if content is not None and not isinstance(content, dict):
            self._send_json_error("content must be an object", 400)
            return
        actor_raw = body.get("actor")
        actor = actor_raw if isinstance(actor_raw, str) and actor_raw else "http"

        from docket.tasks.application import answers as _answers
        from docket.tasks.application import queue as _queue

        try:
            _answers.answer_task(project, task_id, action, content, channel="http", actor=actor)
        except _answers.AnswerRejected as exc:
            self._send_json_error(f"blocked by policy '{exc.policy_id}'", 422)
            return
        except _answers.AnswerError as exc:
            msg = str(exc)
            if "not found in pod" in msg:
                self._send_json_error(msg, 404)
            elif "is not waiting_input" in msg or "is not parked at step" in msg:
                self._send_json_error(msg, 409)
            else:
                self._send_json_error(msg, 422)
            return

        task = next((t for t in _queue.read_tasks(project) if t.get("id") == task_id), None)
        if task is None:
            # Answered, then vanished from its own pod's queue before this read — not
            # expected in practice (nothing deletes a task), but report it honestly
            # rather than crash rendering a view for it.
            self._send_json_error(f"task {task_id!r} not found after answering", 500)
            return
        from docket.operator import inbox as _inbox

        view = _inbox.task_view(project, task).model_dump(by_alias=True, mode="json")
        self._send(json.dumps(view).encode(), "application/json")

    def _handle_post_task_pregrant(self, task_id: str) -> None:
        """`POST /tasks/<id>/pregrants` -- the HTTP counterpart of `docket task approve --for`.
        Body: `{"pod", "command", "tool"?, "actor"?}`; the channel is always `"http"`."""
        if not task_id:
            self._send_json_error("Missing task id", 400)
            return
        raw = self._read_body()
        if raw is None:
            return
        try:
            body: Any = json.loads(raw)
        except (json.JSONDecodeError, RecursionError):
            self._send_json_error("Invalid JSON body", 400)
            return
        if not isinstance(body, dict):
            self._send_json_error("Request body must be a JSON object", 400)
            return

        project = body.get("pod")
        if not isinstance(project, str) or not project:
            self._send_json_error("pod is required", 400)
            return
        if self._reject_bad_project_id(project):
            return
        command = body.get("command")
        if not isinstance(command, str) or not command.strip():
            self._send_json_error("command is required", 400)
            return
        tool_raw = body.get("tool")
        tool = tool_raw if isinstance(tool_raw, str) and tool_raw else "bash"
        actor_raw = body.get("actor")
        actor = actor_raw if isinstance(actor_raw, str) and actor_raw else "http"

        from docket.tasks.application import interruptions as _interruptions

        try:
            token = _interruptions.record_pregrant(
                project, task_id, command, tool=tool, channel="http", actor=actor
            )
        except _interruptions.InterruptionsError as exc:
            self._send_json_error(str(exc), 404)
            return

        resp = {"ok": True, "token": token, "task": task_id, "pod": project}
        self._send(json.dumps(resp).encode(), "application/json")

    def _handle_post_dispatch(self, path: str) -> None:
        if not self._check_auth():
            self._send_json_error("Unauthorized", 401)
            return
        project = path[len("/dispatch/") :]
        if not project:
            self._send_json_error("Missing project", 400)
            return
        if self._reject_bad_project_id(project):
            return
        from docket.pipeline.application import steps as _steps
        from docket.pipeline.domain import spec as _pipeline
        from docket.tasks.application import runs as _runs
        from docket.tasks.application import sweep as _sweep
        from docket.tasks.domain import task as _task

        # The request body (a plain {name: value} JSON object) is the
        # webhook's params — bound into the pod's effective pipeline's
        # declared `variables` namespace (pipeline.domain.spec.resolve_variables)
        # before anything is dispatched. A missing body (no Content-Length)
        # is the same as `{}`, so an omitted body still behaves as a
        # no-params dispatch.
        raw = self._read_body()
        if raw is None:
            return
        try:
            params: Any = json.loads(raw)
        except (json.JSONDecodeError, RecursionError):
            self._send_json_error("Invalid JSON body", 400)
            return
        if not isinstance(params, dict):
            self._send_json_error("Request body must be a JSON object", 400)
            return
        try:
            effective = _steps.effective_pipeline(project, None)
            variables = _pipeline.resolve_variables(effective, params)
        except _pipeline.VariableError as exc:
            self._send_json_error(str(exc), 400)
            return
        except _task.DispatchError as exc:
            msg = str(exc)
            self._send_json_error(msg, 404 if msg.startswith("no pod for") else 400)
            return

        # The run record is created — and its id handed back to
        # the caller — BEFORE any dispatch work is attempted. The actual
        # pipeline still runs async (this endpoint must not block on a real
        # agent turn), but its outcome always lands in the run registry
        # instead of vanishing behind a fire-and-forget thread.
        record = _runs.create_run("webhook", project, variables=variables)
        _audit.audit_log("run.dispatch", f"run={record['id']} project={project} channel=http")

        def _run(proj: str = project, run_id: str = record["id"]) -> None:
            _runs.execute(
                run_id,
                lambda: _sweep.dispatch_pod(
                    proj,
                    turn_timeout=current_home().dispatch_turn_timeout_s,
                    verify_timeout=current_home().dispatch_verify_timeout_s,
                    variables=variables,
                ),
            )

        _threads.start_thread(_run)
        resp_body = json.dumps(
            {"ok": True, "run": record["id"], "project": project, "status": "dispatched"}
        ).encode()
        self._send(resp_body, "application/json")

    def _handle_post_pod_apply(self, project: str) -> None:
        """``POST /pods/<p>/apply`` -- apply a directory on this machine to a pod, under the
        review rule of ADR 0024 section 6 (operator-api.spec.md)."""
        if not self._check_auth():
            self._send_json_error("Unauthorized", 401)
            return
        if self._reject_bad_project_id(project):
            return
        from dataclasses import asdict

        from docket.tasks.application import queue as _queue
        from docket.teams import pod as _pod_core
        from docket.teams.apply import model as _model
        from docket.teams.apply import plan as _pod_apply
        from docket.teams.apply import review as _review

        if project not in _queue.dispatchable_pods():
            self._send_json_error(f"Unknown pod: {project}", 404)
            return
        raw = self._read_body()
        if raw is None:
            return
        try:
            body: Any = json.loads(raw or b"{}")
        except (json.JSONDecodeError, RecursionError):
            self._send_json_error("Invalid JSON body", 400)
            return
        if not isinstance(body, dict):
            self._send_json_error("Request body must be a JSON object", 400)
            return
        codebase = fleet.meta_get(_pod_core.member_id(project, "lead"), "codebase", "")
        if not codebase:
            self._send_json_error(
                f"pod {project} has no recorded codebase; docket pod update reviews a "
                "directory against the repository the pod was made from",
                400,
            )
            return
        directory_value = body.get("directory")
        dry_run, accept = body.get("dryRun", False), body.get("accept")
        if directory_value is not None and not isinstance(directory_value, str):
            self._send_json_error("directory must be a string", 400)
            return
        if not isinstance(dry_run, bool) or not (accept is None or isinstance(accept, str)):
            self._send_json_error("dryRun must be a boolean and accept a string", 400)
            return
        if directory_value is None:
            directory_value = str(_review.repo_config_dir(Path(codebase), project))
        elif not Path(directory_value).is_absolute():
            self._send_json_error("directory must be an absolute path", 400)
            return
        directory = Path(directory_value)
        if not directory_value or not directory.is_dir():
            self._send_json_error(f"directory not found: {directory_value}", 400)
            return
        try:
            outcome = _pod_apply.apply_directory(
                project, directory, Path(codebase), accept=accept, dry_run=dry_run, channel="http"
            )
        except _model.PodApplyError as exc:
            self._send_json_error(str(exc), 400)
            return
        if outcome.status == "refused":
            names = ", ".join(outcome.refused)
            self._send_json_error(f"allowCommands names refused commands: {names}", 409)
        elif outcome.status in ("needs_code", "code_mismatch"):
            payload: dict[str, Any] = {"ok": False}
            if outcome.status == "needs_code":
                payload["error"] = "this directory runs commands on this machine; pass accept"
                payload["reviewCode"] = outcome.code
            else:
                payload["error"] = "the directory changed what runs on this machine since that code"
            payload["runs"] = [asdict(i) for i in outcome.runs]
            self._send_json(payload, 409)
        else:
            self._send_json(
                {
                    "ok": True,
                    "project": project,
                    "items": [asdict(i) for i in outcome.items],
                    "dryRun": outcome.status == "planned",
                }
            )

    def _handle_post_pods(self) -> None:
        """``POST /pods`` — provision a fresh pod from a blueprint. Body,
        response shape, and the not-a-thin-wrapper/no-drift rationale:
        specs/data/serve-read-api.spec.md (POST /pods)."""
        if not self._check_auth():
            self._send_json_error("Unauthorized", 401)
            return
        raw = self._read_body()
        if raw is None:
            return
        try:
            body: Any = json.loads(raw)
        except (json.JSONDecodeError, RecursionError):
            self._send_json_error("Invalid JSON body", 400)
            return
        if not isinstance(body, dict):
            self._send_json_error("Request body must be a JSON object", 400)
            return

        project = body.get("name")
        if not isinstance(project, str) or not project:
            self._send_json_error("name is required", 400)
            return

        from docket.teams import blueprints as _bp

        blueprint_name = body.get("blueprint", _bp.DEFAULT_BLUEPRINT)
        if not isinstance(blueprint_name, str) or not blueprint_name:
            self._send_json_error("blueprint must be a non-empty string", 400)
            return

        path_value = body.get("location", "")
        if not isinstance(path_value, str):
            self._send_json_error("location must be a string", 400)
            return

        # `pod` mirrors `docket init --pod full` — the CLI's only roster
        # override, itself restricted to the `software` blueprint (a
        # non-`software` blueprint provisions its own fixed roster; the CLI
        # warns and ignores rather than erroring, and there is no HTTP
        # surface to print that warning to, so this route just ignores it
        # the same way).
        pod_field = body.get("pod")
        roles: tuple[str, ...] | None = None
        if pod_field is not None:
            if not isinstance(pod_field, str) or pod_field.lower() != "full":
                self._send_json_error('pod must be "full" if given', 400)
                return
            if blueprint_name == "software":
                from docket.teams.pod import FULL_POD_ROLES

                roles = FULL_POD_ROLES

        budget_raw = body.get("budget")
        budget_usd: float | None = None
        if budget_raw is not None:
            if isinstance(budget_raw, bool) or not isinstance(budget_raw, (int, float, str)):
                self._send_json_error("budget must be a number", 400)
                return
            try:
                budget_val = float(budget_raw)
            except (TypeError, ValueError):
                self._send_json_error("budget must be numeric", 400)
                return
            budget_usd = budget_val if budget_val > 0 else None

        verify_cmd = body.get("verifyCmd", "")
        if not isinstance(verify_cmd, str):
            self._send_json_error("verifyCmd must be a string", 400)
            return

        ensure = body.get("ensure", False)
        if not isinstance(ensure, bool):
            self._send_json_error("ensure must be a boolean", 400)
            return

        from docket.teams import pod_provisioning as _pp

        try:
            result = _pp.provision_pod(
                project,
                blueprint_name,
                location=path_value,
                roles=roles,
                budget_usd=budget_usd,
                verify_cmd=verify_cmd,
                source="http",
            )
        except _bp.BlueprintError as exc:
            self._send_json_error(str(exc), 400)
            return
        except _pp.VerifyCmdError as exc:
            self._send_json_error(str(exc), 400)
            return
        except _prov.ProjectIdError as exc:
            self._send_json_error(str(exc), 400)
            return
        except _pp.PodAlreadyExistsError:
            if ensure:
                self._send(
                    json.dumps({"ok": True, "created": False, "project": project}).encode(),
                    "application/json",
                )
                return
            self._send_json_error(f"'{project}' already exists", 409)
            return
        except _pp.PodProvisionError as exc:
            # Rollback has already run (see provision_pod's docstring) --
            # nothing from this attempt survives on disk or in the fleet
            # registry. Not a 4xx: the request itself was well-formed, the
            # failure is an operational one (e.g. disk/filesystem trouble).
            self._send_json_error(str(exc), 500)
            return

        resp_body = json.dumps(
            {
                "ok": True,
                "created": True,
                "project": result.project,
                "blueprint": result.blueprint,
                "members": [
                    {"id": m.member_id, "role": m.role, "model": m.model} for m in result.members
                ],
            }
        ).encode()
        self._send(resp_body, "application/json", status=201)

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
    actual_port = DEFAULT_PORT if port is None else port

    _token = os.environ.get("DOCKET_SERVE_TOKEN") or secrets.token_urlsafe(32)

    class _BoundHandler(_DocketHandler):
        serve_token = _token
        dispatch_on = dispatch

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
    print(
        f"Endpoints: /status.json  /metrics  /health  /approvals  /runs  /dispatch"
        f"  ->  http://localhost:{actual_port}/"
    )
    loopback = bind in ("127.0.0.1", "localhost", "::1")
    bind_note = "loopback-only" if loopback else "WARNING: not loopback — reachable off this host"
    print(f"Bind: {bind}  ({bind_note})")
    if dispatch:
        from docket.operator import channel as _channel

        unreached = _channel.unreached_warning(_channel.load_catalog().delivering())
        if unreached:
            print(f"WARNING: {unreached}")
    if token_file:
        token_path = Path(token_file)
        _write_token_file(token_path, _token)
        print(f"Approval API token written to {token_path} (0600)  (override: DOCKET_SERVE_TOKEN)")
    else:
        print(f"Approval API token: {_token}  (override: DOCKET_SERVE_TOKEN)")
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
