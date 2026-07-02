"""Command: serve — local HTTP endpoints for dashboards / monitoring.

Exposes:
  /status.json         full snapshot (agents, bindings, costs)
  /metrics             Prometheus-format metrics (no external dependency)
  /health              liveness JSON
  /approvals           list pending approvals (auth required)
  /approvals/<token>   grant or deny a pending approval (auth required)

Security model: the server binds to 127.0.0.1 by default. A randomly-generated
Bearer token is printed at startup and required on every /approvals request
(DOCKET_SERVE_TOKEN env var pins a fixed token). The approval endpoints reject
all requests without a valid token before touching approval state.
"""

from __future__ import annotations

import contextlib
import datetime as _dt
import json
import os
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import docket.config as cfg
from docket.core import utils
from docket.edges.adapters import openclaw as oc

DEFAULT_PORT = 7331
DEFAULT_INTERVAL = 30

# Bumped on any breaking change to /status.json or /metrics contract.
# Pinned by tests/python/test_cd8_read_api.py (TestApiContract).
SERVE_API_VERSION = "1"

_SPECIALISTS = tuple(cfg.ORG_DISPLAY_ORDER)


def _utc_timestamp() -> str:
    """Return current UTC time as 'YYYY-MM-DDTHH:MM:SSZ' (matches `date -u`)."""
    return _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _last_activity_or_never(agent_id: str) -> str:
    """Like utils.last_activity but returns 'never' (cmd_snapshot's sentinel)."""
    val = utils.last_activity(agent_id)
    return "never" if val == "—" else val


def _agent_record(
    agent_id: str, *, kind: str, default_type: str, registered: set[str]
) -> dict[str, Any]:
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
        "type": str(meta.get("type", default_type)) if kind == "project" else "specialist",
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
    {id,name,type,kind,scope,model,registered,bindings,lastActivity,costUsd,budgetUsd}.
    Contract is versioned by ``SERVE_API_VERSION`` and pinned in
    ``specs/data/serve-read-api.spec.md``.
    """
    gateway = "active" if utils.gateway_active() else "inactive"
    channels = oc.channel_names()
    registered = {a.id for a in oc.list_agents()}

    agents: list[dict[str, Any]] = []
    total_cost = 0.0

    for pid in utils.project_ids():
        rec = _agent_record(pid, kind="project", default_type="repo", registered=registered)
        total_cost += float(rec["costUsd"])
        agents.append(rec)

    for spec in _SPECIALISTS:
        spec_dir = cfg.OPENCLAW_DIR / "workspaces" / spec
        if not spec_dir.is_dir():
            continue
        rec = _agent_record(
            spec, kind="specialist", default_type="specialist", registered=registered
        )
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


# Last-dispatch timestamp per project for the schedule checker.
# Initialised to 0.0 so every spec fires on the first sweep after serve starts.
_schedule_state: dict[str, float] = {}


def _check_schedules(now_ts: float) -> None:
    """Trigger dispatch for pods whose schedule spec is due.

    Reads the schedule config from ``cfg.SCHEDULE_FILE``. Each due project is
    dispatched in a daemon thread so the sweep loop is never blocked by an agent
    run. Failures are swallowed per-project (best-effort).
    """
    from docket.core import dispatch as _dispatch
    from docket.core import schedule as _sched

    schedules = _sched.load_schedules(cfg.SCHEDULE_FILE)
    for project, spec in schedules.items():
        last_run = _schedule_state.get(project, 0.0)
        if not _sched.is_schedule_due(spec, last_run, now_ts):
            continue
        _schedule_state[project] = now_ts

        def _run(proj: str = project) -> None:
            with contextlib.suppress(Exception):
                _dispatch.dispatch_pod(proj)

        t = threading.Thread(target=_run, daemon=True)
        t.start()


def _run_sweeps(dispatch: bool = False) -> None:
    """Run the periodic sweeps once, each best-effort.

    Coerces stale open traces to aborted and expires pending approvals past
    APPROVAL_TIMEOUT. Every sweep is guarded so one failure never aborts the
    others or the server.

    When *dispatch* is set, also drives every pod's queued tasks through its
    pipeline and checks the schedule file for due projects. These run real,
    budget-gated agent turns so they are opt-in (`docket serve --dispatch`)
    and never part of the read-only monitor.
    """
    import time

    from docket.core import approval, trace

    with contextlib.suppress(Exception):
        trace.sweep_all()
    with contextlib.suppress(Exception):
        approval.approval_sweep_expired()
    if dispatch:
        from docket.core import dispatch as _dispatch

        with contextlib.suppress(Exception):
            _dispatch.dispatch_all_pods()
        with contextlib.suppress(Exception):
            _check_schedules(time.time())


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
        return auth == f"Bearer {self.serve_token}"

    def _send_json_error(self, msg: str, status: int = 400) -> None:
        body = json.dumps({"ok": False, "error": msg}).encode()
        self._send(body, "application/json", status)

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0].rstrip("/")
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

            try:
                if action == "grant":
                    approval.approval_grant(approval_token)
                else:
                    approval.approval_deny(approval_token)
                rec = approval.approval_get(approval_token)
                resp_body = json.dumps(
                    {"ok": True, "token": approval_token, "state": rec["state"]}
                ).encode()
                self._send(resp_body, "application/json")
            except approval.ApprovalNoop as exc:
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

            def _run(proj: str = project) -> None:
                with contextlib.suppress(Exception):
                    _dispatch.dispatch_pod(proj)

            threading.Thread(target=_run, daemon=True).start()
            resp_body = json.dumps(
                {"ok": True, "project": project, "status": "dispatched"}
            ).encode()
            self._send(resp_body, "application/json")
        else:
            self._send_json_error("not found", 404)

    def do_HEAD(self) -> None:
        self.do_GET()


def run_serve(
    port: int | None = None,
    *,
    bind: str = "127.0.0.1",
    interval: int = DEFAULT_INTERVAL,
    dispatch: bool = False,
) -> None:
    """Start the docket HTTP server (blocking) — public CLI entry point.

    Binds to 127.0.0.1 on the given port (default 7331) and serves
    /status.json, /metrics, /health. Responses are built on each request
    (cheap, index-backed). Runs sweeps once at startup and then every
    *interval* seconds in a daemon thread. Runs until interrupted.
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
        f"Endpoints: /status.json  /metrics  /health  /approvals"
        f"  ->  http://localhost:{actual_port}/"
    )
    print(f"Approval API token: {_token}  (override: DOCKET_SERVE_TOKEN)")
    print("")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        server.server_close()
