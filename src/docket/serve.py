"""Command: serve — local HTTP endpoints for dashboards / monitoring.

Exposes:
  /status.json         full snapshot (agents, bindings, costs)
  /metrics             Prometheus-format metrics (no external dependency)
  /health              liveness JSON
  /approvals           list pending approvals (auth required)
  /approvals/<token>   grant or deny a pending approval (auth required)
  /runs                 list dispatch run records, newest first (auth required)
  /runs/<id>            one dispatch run record (auth required)
  /dispatch/<project>   trigger a pod dispatch; returns a queryable run id (auth required)

Security model: the server binds to 127.0.0.1 (loopback-only) by default —
`run_serve`'s ``bind`` parameter can widen that, but nothing in docket
recommends or automates doing so; treat any non-loopback bind as an explicit,
on-you decision (there is no additional network ACL here, only the bearer
token below). A randomly-generated Bearer token is required on every
/approvals, /runs and /dispatch request (DOCKET_SERVE_TOKEN env var pins a fixed
token); it is printed at startup by default, or written to a 0600 file via
``--token-file``/``token_file=`` when stdout isn't a safe place for it (e.g. a
systemd unit's journal). The approval endpoints reject all requests without a
valid token — compared with `secrets.compare_digest` (Phase 18 G-6), not
`==`, before touching approval state.

R-3 (D-17): every dispatch this server triggers — webhook, due schedule, or the
periodic sweep — is recorded in the ``core.runs`` registry *before* it starts
and folded to a terminal state when it finishes, so an operator can always
distinguish "done", "failed", and "never ran" via ``docket runs show`` /
``GET /runs/<id>``. No dispatch call site in this module silently discards an
exception any more (no bare ``contextlib.suppress(Exception)`` around
dispatch) — see ``core/runs.py``'s ``execute()``.

G-1: ``POST /approvals/<token>`` genuinely resumes or kills a pod-dispatch task the
require_approval gate stopped, not just the approval record's own state — see
``core/dispatch.py``'s ``resolve_waiting_approval`` (a no-op for any other approval).

W-4: ``POST /dispatch/<project>``'s JSON body — a plain ``{name: value}`` object,
``{}`` if the body is omitted — is resolved against the pod's effective pipeline's
declared ``variables`` (``core.pipeline.resolve_variables``) before the run record
is even created; a missing *required* variable is rejected with 400 and never
reaches the run registry. The resolved namespace is persisted on the run record
itself (``variables``), so ``docket runs show <id>``/``GET /runs/<id>`` can answer
"what params did this dispatch actually see". Due-schedule dispatch (``_check_schedules``)
now also recognizes a standard 5-field cron expression, not just ``@every``/``HH:MM``
— see ``core/schedule.py``.
"""

from __future__ import annotations

import contextlib
import datetime as _dt
import json
import os
import secrets
import threading
import urllib.parse as _urlparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import docket.config as cfg
from docket.core import fleet as oc
from docket.core import utils

DEFAULT_PORT = 7331
DEFAULT_INTERVAL = 30

# Bumped on any breaking change to /status.json or /metrics contract, or to the
# authenticated write/read-registry endpoints (/dispatch, /runs).
# Pinned by tests/python/test_cd8_read_api.py (TestApiContract).
SERVE_API_VERSION = "2"

_SPECIALISTS = tuple(cfg.ORG_DISPLAY_ORDER)


def _utc_timestamp() -> str:
    """Return current UTC time as 'YYYY-MM-DDTHH:MM:SSZ' (matches `date -u`)."""
    return _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _last_activity_or_never(agent_id: str) -> str:
    """Like utils.last_activity but returns 'never' (cmd_snapshot's sentinel)."""
    val = utils.last_activity(agent_id)
    return "never" if val == "—" else val


def _agent_record(agent_id: str, *, kind: str, registered: set[str]) -> dict[str, Any]:
    from docket.edges import store

    meta_path = cfg.meta_path(agent_id)
    meta: dict[str, Any] = store.read_json(meta_path) if meta_path.exists() else {}
    cost = round(utils.aggregate_cost(agent_id).cost_usd, 6)
    default_scope = "project" if kind == "project" else "org"
    budget_raw = meta.get("budgetUsd")
    budget: float | None = (
        float(budget_raw) if budget_raw and str(budget_raw) not in ("", "0") else None
    )
    return {
        "id": agent_id,
        "name": str(meta.get("name", agent_id)),
        "kind": kind,
        "scope": str(meta.get("scope", default_scope)),
        "model": str(meta.get("model", "")),
        "registered": agent_id in registered,
        "bindings": oc.agent_bindings(agent_id),
        "lastActivity": _last_activity_or_never(agent_id),
        "costUsd": cost,
        "budgetUsd": budget,
    }


