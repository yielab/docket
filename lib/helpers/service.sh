#!/usr/bin/env bash
# Service control - gateway restart

# Restart gateway if running
restart_gateway() {
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
