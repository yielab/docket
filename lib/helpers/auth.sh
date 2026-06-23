#!/usr/bin/env bash
# Model-auth helpers — thin wrappers over OpenClaw's auth-profile system.
#
# OpenClaw authenticates each agent to its model provider through per-agent
# auth profiles stored in <agentDir>/auth-profiles.json and managed by
# `openclaw models auth`. This is the ONLY credential path the gateway honours
# for model calls — docket's secrets.json/.env feed agent *workspace* env vars
# (project work), not model auth. The 'main' agent's store is the canonical one
# created by `openclaw onboard` and shared by newly added agents.
#
# Profile types: token (subscription via setup-token, sk-ant-oat…), oauth, and
# api_key (pay-as-you-go, sk-ant-api…). A profile can be temporarily disabled by
# OpenClaw after a billing/usage failure (usageStats.disabledUntil).

# Path to the canonical model-auth store (the 'main' agent's profiles).
_auth_store() {
  local agent="${1:-main}"
  echo "$OPENCLAW_DIR/agents/$agent/agent/auth-profiles.json"
}

# Emit one line per configured profile: "<id>|<provider>|<type>|<state>"
# where state is "ok" or "disabled:<reason>". Empty output = no profiles.
auth_profiles_summary() {
  local store; store=$(_auth_store "${1:-main}")
  [[ -f "$store" ]] || return 0
  python3 - "$store" <<'PY' 2>/dev/null
import json, sys, time
try:
    d = json.load(open(sys.argv[1]))
except Exception:
    sys.exit(0)
now = time.time() * 1000
usage = d.get("usageStats", {}) or {}
for pid, prof in (d.get("profiles", {}) or {}).items():
    st = usage.get(pid, {}) or {}
    disabled = (st.get("disabledUntil", 0) or 0) > now
    state = "disabled:" + str(st.get("disabledReason", "?")) if disabled else "ok"
    print("%s|%s|%s|%s" % (pid, prof.get("provider", "?"), prof.get("type", "?"), state))
PY
}

# Pretty-print the profile summary with colour. Caller decides the heading.
auth_print_profiles() {
  local pid provider typ state
  while IFS='|' read -r pid provider typ state; do
    [[ -z "$pid" ]] && continue
    if [[ "$state" == "ok" ]]; then
      echo -e "  ${GREEN}●${RESET} $pid  ${DIM}($provider, $typ)${RESET}"
    else
      echo -e "  ${YELLOW}●${RESET} $pid  ${DIM}($provider, $typ)${RESET} — ${YELLOW}${state#disabled:} disabled${RESET}"
    fi
  done < <(auth_profiles_summary "${1:-main}")
}

# Exit 0 if at least one usable (non-disabled) profile exists. Used by `docket
# add` to warn early when a freshly added agent has no working credential.
openclaw_has_model_auth() {
  auth_profiles_summary "${1:-main}" | grep -q '|ok$'
}

# Interactive chooser: subscription (setup-token), API key (paste-token), or
# skip. Shells out to `openclaw models auth` so OpenClaw owns the credential and
# its on-disk format; docket only orchestrates. Safe to call from install or a
# standalone `docket auth` command.
auth_setup_interactive() {
  if ! command -v openclaw >/dev/null 2>&1; then
    warn "openclaw CLI not found — cannot configure auth."
    return 1
  fi
  echo ""
  echo -e "${BOLD}How should agents authenticate to Claude?${RESET}"
  echo "  1) Claude subscription (Pro/Max) — uses your plan; runs the provider token flow"
  echo "     ${DIM}Note: third-party/agent use draws from your extra usage, not plan limits.${RESET}"
  echo "  2) API key (pay-as-you-go)        — paste an sk-ant-… key"
  echo "  3) Skip for now"
  echo ""
  local choice
  read -rp "Choice [1/2/3]: " choice
  case "$choice" in
    1)
      info "Starting subscription token flow (openclaw models auth setup-token)..."
      if openclaw models auth setup-token --provider anthropic; then
        success "Subscription token configured."
        audit_log "auth.setup" "anthropic subscription (setup-token)"
      else
        warn "Token flow did not complete. Retry later: ${GREEN}openclaw models auth setup-token --provider anthropic${RESET}"
        return 1
      fi
      ;;
    2)
      info "Starting API-key flow (openclaw models auth paste-token)..."
      echo "  ${DIM}Get a key: ${BLUE}https://console.anthropic.com/settings/keys${RESET}"
      if openclaw models auth paste-token --provider anthropic; then
        success "API key configured."
        audit_log "auth.setup" "anthropic api-key (paste-token)"
      else
        warn "Paste-token flow did not complete. Retry later: ${GREEN}openclaw models auth paste-token --provider anthropic${RESET}"
        return 1
      fi
      ;;
    *)
      echo -e "  ${DIM}Skipped — configure later with: ${GREEN}docket auth${RESET}${DIM} (or openclaw models auth).${RESET}"
      return 1
      ;;
  esac
  restart_gateway
  return 0
}
