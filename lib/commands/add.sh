#!/usr/bin/env bash
# Command: add

cmd_add() {
  header "Add Project Agent"
  echo ""

  # Type
  echo -e "${BOLD}Project type:${RESET}"
  echo "  1) repo   — codebase in ~/Sites (active development)"
  echo "  2) task   — web research, files, automation (no fixed codebase)"
  echo ""
  read -rp "Type [1/2]: " TYPE_INPUT
  case "$TYPE_INPUT" in
    1|repo) PROJECT_TYPE="repo" ;;
    2|task) PROJECT_TYPE="task" ;;
    *) error "Invalid. Use 1 or 2." ;;
  esac

  # Display name + slug
  echo ""
  read -rp "Display name (e.g. 'Sensor App'): " DISPLAY_NAME
  [[ -z "$DISPLAY_NAME" ]] && error "Display name required."

  DEFAULT_SLUG=$(slugify "$DISPLAY_NAME")
  read -rp "Agent ID [$DEFAULT_SLUG]: " AGENT_ID_INPUT
  AGENT_ID="${AGENT_ID_INPUT:-$DEFAULT_SLUG}"
  AGENT_ID=$(slugify "$AGENT_ID")

  [[ -d "$PROJECTS_DIR/$AGENT_ID" ]] && error "Project '$AGENT_ID' already exists. Use: rack repair $AGENT_ID"

  # Codebase
  CODEBASE_PATH=""
  DETECTED_STACK=""
  if [[ "$PROJECT_TYPE" == "repo" ]]; then
    CLOSEST=$(ls "$SITES_DIR" 2>/dev/null \
      | grep -i "$(echo "$DISPLAY_NAME" | tr ' ' '-' | tr '[:upper:]' '[:lower:]')" \
      | head -1 || true)
    DEFAULT_PATH="$SITES_DIR/${CLOSEST:-$DISPLAY_NAME}"
    read -rp "Codebase path [$DEFAULT_PATH]: " PATH_INPUT
    CODEBASE_PATH="${PATH_INPUT:-$DEFAULT_PATH}"
    if [[ -d "$CODEBASE_PATH" ]]; then
      DETECTED_STACK=$(detect_stack "$CODEBASE_PATH")
      info "Detected stack: $DETECTED_STACK"
    else
      warn "Path not found: $CODEBASE_PATH"
    fi
  fi

  read -rp "Description: " DESCRIPTION
  [[ -z "$DESCRIPTION" ]] && DESCRIPTION="No description provided."

  TECH_STACK=""
  if [[ "$PROJECT_TYPE" == "repo" ]]; then
    read -rp "Stack [${DETECTED_STACK:-unknown}]: " STACK_INPUT
    TECH_STACK="${STACK_INPUT:-$DETECTED_STACK}"
  fi

  read -rp "Model [$DEFAULT_MODEL]: " MODEL_INPUT
  MODEL="${MODEL_INPUT:-$DEFAULT_MODEL}"

  # Telegram
  echo ""
  header "Telegram group (Enter to skip)"
  _show_unbound_groups
  read -rp "Group ID (e.g. -1001234567890): " TG_GROUP_ID

  # Build workspace
  _create_workspace "$AGENT_ID" "$PROJECT_TYPE" "$DISPLAY_NAME" \
    "$CODEBASE_PATH" "$TECH_STACK" "$DESCRIPTION" "$MODEL"

  # Save metadata (all fields needed for deep reset / regeneration)
  meta_set "$AGENT_ID" "type"        "$PROJECT_TYPE"
  meta_set "$AGENT_ID" "name"        "$DISPLAY_NAME"
  meta_set "$AGENT_ID" "codebase"    "$CODEBASE_PATH"
  meta_set "$AGENT_ID" "stack"       "$TECH_STACK"
  meta_set "$AGENT_ID" "model"       "$MODEL"
  meta_set "$AGENT_ID" "description" "$DESCRIPTION"
  meta_set "$AGENT_ID" "created"     "$(date -Iseconds)"
  meta_set "$AGENT_ID" "sessionKey"  "$(generate_session_key "$AGENT_ID" "default")"
  meta_set "$AGENT_ID" "projectKey"  "default"

  # Create work directory for task-type projects (no fixed codebase)
  if [[ "$PROJECT_TYPE" == "task" ]]; then
    mkdir -p "$SITES_DIR/$AGENT_ID"
    success "Work directory created: $SITES_DIR/$AGENT_ID"
  fi

  # Register agent with openclaw
  openclaw agents add "$AGENT_ID" \
    --workspace "$PROJECTS_DIR/$AGENT_ID" \
    --model "$MODEL" \
    --non-interactive 2>&1 | grep -v "^$"
  success "Agent '$AGENT_ID' registered"
  audit_log "agent.add" "$AGENT_ID model=$MODEL"

  # Sync session key to OpenClaw config
  local session_key; session_key=$(meta_get "$AGENT_ID" "sessionKey" "agent:${AGENT_ID}:default")
  sync_session_key "$AGENT_ID" "$session_key"
  dbg "Session key synced to OpenClaw: $session_key"

  # Telegram
  if [[ -n "${TG_GROUP_ID:-}" ]]; then
    _wire_group "$AGENT_ID" "$TG_GROUP_ID"
    restart_gateway
  else
    _print_wire_instructions "$AGENT_ID"
  fi

  _print_summary "$AGENT_ID" "$PROJECT_TYPE" "$CODEBASE_PATH" "${TG_GROUP_ID:-}"
}