def build_status() -> dict[str, Any]:
    """Build the /status.json payload.

    Shape (v1)::

        {apiVersion, timestamp, gateway, channels, agents:[...], totalCostUsd}

    ``gateway`` is ``"active"`` or ``"inactive"``; each agent carries
    {id,name,kind,scope,model,registered,bindings,lastActivity,costUsd,budgetUsd}.
    Contract is versioned by ``SERVE_API_VERSION`` and pinned in
    ``specs/data/serve-read-api.spec.md``.
    """
    gateway = "active" if utils.gateway_active() else "inactive"
    channels = oc.channel_names()
    registered = {a.id for a in oc.list_agents()}

    agents: list[dict[str, Any]] = []
    total_cost = 0.0

    for pid in utils.project_ids():
        rec = _agent_record(pid, kind="project", registered=registered)
        total_cost += float(rec["costUsd"])
        agents.append(rec)

    for spec in _SPECIALISTS:
        spec_dir = cfg.WORKSPACES_DIR / spec
        if not spec_dir.is_dir():
            continue
        rec = _agent_record(spec, kind="specialist", registered=registered)
        total_cost += float(rec["costUsd"])
        agents.append(rec)

    return {
        "apiVersion": SERVE_API_VERSION,
        "timestamp": _utc_timestamp(),
        "gateway": gateway,
        "channels": channels,
        "agents": agents,
        "totalCostUsd": round(total_cost, 6),
    }


def _cost_json() -> dict[str, Any]:
    """Per-project cost payload.

    Returns {agents:[{id,model,costUsd,turns,...}], totalUsd}. Metrics only
    cover project agents (specialists are excluded).
    """
    from docket.edges import store

    agents: list[dict[str, Any]] = []
    total = 0.0
    for pid in utils.project_ids():
        raw = store.read_json(cfg.meta_path(pid))
        model = str(raw.get("model", cfg.DEFAULT_MODEL))
        budget_raw = raw.get("budgetUsd")
        totals = utils.aggregate_cost(pid)
        cost = totals.cost_usd
        total += cost
        budget_val = float(budget_raw) if budget_raw and str(budget_raw) not in ("", "0") else None
        agents.append(
            {
                "id": pid,
                "model": model,
                "input": totals.input_tokens,
                "output": totals.output_tokens,
                "costUsd": round(cost, 6),
                "pricingKnown": True,
                "turns": totals.turns,
                "budgetUsd": budget_val,
            }
        )
    return {"agents": agents, "totalUsd": round(total, 6)}


def _esc(s: Any) -> str:
    """Strip backslashes and double-quotes from a label value."""
    return str(s).replace("\\", "").replace('"', "")


def render_metrics() -> str:
    """Render Prometheus-format metrics.

    No trailing newline; callers append it.
    """
    d = _cost_json()
    gw = "1" if utils.gateway_active() else "0"

    lines: list[str] = [
        "# HELP docket_agents_total Number of project agents",
        "# TYPE docket_agents_total gauge",
        "docket_agents_total " + str(len(d.get("agents", []))),
        "# HELP docket_agent_cost_usd Cumulative cost per agent (USD)",
        "# TYPE docket_agent_cost_usd gauge",
    ]
    for a in d.get("agents", []):
        lab = 'agent="' + _esc(a.get("id", "")) + '",model="' + _esc(a.get("model", "")) + '"'
        lines.append("docket_agent_cost_usd{" + lab + "} " + str(a.get("costUsd", 0)))
        lines.append(
            'docket_agent_turns_total{agent="'
            + _esc(a.get("id", ""))
            + '"} '
            + str(a.get("turns", 0))
        )
    from docket.core import approval as _approval

    pending = len(_approval.list_pending())
    lines += [
        "# HELP docket_cost_usd_total Total cost across all agents (USD)",
        "# TYPE docket_cost_usd_total gauge",
        "docket_cost_usd_total " + str(d.get("totalUsd", 0)),
        "# HELP docket_gateway_up Gateway service active (1) or not (0)",
        "# TYPE docket_gateway_up gauge",
        "docket_gateway_up " + gw,
        "# HELP docket_approvals_pending_total Pending approvals awaiting a human decision",
        "# TYPE docket_approvals_pending_total gauge",
        "docket_approvals_pending_total " + str(pending),
    ]
    return "\n".join(lines)


