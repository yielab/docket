#!/usr/bin/env bash
# Command: serve — HTTP endpoint serving live snapshot JSON for team dashboards

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
  info "Endpoint: http://localhost:${port}/status.json"
  echo ""

  # Initial snapshot
  cmd_snapshot > "$tmpdir/status.json"

  # Background refresh loop
  (
    while true; do
      sleep "$interval"
      cmd_snapshot > "$tmpdir/status.json" 2>/dev/null || true
    done
  ) &

  # Serve with Python's built-in HTTP server
  cd "$tmpdir"
  python3 -m http.server "$port" --bind 127.0.0.1 2>/dev/null
}
