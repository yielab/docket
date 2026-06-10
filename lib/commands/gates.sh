#!/usr/bin/env bash
# Command: gates — manage exec-approval enforcement (Phase 0 G3)
#
# Opt-in, re-runnable front door for the daemon's exec-approval gates. rack
# configures; the OpenClaw daemon enforces. See
# internal-docs/SECURITY-GATES-FEASIBILITY.md and
# specs/functional/security-gates.spec.md.

cmd_gates() {
  local subcmd="${1:-status}"
  shift || true

  case "$subcmd" in
    status)  _gates_status ;;
    enable)  _gates_enable "$@" ;;
    disable) _gates_disable ;;
    *)
      cat <<EOF
${BOLD}Usage:${RESET} rack gates <command>

${BOLD}Commands:${RESET}
  ${GREEN}status${RESET}            Show current exec-approval policy and audit posture
  ${GREEN}enable${RESET} [--force]  Apply conservative gate defaults + curated allowlist
  ${GREEN}disable${RESET}           Reset gate defaults (escape hatch; daemon falls back to tools.exec)

${BOLD}What 'enable' does:${RESET}
  Sets exec-approval defaults to ${CYAN}security=allowlist, ask=on-miss, askFallback=deny${RESET}
  and seeds each agent a curated allowlist of common, lower-risk binaries.
  Dangerous/non-allowlisted commands (rm, dd, docker, ...) then prompt and,
  with no approver reachable, are denied (fail-closed).

  ${DIM}Existing config is preserved; defaults are only overwritten with --force.${RESET}
  ${DIM}Verify anytime with 'rack doctor' (Security gates section).${RESET}
EOF
      ;;
  esac
}

_gates_status() {
  header "Exec-approval gates"
  echo ""
  local gate_line gs_state gs_policy gs_counts
  gate_line=$(_security_gate_report)
  IFS='|' read -r gs_state gs_policy gs_counts <<< "$gate_line"
  case "$gs_state" in
    OK)    success "Policy: $gs_policy" ; echo "  $gs_counts" ;;
    OPEN)  warn "Policy: $gs_policy — host exec is ungated ($gs_counts)" ;;
    UNSET) warn "Gates inactive — no exec-approval policy configured"
           echo "  Enable with: ${GREEN}rack gates enable${RESET}" ;;
    *)     dim "Status unavailable: ${gs_policy}" ;;
  esac

  local route_line r_state r_mode
  route_line=$(_approval_routing_status)
  IFS='|' read -r r_state r_mode <<< "$route_line"
  case "$r_state" in
    on)    success "Approval routing: on (mode=${r_mode:-?})" ;;
    off)   warn "Approval routing: off — prompts won't reach chat" ;;
    *)     dim "Approval routing: not configured" ;;
  esac
}

_gates_enable() {
  local force="${1:-}"
  header "Enabling exec-approval gates"
  echo ""
  warn "Fail-closed: commands not on the allowlist will prompt, and are DENIED"
  echo "  when no approver is reachable (Telegram approval routing is a later step)."
  echo "  Dangerous bins (rm, dd, docker, systemctl, ...) are intentionally gated."
  echo ""

  local out
  out=$(apply_exec_approval_gates "$force") || return 1

  # out = "<mode>|defaults_changed=N|seeded=...|bins=N"
  local mode rest
  mode="${out%%|*}"; rest="${out#*|}"
  local bins seeded dchg
  bins=$(printf '%s' "$rest" | tr '|' '\n' | sed -n 's/^bins=//p')
  seeded=$(printf '%s' "$rest" | tr '|' '\n' | sed -n 's/^seeded=//p')
  dchg=$(printf '%s' "$rest" | tr '|' '\n' | sed -n 's/^defaults_changed=//p')

  if [[ "$dchg" == "1" ]]; then
    success "Applied gate defaults (security=allowlist, ask=on-miss, askFallback=deny)"
  else
    info "Gate defaults already set — left as-is (use --force to overwrite)"
  fi
  [[ -n "$seeded" ]] && success "Seeded allowlist (${bins} bins) for: ${seeded}"
  case "$mode" in
    applied-via-daemon) info "Applied via the running gateway (openclaw approvals set)" ;;
    applied-direct)     info "Wrote ~/.openclaw/exec-approvals.json directly (gateway not reached)" ;;
  esac

  # G4 — wire the answer channel so fail-closed prompts are reachable.
  local tg_count
  if tg_count=$(apply_approval_routing); then
    success "Approval routing on (mode=session) — prompts go to each agent's channel"
    if [[ "${tg_count:-0}" -gt 0 ]]; then
      echo "  ${tg_count} Telegram-bound agent(s) can approve with: /approve <id> allow-once|deny"
    else
      warn "No Telegram-bound agents — wire one (rack wire <id>) so prompts are answerable."
    fi
  fi

  restart_gateway

  echo ""
  echo "  Verify:  ${GREEN}rack doctor${RESET}   ·   Tune:  ${GREEN}openclaw approvals allowlist add <glob>${RESET}"
  echo "  Disable: ${GREEN}rack gates disable${RESET}"
}

_gates_disable() {
  header "Disabling exec-approval gates"
  echo ""
  disable_exec_approval_gates || return 1
  disable_approval_routing || true
  restart_gateway
  success "Reset gate defaults + approval routing — daemon falls back to tools.exec policy"
  echo "  ${DIM}Seeded allowlists are left in place (harmless; reused if re-enabled).${RESET}"
}
