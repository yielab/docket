#!/usr/bin/env bash
# Command: auth — manage how agents authenticate to the model provider.
#
# A thin, opinionated front-end over `openclaw models auth`. OpenClaw owns the
# credential store (auth-profiles.json); docket presents the subscription-first
# choice and reports status. See lib/helpers/auth.sh.

cmd_auth() {
  local sub="${1:-status}"
  shift || true

  case "$sub" in
    status|list|"")
      header "Claude authentication"
      echo ""
      local summary; summary=$(auth_profiles_summary)
      if [[ -z "$summary" ]]; then
        warn "No auth profiles configured — agents cannot answer."
        echo "  Set one up: ${GREEN}docket auth login${RESET}  (subscription)  ·  ${GREEN}docket auth key${RESET}  (API key)"
        return
      fi
      echo -e "${BOLD}Configured profiles:${RESET}"
      auth_print_profiles
      echo ""
      if auth_profiles_summary | grep -q '|ok$'; then
        success "At least one profile is usable."
      else
        warn "All profiles are disabled (usage/billing)."
        echo "  Subscription extra usage: ${BLUE}https://claude.ai/settings/usage${RESET}"
        echo "  Or re-fund / replace the API key, then: ${GREEN}docket auth key${RESET}"
      fi
      echo ""
      echo "Change: ${GREEN}docket auth login${RESET} (subscription) · ${GREEN}docket auth key${RESET} (API key)"
      echo "Low-level: ${GREEN}openclaw models auth${RESET}"
      ;;

    setup|choose)
      # Interactive subscription-or-key chooser.
      auth_setup_interactive
      ;;

    login|subscription|sub)
      command -v openclaw >/dev/null 2>&1 || error "openclaw CLI not found."
      info "Subscription token flow (openclaw models auth setup-token)..."
      if openclaw models auth setup-token --provider anthropic "$@"; then
        success "Subscription token configured."
        audit_log "auth.setup" "anthropic subscription (setup-token)"
        restart_gateway
      else
        error "Token flow did not complete. Retry: openclaw models auth setup-token --provider anthropic"
      fi
      ;;

    key|api|apikey)
      command -v openclaw >/dev/null 2>&1 || error "openclaw CLI not found."
      echo "  ${DIM}Get a key: ${BLUE}https://console.anthropic.com/settings/keys${RESET}"
      info "API-key flow (openclaw models auth paste-token)..."
      if openclaw models auth paste-token --provider anthropic "$@"; then
        success "API key configured."
        audit_log "auth.setup" "anthropic api-key (paste-token)"
        restart_gateway
      else
        error "Paste-token flow did not complete. Retry: openclaw models auth paste-token --provider anthropic"
      fi
      ;;

    *)
      error "Unknown auth subcommand '$sub'.
Usage:
  docket auth [status]        # show configured Claude auth profiles
  docket auth setup           # interactive: subscription or API key
  docket auth login           # configure Claude subscription (setup-token)
  docket auth key             # configure an API key (paste-token)"
      ;;
  esac
}
