#!/usr/bin/env bash
# Command: install

cmd_install() {
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
    local specialists=("programmer" "reviewer" "tester" "knowledge" "security")
    local missing_specialists=()
    for spec in "${specialists[@]}"; do
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
      echo "  • Agents: $(python3 -c "import json; c=json.load(open('$CONFIG_FILE')); print(len(c.get('agents', {}).get('registered', [])))" 2>/dev/null || echo "unknown")"
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

  # Step 5: Install specialist agents (if not present)
  header "Step 5: Setting up specialist agents"
  local specialists=("programmer" "reviewer" "tester" "knowledge" "security")
  local specialist_models=(
    "anthropic/claude-sonnet-4-6"
    "anthropic/claude-haiku-4-5"
    "anthropic/claude-haiku-4-5"
    "anthropic/claude-haiku-4-5"
    "anthropic/claude-sonnet-4-6"
  )

  for i in "${!specialists[@]}"; do
    local spec="${specialists[$i]}"
    local spec_model="${specialist_models[$i]}"

    if agent_registered "$spec"; then
      success "$spec: already registered"
    else
      info "Creating $spec agent..."
      openclaw agents add "$spec" \
        --workspace "$OPENCLAW_DIR/workspaces/$spec" \
        --model "$spec_model" \
        --non-interactive 2>&1 | grep -v "^$"
      success "$spec: created ($(model_to_profile "$spec_model"))"
    fi
  done

  echo ""

  # Step 6: Configure security best practices
  header "Step 6: Configuring security best practices"

  success "Security configuration skipped"
  echo "  Note: Tool approval gates and workspace isolation"
  echo "        are configured per-agent in TOOLS.md and SOUL.md"
  echo "        Run 'rack repair <id>' to apply security templates"

  echo ""

  # Step 7: Set up gateway service
  header "Step 7: Gateway service"
  if systemctl --user is-active openclaw-gateway.service &>/dev/null; then
    success "Gateway already running"
    info "Restarting to apply changes..."
    systemctl --user restart openclaw-gateway.service
    sleep 2
  else
    info "Starting gateway service..."
    systemctl --user start openclaw-gateway.service 2>/dev/null || true
    sleep 2
  fi

  if systemctl --user is-active openclaw-gateway.service &>/dev/null; then
    success "Gateway service: active"
  else
    warn "Gateway service not started"
    echo "  Start manually: systemctl --user start openclaw-gateway.service"
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
  echo "  2. Initialize team coordination (optional):"
  echo "     ${GREEN}rack team init${RESET}"
  echo ""
  echo "  3. Configure Telegram:"
  echo "     - Create groups for each agent"
  echo "     - Add your bot (@your_bot)"
  echo "     - Wire agents: ${GREEN}rack wire <agent-id>${RESET}"
  echo ""
  echo "  4. Check system health:"
  echo "     ${GREEN}rack doctor${RESET}"
  echo ""
  echo -e "${BOLD}Configuration:${RESET}"
  echo "  Config: $CONFIG_FILE"
  echo "  Projects: $PROJECTS_DIR"
  echo "  Sites: $SITES_DIR"
  echo ""
  echo -e "${BOLD}Cost Management:${RESET}"
  echo "  Default profile: $(model_to_profile "$DEFAULT_MODEL")"
  echo "  View usage: ${GREEN}rack cost${RESET}"
  echo "  Change profiles: ${GREEN}rack profile <id> economy|standard|premium${RESET}"
  echo ""
}

