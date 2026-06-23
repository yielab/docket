"""Command: serve — local HTTP endpoints for dashboards / monitoring.

Stdlib-only (``http.server``) port of ``lib/commands/serve.sh``. Exposes three
endpoints with a byte-compatible output contract:

  /status.json  full snapshot (agents, bindings, costs)  — mirrors cmd_snapshot
  /metrics      Prometheus-format metrics                 — mirrors _serve_metrics
  /health       liveness JSON                             — mirrors _serve_refresh

The Bash hand-formats the Prometheus text, so we do too (no prometheus_client
dependency). All agent/cost data is read via ``core.utils`` and the OpenClaw
ACL — this module never parses ``openclaw.json`` directly.
"""

from __future__ import annotations

import contextlib
import datetime as _dt
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import docket.config as cfg
from docket.core import utils
from docket.edges.adapters import openclaw as oc

DEFAULT_PORT = 7331
DEFAULT_INTERVAL = 30

# Specialist roles, in the same order cmd_snapshot iterates them.
_SPECIALISTS = ("manager", "programmer", "reviewer", "tester", "knowledge", "security")


# ── data builders (pure, socket-free, unit-testable) ──────────────────────────


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
    # Read meta tolerantly via the raw store to mirror cmd_snapshot's read_meta
    # (a missing/invalid file yields {} rather than raising).
    from docket.edges import store

    meta_path = cfg.meta_path(agent_id)
    meta: dict[str, Any] = store.read_json(meta_path) if meta_path.exists() else {}
    cost = round(utils.aggregate_cost(agent_id).cost_usd, 6)
    return {
        "id": agent_id,
        "name": str(meta.get("name", agent_id)),
        "type": str(meta.get("type", default_type)) if kind == "project" else "specialist",
        "kind": kind,
        "model": str(meta.get("model", "")),
        "registered": agent_id in registered,
        "bindings": oc.agent_bindings(agent_id),
        "lastActivity": _last_activity_or_never(agent_id),
        "costUsd": cost,
    }


def build_status() -> dict[str, Any]:
    """Build the /status.json payload (mirrors cmd_snapshot).

    Shape::

        {timestamp, gateway, channels, agents:[...], totalCostUsd}

    ``gateway`` is the systemd is-active string ("active"/"inactive"); each
    agent carries {id,name,type,kind,model,registered,bindings,lastActivity,costUsd}.
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
        "timestamp": _utc_timestamp(),
        "gateway": gateway,
        "channels": channels,
        "agents": agents,
        "totalCostUsd": round(total_cost, 6),
    }


def _cost_json() -> dict[str, Any]:
    """Per-project cost payload mirroring _cost_json in cost.sh.

    Returns {agents:[{id,model,costUsd,turns,...}], totalUsd}. Metrics only
    cover project agents (specialists are excluded), matching the Bash.
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
    """Strip backslashes and double-quotes from a label value (matches Bash esc)."""
    return str(s).replace("\\", "").replace('"', "")


def render_metrics() -> str:
    """Render Prometheus-format metrics (mirrors _serve_metrics).

    Hand-formatted to match the Bash metric names, labels, and ordering exactly.
    No trailing newline (the Bash `print("\\n".join(lines))` adds one when
    served; callers append it).
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
    lines += [
        "# HELP docket_cost_usd_total Total cost across all agents (USD)",
        "# TYPE docket_cost_usd_total gauge",
        "docket_cost_usd_total " + str(d.get("totalUsd", 0)),
        "# HELP docket_gateway_up Gateway service active (1) or not (0)",
        "# TYPE docket_gateway_up gauge",
        "docket_gateway_up " + gw,
    ]
    return "\n".join(lines)


def render_health() -> str:
    """Render the /health body (mirrors _serve_refresh's health write).

    Format: ``{"status":"ok","gateway":N}\\n`` where N is 1 or 0.
    """
    gw = 1 if utils.gateway_active() else 0
    return f'{{"status":"ok","gateway":{gw}}}\n'


def render_status() -> str:
    """Render the /status.json body (indent=2, matching cmd_snapshot)."""
    return json.dumps(build_status(), indent=2)


# ── periodic sweeps (mirror _serve_refresh) ───────────────────────────────────


def _run_sweeps() -> None:
    """Run the three _serve_refresh sweeps once, each best-effort.

    Mirrors _serve_refresh's tail: coerce stale open traces to aborted (OBS-3),
    expire pending approvals past APPROVAL_TIMEOUT (H5), and check role drift
    (OBS-11). Every sweep is guarded so one failure never aborts the others or
    the server (matching the Bash ``2>/dev/null || true`` guards).
    """
    from docket.core import approval, drift, trace

    with contextlib.suppress(Exception):
        trace.sweep_all()
    with contextlib.suppress(Exception):
        approval.approval_sweep_expired()
    with contextlib.suppress(Exception):
        drift.drift_check_all()


def _sweep_loop(interval: int, stop: threading.Event) -> None:
    """Run _run_sweeps every *interval* seconds until *stop* is set."""
    while not stop.wait(interval):
        _run_sweeps()


# ── HTTP server ───────────────────────────────────────────────────────────────


class _DocketHandler(BaseHTTPRequestHandler):
    """Serves the three docket endpoints; builds responses on demand."""

    # Silence the default per-request stderr logging (Bash uses 2>/dev/null).
    def log_message(self, fmt: str, *args: Any) -> None:
        return

    def _send(self, body: bytes, content_type: str, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0].rstrip("/")
        if path in ("/status.json", "/status"):
            self._send(render_status().encode("utf-8"), "application/json")
        elif path == "/metrics":
            self._send((render_metrics() + "\n").encode("utf-8"), "text/plain; version=0.0.4")
        elif path == "/health":
            self._send(render_health().encode("utf-8"), "application/json")
        else:
            self._send(b"not found\n", "text/plain", status=404)

    def do_HEAD(self) -> None:
        self.do_GET()


def run_serve(
    port: int | None = None, *, bind: str = "127.0.0.1", interval: int = DEFAULT_INTERVAL
) -> None:
    """Start the docket HTTP server (blocking) — public CLI entry point.

    Mirrors cmd_serve: binds to 127.0.0.1 on the given port (default 7331) and
    serves /status.json, /metrics, /health. Responses are built on each request
    (cheap, index-backed). The Bash also ran _serve_refresh once at startup and
    then every *interval* seconds (default 30); we mirror those periodic sweeps
    (trace/approval/drift) with a daemon thread. Runs until interrupted.
    """
    actual_port = DEFAULT_PORT if port is None else port

    # Run the sweeps once at startup, then on each interval (mirrors cmd_serve).
    _run_sweeps()
    stop = threading.Event()
    sweeper = threading.Thread(target=_sweep_loop, args=(interval, stop), daemon=True)
    sweeper.start()

    server = ThreadingHTTPServer((bind, actual_port), _DocketHandler)
    print(f"docket serve  port={actual_port}  refresh={interval}s  (Ctrl-C to stop)")
    print(f"Endpoints: /status.json  /metrics  /health  ->  http://localhost:{actual_port}/")
    print("")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        server.server_close()