def render_health() -> str:
    """Render the /health body.

    Format: ``{"status":"ok","gateway":N}\\n`` where N is 1 or 0.
    """
    gw = 1 if utils.gateway_active() else 0
    return f'{{"status":"ok","gateway":{gw}}}\n'


def render_status() -> str:
    """Render the /status.json body (indent=2, matching cmd_snapshot)."""
    return json.dumps(build_status(), indent=2)


def _check_schedules(now_ts: float) -> None:
    """Trigger dispatch for pods whose schedule spec is due.

    Reads the schedule config from ``cfg.SCHEDULE_FILE``; the last-run
    timestamp used to decide "due" is read from — and, once a project fires,
    written back into — that same file (``core.schedule.load_last_run`` /
    ``record_last_run``) rather than an in-memory dict, so a ``docket serve``
    restart does not re-fire every schedule on its first sweep (R-3).

    Each due project gets a run record (source ``"schedule"``) created up
    front, then is dispatched in a daemon thread via ``core.runs.execute`` so
    the sweep loop is never blocked by an agent run — and so the outcome
    (including an exception) always lands in the run registry instead of
    being silently discarded.
    """
    from docket.core import dispatch as _dispatch
    from docket.core import runs as _runs
    from docket.core import schedule as _sched

    schedules = _sched.load_schedules(cfg.SCHEDULE_FILE)
    last_run_map = _sched.load_last_run(cfg.SCHEDULE_FILE)
    for project, spec in schedules.items():
        last_run = last_run_map.get(project, 0.0)
        if not _sched.is_schedule_due(spec, last_run, now_ts):
            continue
        _sched.record_last_run(cfg.SCHEDULE_FILE, project, now_ts)

        record = _runs.create_run("schedule", project)

        def _run(proj: str = project, run_id: str = record["id"]) -> None:
            # R-2's process-wide timeout knobs (unset = no override) run inside
            # R-3's run record, so a scheduled dispatch is both configurable and
            # observable rather than fire-and-forget.
            _runs.execute(
                run_id,
                lambda: _dispatch.dispatch_pod(
                    proj,
                    turn_timeout=cfg.DISPATCH_TURN_TIMEOUT_S,
                    verify_timeout=cfg.DISPATCH_VERIFY_TIMEOUT_S,
                ),
            )

        t = threading.Thread(target=_run, daemon=True)
        t.start()


def _run_sweeps(dispatch: bool = False) -> None:
    """Run the periodic sweeps once, each best-effort.

    Coerces stale open traces to aborted and expires pending approvals past
    APPROVAL_TIMEOUT. Every sweep is guarded so one failure never aborts the
    others or the server.

    When *dispatch* is set, also drives every dispatchable pod's queued tasks
    through its pipeline (one run record per pod, source ``"sweep"``) and
    checks the schedule file for due projects. These run real, budget-gated
    agent turns so they are opt-in (`docket serve --dispatch`) and never part
    of the read-only monitor.
    """
    import time

    from docket.core import approval, trace

    with contextlib.suppress(Exception):
        trace.sweep_all()
    with contextlib.suppress(Exception):
        approval.approval_sweep_expired()
    if dispatch:
        from docket.core import dispatch as _dispatch
        from docket.core import runs as _runs

        try:
            pods_to_dispatch = _dispatch.dispatchable_pods()
        except Exception as exc:
            print(f"[serve] sweep: could not list dispatchable pods: {exc}")
            pods_to_dispatch = []
        for project in pods_to_dispatch:
            record = _runs.create_run("sweep", project)

            def _dispatch_one(proj: str = project) -> list[_dispatch.TaskResult]:
                # R-2 timeout knobs inside R-3's per-pod run record.
                return _dispatch.dispatch_pod(
                    proj,
                    turn_timeout=cfg.DISPATCH_TURN_TIMEOUT_S,
                    verify_timeout=cfg.DISPATCH_VERIFY_TIMEOUT_S,
                )

            _runs.execute(record["id"], _dispatch_one)
        try:
            _check_schedules(time.time())
        except Exception as exc:
            print(f"[serve] sweep: schedule check failed: {exc}")


