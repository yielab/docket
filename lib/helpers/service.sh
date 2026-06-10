#!/usr/bin/env bash
# Service control — gateway lifecycle, abstracted over the platform init system.
#
# rack was Linux/systemd-only; service_ctl lets it degrade cleanly elsewhere
# (macOS launchd, or no service manager) instead of calling systemctl blindly.
# On systemd the behaviour is identical to before. See ROADMAP Phase 3.

GATEWAY_UNIT="openclaw-gateway.service"

# Set RACK_NO_RESTART=1 to print instead of restarting (useful for testing).
RACK_GATEWAY_DIRTY=0

# Which init system manages user services here.
service_manager() {
  if [[ -n "${RACK_SERVICE_MANAGER:-}" ]]; then echo "$RACK_SERVICE_MANAGER"; return; fi
  if command -v systemctl >/dev/null 2>&1; then echo "systemd"
  elif command -v launchctl >/dev/null 2>&1; then echo "launchd"
  else echo "none"; fi
}

# The command string a user would run for an action — platform-appropriate, for
# use in hint messages. Usage: service_hint <start|restart|status>
service_hint() {
  local action="$1"
  case "$(service_manager)" in
    systemd) echo "systemctl --user $action $GATEWAY_UNIT" ;;
    launchd) echo "openclaw gateway $action  (or your launchd service)" ;;
    *)       echo "openclaw gateway $action" ;;
  esac
}

# Run a gateway service action. Usage: service_ctl <is-active|start|restart|status>
# On systemd, delegates to systemctl --user (unchanged behaviour). Off systemd,
# rack can't drive the unit: is-active reports not-active, others warn and fail —
# callers degrade gracefully rather than crashing.
service_ctl() {
  local action="$1"
  case "$(service_manager)" in
    systemd)
      systemctl --user "$action" "$GATEWAY_UNIT"
      ;;
    *)
      case "$action" in
        is-active) return 1 ;;
        status)    return 1 ;;
        *)
          warn "No systemd here — manage the OpenClaw gateway with: $(service_hint "$action")"
          return 1
          ;;
      esac
      ;;
  esac
}

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
  if service_ctl is-active &>/dev/null; then
    info "Restarting gateway..."
    if ! service_ctl restart 2>/dev/null; then
      warn "Gateway restart failed."
      echo "  Check: $(service_hint status)"
      return 1
    fi
    sleep 2
    success "Gateway restarted"
  else
    warn "Gateway not running. Start it with:"
    echo "  $(service_hint start)"
  fi
}
