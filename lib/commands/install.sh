#!/usr/bin/env bash
# Command: install

cmd_install() {
  # Opt-in enforcement: gates are applied only with --gates (default install
  # leaves enforcement untouched so existing autonomous agents aren't blocked).
  local want_gates=0 a
  for a in "$@"; do
    case "$a" in
      --gates)    want_gates=1 ;;
      --no-gates) want_gates=0 ;;
    esac
  done

  header "Rack Installation — OpenClaw Setup"
  echo ""

  # Detect existing setup
  local is_existing_setup=false
  local needs_update=()

  if [[ -f "$CONFIG_FILE" ]]; then
    is_existing_setup=true
    info "Existing OpenClaw installation detected"
    echo ""

    # Check what needs updating
    if ! python3 -c "import json; c=json.load(open('$CONFIG_FILE')); exit(0 if 'agents' in c and 'defaults' in c['agents'] else 1)" 2>/dev/null; then
      needs_update+=("agent defaults")
    fi

    # Check for missing specialist agents
    local missing_specialists=()
    for spec in "${RACK_SPECIALISTS[@]}"; do
      if ! agent_registered "$spec"; then
        missing_specialists+=("$spec")
      fi
    done

    if [[ "${#missing_specialists[@]}" -gt 0 ]]; then
      needs_update+=("specialist agents: ${missing_specialists[*]}")
    fi

    if [[ "${#needs_update[@]}" -eq 0 ]]; then
      success "OpenClaw is fully configured!"
      echo ""
      echo "Current setup:"
      echo "  • Config: $CONFIG_FILE"
      echo "  • Projects: $PROJECTS_DIR"
      echo "  • Agents: $(python3 -c "import json; c=json.load(open('$CONFIG_FILE')); print(len(c.get('agents', {}).get('list', [])))" 2>/dev/null || echo "unknown")"
      echo ""
      read -rp "Reconfigure anyway? [y/N]: " CONFIRM
      [[ "${CONFIRM,,}" != "y" ]] && { info "Nothing to do. Run 'rack doctor' to verify health."; exit 0; }
    else
      warn "Updates needed:"
      for update in "${needs_update[@]}"; do
        echo "  • $update"
      done
      echo ""
      read -rp "Apply updates? [Y/n]: " CONFIRM
      [[ "${CONFIRM,,}" == "n" ]] && { warn "Aborted."; exit 0; }
    fi
  fi

  # Step 1: Check dependencies
  header "Step 1: Checking dependencies"
  local missing_deps=()

  if ! command -v openclaw &>/dev/null; then
    missing_deps+=("openclaw")
  else
    success "openclaw: $(openclaw --version 2>/dev/null || echo 'found')"
  fi

  if ! command -v python3 &>/dev/null; then
    missing_deps+=("python3")
  else
    success "python3: $(python3 --version 2>/dev/null | awk '{print $2}')"
  fi

  if ! command -v git &>/dev/null; then
    missing_deps+=("git")
  else
    success "git: $(git --version | awk '{print $3}')"
  fi

  if [[ "${#missing_deps[@]}" -gt 0 ]]; then
    error "Missing dependencies: ${missing_deps[*]}"
    echo ""
    echo "Install OpenClaw from: https://openclaw.dev"
    exit 1
  fi

  if command -v fzf &>/dev/null; then
    success "fzf: found (optional, improves UX)"
  else
    warn "fzf not found (optional) — install with: brew install fzf"
  fi

  echo ""

  # Step 2: Initialize OpenClaw if needed
  header "Step 2: OpenClaw initialization"
  if [[ ! -f "$CONFIG_FILE" ]]; then
    info "Running openclaw onboard..."
    echo ""
    openclaw onboard
    echo ""
    success "OpenClaw initialized"
  else
    success "OpenClaw already initialized"
  fi

  # Step 3: Create directory structure
  header "Step 3: Creating directory structure"
  mkdir -p "$PROJECTS_DIR"
  mkdir -p "$SITES_DIR"
  mkdir -p "$(dirname "$LOG_FILE")"

  chmod 700 "$OPENCLAW_DIR"
  chmod 700 "$PROJECTS_DIR"

  success "Directories created"
  echo "  $PROJECTS_DIR"
  echo "  $SITES_DIR"

  echo ""

  # Step 4: Configure agent defaults
  header "Step 4: Configuring agent defaults"
  python3 - "$CONFIG_FILE" "$DEFAULT_MODEL" <<'PY'