def _sweep_loop(interval: int, stop: threading.Event, dispatch: bool = False) -> None:
    """Run _run_sweeps every *interval* seconds until *stop* is set."""
    while not stop.wait(interval):
        _run_sweeps(dispatch)


class _DocketHandler(BaseHTTPRequestHandler):
    """Serves the docket endpoints; builds responses on demand.

    ``serve_token`` is set per-server via a subclass created in ``run_serve``.
    An empty token disallows all auth so the base class can never accidentally
    pass an unauthenticated request through.
    """

    serve_token: str = ""

    def log_message(self, fmt: str, *args: Any) -> None:
        return

    def _send(self, body: bytes, content_type: str, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _check_auth(self) -> bool:
        if not self.serve_token:
            return False
        auth = self.headers.get("Authorization", "")
        expected = f"Bearer {self.serve_token}"
        # Timing-safe compare (Phase 18 G-6) — a plain `==` short-circuits on
        # the first mismatched byte, leaking token-length/prefix information
        # to an attacker who can measure response latency.
        return secrets.compare_digest(auth, expected)

    def _send_json_error(self, msg: str, status: int = 400) -> None:
        body = json.dumps({"ok": False, "error": msg}).encode()
        self._send(body, "application/json", status)

    def do_GET(self) -> None:
        full_path = self.path
        path = full_path.split("?", 1)[0].rstrip("/")
        if path in ("/status.json", "/status"):
            self._send(render_status().encode("utf-8"), "application/json")
        elif path == "/metrics":
            self._send((render_metrics() + "\n").encode("utf-8"), "text/plain; version=0.0.4")
        elif path == "/health":
            self._send(render_health().encode("utf-8"), "application/json")
        elif path == "/approvals":
            if not self._check_auth():
                self._send_json_error("Unauthorized", 401)
                return
            from docket.core import approval

            body = json.dumps({"pending": approval.list_pending()}).encode("utf-8")
            self._send(body, "application/json")
        elif path == "/runs":
            if not self._check_auth():
                self._send_json_error("Unauthorized", 401)
                return
            from docket.core import runs as _runs

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
            from docket.core import runs as _runs

            rec = _runs.get_run(run_id)
            if rec is None:
                self._send_json_error(f"Unknown run: {run_id}", 404)
                return
            self._send(json.dumps(rec).encode("utf-8"), "application/json")
        else:
            self._send(b"not found\n", "text/plain", status=404)

    def do_POST(self) -> None:
        path = self.path.split("?", 1)[0].rstrip("/")
        if path.startswith("/approvals/"):
            if not self._check_auth():
                self._send_json_error("Unauthorized", 401)
                return
            approval_token = path[len("/approvals/") :]
            if not approval_token:
                self._send_json_error("Missing approval token", 400)
                return
            try:
                length = int(self.headers.get("Content-Length", 0))
                raw = self.rfile.read(length) if length > 0 else b"{}"
                req_body: dict[str, object] = json.loads(raw)
            except (ValueError, json.JSONDecodeError):
                self._send_json_error("Invalid JSON body", 400)
                return
            action = str(req_body.get("action", ""))
            if action not in ("grant", "deny"):
                self._send_json_error('action must be "grant" or "deny"', 400)
                return
            from docket.core import approval
            from docket.core import dispatch as _dispatch

            decision = "granted" if action == "grant" else "denied"
            try:
                if action == "grant":
                    approval.approval_grant(approval_token, channel="http")
                else:
                    approval.approval_deny(approval_token, channel="http")
                # G-1: if this token gated a dispatch task, genuinely resume
                # (grant) or kill (deny) it — see core/dispatch.py's
                # resolve_waiting_approval. A no-op for any other approval.
                _dispatch.resolve_waiting_approval(approval_token, decision)
                rec = approval.approval_get(approval_token)
                resp_body = json.dumps(
                    {"ok": True, "token": approval_token, "state": rec["state"]}
                ).encode()
                self._send(resp_body, "application/json")
            except approval.ApprovalNoop as exc:
                _dispatch.resolve_waiting_approval(approval_token, decision)
                self._send_json_error(exc.message, 409)
            except approval.ApprovalError as exc:
                self._send_json_error(str(exc), 404)
        elif path.startswith("/dispatch/"):
            if not self._check_auth():
                self._send_json_error("Unauthorized", 401)
                return
            project = path[len("/dispatch/") :]
            if not project:
                self._send_json_error("Missing project", 400)
                return
            from docket.core import dispatch as _dispatch
            from docket.core import pipeline as _pipeline
            from docket.core import runs as _runs

            # W-4: the request body (a plain {name: value} JSON object) is the
            # webhook's params — bound into the pod's effective pipeline's
            # declared `variables` namespace (core.pipeline.resolve_variables)
            # before anything is dispatched. A missing body (no Content-Length)
            # is the same as `{}`, matching the pre-W-4 no-params behavior
            # exactly.
            try:
                length = int(self.headers.get("Content-Length", 0))
                raw = self.rfile.read(length) if length > 0 else b"{}"
                params: Any = json.loads(raw)
            except (ValueError, json.JSONDecodeError):
                self._send_json_error("Invalid JSON body", 400)
                return
            if not isinstance(params, dict):
                self._send_json_error("Request body must be a JSON object", 400)
                return
            try:
                effective = _dispatch.effective_pipeline(project, None)
                variables = _pipeline.resolve_variables(effective, params)
            except _pipeline.VariableError as exc:
                self._send_json_error(str(exc), 400)
                return

            # R-3 (D-17): the run record is created — and its id handed back to
            # the caller — BEFORE any dispatch work is attempted. The actual
            # pipeline still runs async (this endpoint must not block on a real
            # agent turn), but its outcome always lands in the run registry
            # instead of vanishing behind a fire-and-forget thread.
            record = _runs.create_run("webhook", project, variables=variables)

            def _run(proj: str = project, run_id: str = record["id"]) -> None:
                _runs.execute(
                    run_id,
                    lambda: _dispatch.dispatch_pod(
                        proj,
                        turn_timeout=cfg.DISPATCH_TURN_TIMEOUT_S,
                        verify_timeout=cfg.DISPATCH_VERIFY_TIMEOUT_S,
                    ),
                )

            threading.Thread(target=_run, daemon=True).start()
            resp_body = json.dumps(
                {"ok": True, "run": record["id"], "project": project, "status": "dispatched"}
            ).encode()
            self._send(resp_body, "application/json")
        else:
            self._send_json_error("not found", 404)

    def do_HEAD(self) -> None:
        self.do_GET()


def _write_token_file(path: Path, token: str) -> None:
    """Write *token* to *path* with 0600 perms (create or replace, owner-only).

    Uses ``os.open`` with an explicit mode so the file is never briefly
    world-/group-readable between creation and a follow-up ``chmod``.
    """
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
    token_file: str | None = None,
) -> None:
    """Start the docket HTTP server (blocking) — public CLI entry point.

    Binds to *bind* (default ``127.0.0.1`` — loopback-only; not reachable off
    this host unless the caller explicitly widens it, which docket neither
    recommends nor automates) on the given port (default 7331) and serves
    /status.json, /metrics, /health. Responses are built on each request
    (cheap, index-backed). Runs sweeps once at startup and then every
    *interval* seconds in a daemon thread. Runs until interrupted.

    ``token_file``, when given, writes the bearer token required by
    /approvals and /dispatch to that path (0600 perms) instead of printing it
    to stdout (Phase 18 G-6) — use this when stdout may land somewhere less
    private than a terminal, e.g. a systemd unit's journal.
    """
    actual_port = DEFAULT_PORT if port is None else port

    _token = os.environ.get("DOCKET_SERVE_TOKEN") or secrets.token_urlsafe(32)

    class _BoundHandler(_DocketHandler):
        serve_token = _token

    _run_sweeps(dispatch)
    stop = threading.Event()
    sweeper = threading.Thread(target=_sweep_loop, args=(interval, stop, dispatch), daemon=True)
    sweeper.start()

    server = ThreadingHTTPServer((bind, actual_port), _BoundHandler)
    disp = "  dispatch=on" if dispatch else ""
    print(f"docket serve  port={actual_port}  refresh={interval}s{disp}  (Ctrl-C to stop)")
    print(
        f"Endpoints: /status.json  /metrics  /health  /approvals  /runs  /dispatch"
        f"  ->  http://localhost:{actual_port}/"
    )
    loopback = bind in ("127.0.0.1", "localhost", "::1")
    bind_note = "loopback-only" if loopback else "WARNING: not loopback — reachable off this host"
    print(f"Bind: {bind}  ({bind_note})")
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
        server.server_close()
