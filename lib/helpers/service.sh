#!/usr/bin/env bash
# Service control - gateway restart

# Set RACK_NO_RESTART=1 to print instead of restarting (useful for testing).
RACK_GATEWAY_DIRTY=0

# Mark that the gateway config has changed and needs a restart at end of command.
mark_gateway_dirty() {
  RACK_GATEWAY_DIRTY=1
}

# Restart the gateway exactly once if marked dirty; no-op otherwise.
restart_gateway_if_dirty() {
  [[ "$RACK_GATEWAY_DIRTY" -eq 0 ]] && return 0
  RACK_GATEWAY_DIRTY=0
  restart_gateway
}

# Restart gateway if running
restart_gateway() {
  if [[ "${RACK_NO_RESTART:-0}" == "1" ]]; then
    echo "[dry-run] restart_gateway called"
    return 0
  fi
  dbg "Checking gateway service status..."
  if systemctl --user is-active openclaw-gateway.service &>/dev/null; then
    info "Restarting gateway..."
    if ! systemctl --user restart openclaw-gateway.service 2>/dev/null; then
      warn "Gateway restart failed."
      echo "  Check: systemctl --user status openclaw-gateway.service"
      return 1
    fi
    sleep 2
    success "Gateway restarted"
  else
    warn "Gateway not running. Start it with:"
    echo "  systemctl --user start openclaw-gateway.service"
  fi
}