import json, sys
path, default_model = sys.argv[1], sys.argv[2]

with open(path) as f:
    config = json.load(f)

# Set defaults
if "agents" not in config:
    config["agents"] = {}

config["agents"]["defaults"] = {
    "model": {"primary": default_model},
    "workspace": f"{config.get('workspacesDir', '~/.openclaw/workspace')}",
    "compaction": {"mode": "safeguard"},
    "maxConcurrent": 4,
    "subagents": {"maxConcurrent": 8}
}

# Ensure channels exist
if "channels" not in config:
    config["channels"] = {}

if "telegram" not in config["channels"]:
    config["channels"]["telegram"] = {
        "enabled": True,
        "groups": {}
    }

with open(path, "w") as f:
    json.dump(config, f, indent=2)
PY

  success "Agent defaults configured"
  echo "  Default model: $DEFAULT_MODEL"
  echo "  Compaction: safeguard mode"
  echo "  Max concurrent: 4 agents"

  echo ""

  # Step 5: Install specialist agents (if not present).
  # Models come from the role→model policy (rack models), so a provider preset
  # switched before install provisions specialists on that provider.
  header "Step 5: Setting up specialist agents"

  local spec
  for spec in "${RACK_SPECIALISTS[@]}"; do
    local spec_model; spec_model=$(resolve_role_model "$spec")

    if agent_registered "$spec"; then
      success "$spec: already registered"
    else
      info "Creating $spec agent..."
      mkdir -p "$OPENCLAW_DIR/workspaces/$spec"
      openclaw agents add "$spec" \
        --workspace "$OPENCLAW_DIR/workspaces/$spec" \
        --model "$spec_model" \
        --non-interactive 2>&1 | grep -v "^$"
      success "$spec: created ($spec_model — ${ROLE_WHY[$spec]:-})"
    fi

    # Specialists are first-class citizens of the meta system: stamp (or
    # backfill) .rack-meta.json so list/profile/doctor manage them like any
    # other agent.
    if [[ -d "$OPENCLAW_DIR/workspaces/$spec" && ! -f "$OPENCLAW_DIR/workspaces/$spec/$META_FILE" ]]; then
      meta_set "$spec" "kind"        "specialist"
      meta_set "$spec" "role"        "$spec"
      meta_set "$spec" "name"        "$spec"
      meta_set "$spec" "model"       "$spec_model"
      meta_set "$spec" "modelSource" "policy"
      meta_set "$spec" "created"     "$(date -Iseconds)"
    fi
  done

  echo ""

  # Step 6: Configure security best practices
  header "Step 6: Configuring security best practices"

  # Harden permissions on sensitive state files so another local user can't read
  # secrets or rewrite tool/auth policy (G2). Enforcement gates (exec approvals,
  # workspace isolation) are specified in security-gates.spec.md and applied in a
  # later phase; see ROADMAP Phase 0.
  local _hardened; _hardened=$(secure_config_perms)
  if [[ -n "$_hardened" ]]; then
    while IFS= read -r _f; do
      [[ -n "$_f" ]] && success "Tightened permissions to 600: $_f"
    done <<< "$_hardened"
  else
    success "Config and secrets permissions already owner-only (600)"
  fi
  echo "  ${DIM}Verify posture anytime with: rack doctor  (Security gates section)${RESET}"

  # Opt-in exec-approval enforcement (G3).
  if [[ "$want_gates" -eq 1 ]]; then
    echo ""
    local _g_out
    if _g_out=$(apply_exec_approval_gates); then
      local _g_bins _g_seeded
      _g_bins=$(printf '%s' "$_g_out" | tr '|' '\n' | sed -n 's/^bins=//p')
      _g_seeded=$(printf '%s' "$_g_out" | tr '|' '\n' | sed -n 's/^seeded=//p')
      success "Exec-approval gates applied (security=allowlist, ask=on-miss, askFallback=deny)"
      [[ -n "$_g_seeded" ]] && echo "  Seeded allowlist (${_g_bins} bins) for: ${_g_seeded}"
      local _g_tg; _g_tg=$(apply_approval_routing 2>/dev/null) \
        && success "Approval routing on (mode=session); ${_g_tg:-0} Telegram-bound agent(s)"
      warn "Fail-closed: non-allowlisted commands are denied without an approver."
      echo "  Tune: ${GREEN}openclaw approvals allowlist add <glob>${RESET}  ·  Disable: ${GREEN}rack gates disable${RESET}"
    else
      warn "Could not apply exec-approval gates (see 'rack gates enable')"
    fi
  else
    echo "  ${DIM}Exec-approval enforcement is opt-in: 'rack gates enable' (or install --gates).${RESET}"
    echo "  ${DIM}Spec: specs/functional/security-gates.spec.md.${RESET}"
  fi

  echo ""

  # Step 7: Set up gateway service
  header "Step 7: Gateway service"
  if [[ "$(service_manager)" == "none" ]]; then
    warn "No service manager detected — start the OpenClaw gateway yourself:"
    echo "  $(service_hint start)"
  else
    if service_ctl is-active &>/dev/null; then
      success "Gateway already running"
      info "Restarting to apply changes..."
      service_ctl restart
      sleep 2
    else
      info "Starting gateway service..."
      service_ctl start 2>/dev/null || true
      sleep 2
    fi

    if service_ctl is-active &>/dev/null; then
      success "Gateway service: active"
    else
      warn "Gateway service not started"
      echo "  Start manually: $(service_hint start)"
    fi
  fi

  echo ""

  # Step 8: Summary
  header "Installation Complete!"
  echo ""
  echo -e "${BOLD}Next Steps:${RESET}"
  echo ""
  echo "  1. Add your first project agent:"
  echo "     ${GREEN}rack add${RESET}"
  echo ""
  echo "  2. Configure Telegram (optional but recommended):"
  echo "     - Create groups for each agent (manager, programmer, etc.)"
  echo "     - Add your bot to each group"
  echo "     - Wire agents: ${GREEN}rack wire <agent-id>${RESET}"
  echo ""
  echo "  3. Check system health:"
  echo "     ${GREEN}rack doctor${RESET}"
  echo ""
  echo -e "${BOLD}Specialist Agents (auto-created):${RESET}"
  echo "  • manager    - Orchestrates and delegates tasks"
  echo "  • programmer - Code implementation"
  echo "  • reviewer   - Code review and analysis"
  echo "  • tester     - Test execution and verification"
  echo "  • knowledge  - Memory distillation and patterns"
  echo "  • security   - Security audits and risk checks"
  echo ""
  echo -e "${BOLD}Configuration:${RESET}"
  echo "  Config: $CONFIG_FILE"
  echo "  Projects: $PROJECTS_DIR"
  echo "  Sites: $SITES_DIR"
  echo ""
  echo -e "${BOLD}Cost Management:${RESET}"
  echo "  Default model: $DEFAULT_MODEL"
  echo "  View usage: ${GREEN}rack cost${RESET}"
  echo "  Role→model policy: ${GREEN}rack models${RESET}   Pin one agent: ${GREEN}rack profile <id> <provider/model>${RESET}"
  echo ""
}

