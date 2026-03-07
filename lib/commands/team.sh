#!/usr/bin/env bash
# Command: team — Manage specialist agents and RACK architecture

cmd_team() {
  local subcommand="${1:-status}"

  case "$subcommand" in
    status)
      _team_status
      ;;
    upgrade)
      _team_upgrade
      ;;
    check)
      _team_check
      ;;
    roles)
      _team_roles
      ;;
    init)
      warn "'team init' is deprecated. Use 'rack install' instead."
      ;;
    *)
      _team_help
      ;;
  esac
}

_team_help() {
  header "Team Management"
  echo ""
  echo "Manage specialist agents with RACK architecture"
  echo ""
  echo -e "${BOLD}Usage:${RESET}"
  echo "  rack team status      Show specialist agent health"
  echo "  rack team upgrade     Upgrade specialists to RACK templates"
  echo "  rack team check       Verify all specialists exist"
  echo "  rack team roles       Show agent roles and responsibilities"
  echo ""
}

_team_status() {
  header "Specialist Team Status"
  echo ""

  local specialists=("manager" "programmer" "reviewer" "tester" "knowledge" "security")

  for spec in "${specialists[@]}"; do
    local workspace="$OPENCLAW_DIR/workspaces/$spec"

    if [[ ! -d "$workspace" ]]; then
      printf "  ${RED}✗${RESET} %-12s Not installed\n" "$spec"
      continue
    fi

    # Check if SOUL.md exists
    if [[ ! -f "$workspace/SOUL.md" ]]; then
      printf "  ${YELLOW}⚠${RESET} %-12s Missing SOUL.md\n" "$spec"
      continue
    fi

    # Check if RACK-optimized (has RACK keywords or specialized patterns)
    if grep -qE "RACK Architecture|Context Compression|Short-Circuit|veto power|Mandatory.*checklist|validation specialist|compressed brief|observe behavior" "$workspace/SOUL.md" 2>/dev/null; then
      printf "  ${GREEN}✓${RESET} %-12s RACK-optimized\n" "$spec"
    else
      printf "  ${CYAN}○${RESET} %-12s Standard (upgrade available)\n" "$spec"
    fi
  done

  echo ""

  # Count upgraded vs total
  local upgraded=$(grep -lE "RACK Architecture|Context Compression|validation specialist|veto power|compressed brief|observe behavior" ~/.openclaw/workspaces/*/SOUL.md 2>/dev/null | wc -l | tr -d ' ')
  local total=${#specialists[@]}

  if [[ $upgraded -eq $total ]] || [[ $upgraded -ge 4 ]]; then
    dim "All core specialists RACK-optimized (knowledge & security use standard templates)"
  else
    dim "Run 'rack team upgrade' to apply RACK templates"
  fi
  echo ""
}

_team_check() {
  header "Specialist Agent Health Check"
  echo ""

  local specialists=("programmer" "reviewer" "tester" "knowledge" "security" "manager")
  local missing=()
  local healthy=0

  for spec in "${specialists[@]}"; do
    if agent_registered "$spec"; then
      success "$spec: registered"
      healthy=$((healthy + 1))
    else
      warn "$spec: NOT registered"
      missing+=("$spec")
    fi
  done

  echo ""

  if [[ "${#missing[@]}" -eq 0 ]]; then
    success "All specialists healthy ($healthy/6)"
  else
    error "Missing specialists: ${missing[*]}"
    echo ""
    echo "Run: rack install"
    exit 1
  fi
}

_team_roles() {
  header "Specialist Agent Roles (RACK Architecture)"
  echo ""

  echo -e "${BOLD}${GREEN}Manager (Atlas)${RESET}"
  echo "  • Orchestrates tasks and delegates to specialists"
  echo "  • Embedded classifier logic (routes tasks efficiently)"
  echo "  • Context compression before delegation"
  echo "  • Short-circuit resolution for simple queries"
  echo "  • Model: Sonnet | Tools: read (memory), message"
  echo ""

  echo -e "${BOLD}${GREEN}Programmer${RESET}"
  echo "  • Implements code changes from compressed briefs"
  echo "  • Reads <5K tokens per task (file + brief only)"
  echo "  • Signals completion via memory files"
  echo "  • Model: Haiku (simple) / Sonnet (complex)"
  echo "  • Tools: read, write, edit, exec (sandbox)"
  echo ""

  echo -e "${BOLD}${GREEN}Reviewer (Auditor)${RESET}"
  echo "  • Security + correctness gatekeeper"
  echo "  • 6-point mandatory checklist"
  echo "  • Veto power (bad code doesn't proceed)"
  echo "  • Model: Sonnet | Tools: read (diff only)"
  echo ""

  echo -e "${BOLD}${GREEN}Tester (Validator)${RESET}"
  echo "  • Behavior-only validation (doesn't read code!)"
  echo "  • Executes reproduction steps"
  echo "  • Binary verdict: PASS or FAIL"
  echo "  • Model: Haiku | Tools: exec, browser (read-only)"
  echo ""

  echo -e "${BOLD}${GREEN}Knowledge${RESET}"
  echo "  • Memory distillation and indexing"
  echo "  • Pattern extraction from logs"
  echo "  • Architectural decision tracking"
  echo "  • Model: Haiku | Tools: read, memory search"
  echo ""

  echo -e "${BOLD}${GREEN}Security${RESET}"
  echo "  • Deep threat modeling (beyond code review)"
  echo "  • Penetration testing coordination"
  echo "  • Compliance audits (GDPR, HIPAA)"
  echo "  • Model: Sonnet | Tools: read, browser"
  echo ""

  echo -e "${DIM}Note: Reviewer handles routine security checks. Security specialist"
  echo -e "      handles deep audits, compliance, and threat modeling.${RESET}"
  echo ""
}

_team_upgrade() {
  header "Upgrading Specialists to RACK Architecture"
  echo ""

  warn "This will replace SOUL.md files with RACK-optimized templates"
  echo ""
  echo "Changes:"
  echo "  • Manager: Add classifier logic + context compression rules"
  echo "  • Programmer: Add brief-only reading + <5K token targets"
  echo "  • Reviewer: Add 6-point security checklist + veto power"
  echo "  • Tester: Add behavior-only validation (no code reading)"
  echo "  • Knowledge: No changes (already efficient)"
  echo "  • Security: No changes (focused on deep audits)"
  echo ""

  read -rp "Proceed with upgrade? [y/N]: " CONFIRM
  [[ "${CONFIRM,,}" != "y" ]] && { warn "Aborted."; return; }

  echo ""

  local template_dir="$RACK_CLI_ROOT/lib/templates"
  local upgraded=0
  local failed=0

  # Upgrade Manager
  info "Upgrading manager..."
  local manager_workspace="$OPENCLAW_DIR/workspaces/manager"
  if [[ -d "$manager_workspace" ]]; then
    # Backup existing SOUL.md
    if [[ -f "$manager_workspace/SOUL.md" ]]; then
      cp "$manager_workspace/SOUL.md" "$manager_workspace/SOUL.md.backup-$(date +%Y%m%d-%H%M%S)"
    fi

    # Apply RACK template
    cp "$template_dir/rack-manager.md" "$manager_workspace/SOUL.md"
    chmod 600 "$manager_workspace/SOUL.md"

    success "manager: upgraded (backup saved)"
    upgraded=$((upgraded + 1))
  else
    warn "manager: workspace not found"
    failed=$((failed + 1))
  fi

  # Upgrade Programmer
  info "Upgrading programmer..."
  local programmer_workspace="$OPENCLAW_DIR/workspaces/programmer"
  if [[ -d "$programmer_workspace" ]]; then
    if [[ -f "$programmer_workspace/SOUL.md" ]]; then
      cp "$programmer_workspace/SOUL.md" "$programmer_workspace/SOUL.md.backup-$(date +%Y%m%d-%H%M%S)"
    fi

    cp "$template_dir/rack-programmer.md" "$programmer_workspace/SOUL.md"
    chmod 600 "$programmer_workspace/SOUL.md"

    success "programmer: upgraded"
    upgraded=$((upgraded + 1))
  else
    warn "programmer: workspace not found"
    failed=$((failed + 1))
  fi

  # Upgrade Reviewer
  info "Upgrading reviewer..."
  local reviewer_workspace="$OPENCLAW_DIR/workspaces/reviewer"
  if [[ -d "$reviewer_workspace" ]]; then
    if [[ -f "$reviewer_workspace/SOUL.md" ]]; then
      cp "$reviewer_workspace/SOUL.md" "$reviewer_workspace/SOUL.md.backup-$(date +%Y%m%d-%H%M%S)"
    fi

    cp "$template_dir/rack-reviewer.md" "$reviewer_workspace/SOUL.md"
    chmod 600 "$reviewer_workspace/SOUL.md"

    success "reviewer: upgraded"
    upgraded=$((upgraded + 1))
  else
    warn "reviewer: workspace not found"
    failed=$((failed + 1))
  fi

  # Upgrade Tester
  info "Upgrading tester..."
  local tester_workspace="$OPENCLAW_DIR/workspaces/tester"
  if [[ -d "$tester_workspace" ]]; then
    if [[ -f "$tester_workspace/SOUL.md" ]]; then
      cp "$tester_workspace/SOUL.md" "$tester_workspace/SOUL.md.backup-$(date +%Y%m%d-%H%M%S)"
    fi

    cp "$template_dir/rack-tester.md" "$tester_workspace/SOUL.md"
    chmod 600 "$tester_workspace/SOUL.md"

    success "tester: upgraded"
    upgraded=$((upgraded + 1))
  else
    warn "tester: workspace not found"
    failed=$((failed + 1))
  fi

  # Knowledge and Security don't need upgrades (already efficient)
  info "knowledge: no upgrade needed (already optimized)"
  info "security: no upgrade needed (already optimized)"

  echo ""

  if [[ $failed -gt 0 ]]; then
    warn "Upgraded: $upgraded, Failed: $failed"
    echo ""
    echo "Missing agents? Run: rack install"
  else
    success "All specialists upgraded! ($upgraded agents)"
  fi

  echo ""
  info "Restarting gateway to apply changes..."
  restart_gateway

  echo ""
  success "RACK upgrade complete!"
  echo ""
  echo -e "${BOLD}Next Steps:${RESET}"
  echo "  1. Test specialist responses: Send a message to manager in Telegram"
  echo "  2. Verify context efficiency: Check token usage in next session"
  echo "  3. Test bug-fix pipeline: rack workflow manager create bug-fix"
  echo ""
  echo -e "${BOLD}What Changed:${RESET}"
  echo "  • Manager now compresses context before delegating (<500 tokens)"
  echo "  • Programmer reads brief only (not full history)"
  echo "  • Reviewer runs 6-point security checklist"
  echo "  • Tester validates behavior (doesn't read code)"
  echo ""
  echo -e "${BOLD}Expected Benefits:${RESET}"
  echo "  • 50-80% reduction in token usage for routine tasks"
  echo "  • Faster response times (less context to process)"
  echo "  • Better security (mandatory checklist on every change)"
  echo "  • More reliable validation (objective behavior tests)"
  echo ""
}
