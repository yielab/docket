#!/usr/bin/env bash
# Command: serve — local HTTP endpoints for dashboards/monitoring.
#   /status.json  full snapshot (agents, bindings, costs)
#   /metrics      Prometheus-format metrics (scrapeable)
#   /health       liveness JSON

# Emit Prometheus-format metrics from the indexed cost data + gateway state.
_serve_metrics() {
  local gw=0
  service_ctl is-active &>/dev/null && gw=1
  local blob; blob=$(mktemp)
  _cost_json > "$blob" 2>/dev/null || echo '{"agents":[],"totalUsd":0}' > "$blob"
  RACK_GW_UP="$gw" python3 - "$blob" <<'PY'
import json, os, sys
try:
    d = json.load(open(sys.argv[1]))
except Exception:
    d = {"agents": [], "totalUsd": 0}
gw = os.environ.get("RACK_GW_UP", "0")

def esc(s):
    return str(s).replace("\\", "").replace('"', "")

lines = [
    "# HELP rack_agents_total Number of project agents",
    "# TYPE rack_agents_total gauge",
    "rack_agents_total " + str(len(d.get("agents", []))),
    "# HELP rack_agent_cost_usd Cumulative cost per agent (USD)",
    "# TYPE rack_agent_cost_usd gauge",
]
for a in d.get("agents", []):
    lab = 'agent="' + esc(a.get("id", "")) + '",model="' + esc(a.get("model", "")) + '"'
    lines.append("rack_agent_cost_usd{" + lab + "} " + str(a.get("costUsd", 0)))
    lines.append('rack_agent_turns_total{agent="' + esc(a.get("id", "")) + '"} ' + str(a.get("turns", 0)))
lines += [
    "# HELP rack_cost_usd_total Total cost across all agents (USD)",
    "# TYPE rack_cost_usd_total gauge",
    "rack_cost_usd_total " + str(d.get("totalUsd", 0)),
    "# HELP rack_gateway_up Gateway service active (1) or not (0)",
    "# TYPE rack_gateway_up gauge",
    "rack_gateway_up " + gw,
]
print("\n".join(lines))
PY
  rm -f "$blob"
}

# Write all served artifacts into the given directory.
_serve_refresh() {
  local dir="$1" gw=0
  service_ctl is-active &>/dev/null && gw=1
  cmd_snapshot > "$dir/status.json" 2>/dev/null || echo '{}' > "$dir/status.json"
  _serve_metrics > "$dir/metrics" 2>/dev/null || true
  printf '{"status":"ok","gateway":%s}\n' "$gw" > "$dir/health"
}

cmd_serve() {
  local port=7331 interval=30
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --port|-p)     port="$2";     shift 2 ;;
      --interval|-i) interval="$2"; shift 2 ;;
      *) shift ;;
    esac
  done

  local tmpdir; tmpdir=$(mktemp -d)
  trap 'rm -rf "$tmpdir"; kill $(jobs -p) 2>/dev/null; exit 0' INT TERM EXIT

  info "rack serve  port=$port  refresh=${interval}s  (Ctrl-C to stop)"
  info "Endpoints: /status.json  /metrics  /health  →  http://localhost:${port}/"
  echo ""

  _serve_refresh "$tmpdir"

  # Background refresh loop
  (
    while true; do
      sleep "$interval"
      _serve_refresh "$tmpdir" 2>/dev/null || true
    done
  ) &

  # Serve with Python's built-in HTTP server
  cd "$tmpdir" || { fail "Cannot enter $tmpdir"; return 1; }
  python3 -m http.server "$port" --bind 127.0.0.1 2>/dev/null
}
