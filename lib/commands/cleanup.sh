#!/usr/bin/env bash
# Command: cleanup

cmd_cleanup() {
  local mode="${1:-safe}"
  local agent_id="${2:-}"

  header "Session Cleanup"
  echo ""

  case "$mode" in
    safe|--safe)
      info "Mode: Safe cleanup (sessions >100 turns or >5MB)"
      _cleanup_safe "$agent_id"
      ;;
    aggressive|--aggressive)
      warn "Mode: Aggressive cleanup (sessions >50 turns or >1MB)"
      read -rp "This will delete more sessions. Continue? [y/N]: " confirm
      [[ "${confirm,,}" != "y" ]] && { warn "Aborted."; exit 0; }
      _cleanup_aggressive "$agent_id"
      ;;
    all|--all)
      error "Mode: Delete ALL sessions"
      read -rp "This will delete ALL session history. Are you sure? [y/N]: " confirm
      [[ "${confirm,,}" != "y" ]] && { warn "Aborted."; exit 0; }
      _cleanup_all "$agent_id"
      ;;
    preview|--preview)
      info "Mode: Preview (show what would be deleted)"
      _cleanup_preview "$agent_id"
      ;;
    *)
      error "Invalid mode: $mode"
      echo ""
      echo "Usage: rack cleanup [mode] [agent-id]"
      echo ""
      echo "Modes:"
      echo "  safe         Delete sessions >100 turns or >5MB (default)"
      echo "  aggressive   Delete sessions >50 turns or >1MB"
      echo "  all          Delete ALL sessions"
      echo "  preview      Show what would be deleted"
      echo ""
      echo "Examples:"
      echo "  rack cleanup                    # Safe cleanup all agents"
      echo "  rack cleanup safe ai-site       # Safe cleanup one agent"
      echo "  rack cleanup preview            # Preview all"
      echo "  rack cleanup aggressive demo # Aggressive cleanup one agent"
      exit 1
      ;;
  esac
}

_cleanup_safe() {
  local agent_id="$1"
  local backup_dir="/tmp/openclaw-session-backup-$(date +%Y%m%d-%H%M%S)"
  mkdir -p "$backup_dir"

  info "Finding large sessions (>5MB or >100 turns)..."
  echo ""

  local sessions_to_clean=()
  local agents_dir="$HOME/.openclaw/agents"

  # Find sessions
  if [[ -n "$agent_id" ]]; then
    sessions_to_clean+=( $(find "$agents_dir/$agent_id/sessions" -name "*.jsonl" -size +5M 2>/dev/null) )
  else
    sessions_to_clean+=( $(find "$agents_dir/*/sessions" -name "*.jsonl" -size +5M 2>/dev/null) )
  fi

  if [[ ${#sessions_to_clean[@]} -eq 0 ]]; then
    success "No large sessions found. System is healthy!"
    return 0
  fi

  echo "Found ${#sessions_to_clean[@]} large session(s):"
  echo ""

  local total_size=0
  for session in "${sessions_to_clean[@]}"; do
    local size=$(stat -f%z "$session" 2>/dev/null || stat -c%s "$session" 2>/dev/null)
    local size_mb=$(echo "scale=1; $size / 1048576" | bc)
    local agent=$(echo "$session" | grep -oP '(?<=agents/)[^/]+(?=/sessions)' || echo "$session" | sed 's|.*/agents/\([^/]*\)/sessions.*|\1|')
    total_size=$((total_size + size))

    echo "  $(basename "$session")"
    echo "    Agent: $agent"
    echo "    Size:  ${size_mb}MB"
    echo ""
  done

  local total_mb=$(echo "scale=1; $total_size / 1048576" | bc)
  warn "Total size to remove: ${total_mb}MB"
  echo ""

  read -rp "Move these sessions to backup? [Y/n]: " confirm
  if [[ "${confirm,,}" == "n" ]]; then
    warn "Aborted."
    exit 0
  fi

  # Move to backup
  local count=0
  for session in "${sessions_to_clean[@]}"; do
    mv "$session" "$backup_dir/"
    ((count++))
  done

  success "Moved $count session(s) to: $backup_dir"
  echo ""
  info "To restore: mv $backup_dir/*.jsonl ~/.openclaw/agents/AGENT/sessions/"
}

_cleanup_aggressive() {
  local agent_id="$1"
  warn "Aggressive cleanup not yet implemented"
  echo "Use: rack cleanup safe"
}

_cleanup_all() {
  local agent_id="$1"
  error "Delete all sessions not yet implemented"
  echo "Use: rack cleanup safe"
}

_cleanup_preview() {
  local agent_id="$1"

  info "Scanning all agent sessions..."
  echo ""

  local agents_dir="$HOME/.openclaw/agents"

  # Find all sessions
  local all_sessions
  if [[ -n "$agent_id" ]]; then
    all_sessions=$(find "$agents_dir/$agent_id/sessions" -name "*.jsonl" 2>/dev/null)
  else
    all_sessions=$(find "$agents_dir/*/sessions" -name "*.jsonl" 2>/dev/null)
  fi

  if [[ -z "$all_sessions" ]]; then
    info "No sessions found"
    return 0
  fi

  echo -e "${BOLD}Session Size Report:${RESET}"
  echo ""
  printf "%-25s %10s %10s %s\n" "AGENT" "SIZE" "STATUS" "FILE"
  echo "────────────────────────────────────────────────────────────────────"

  local total_size=0
  local large_count=0
  local medium_count=0
  local small_count=0

  while IFS= read -r session; do
    local size=$(stat -f%z "$session" 2>/dev/null || stat -c%s "$session" 2>/dev/null)
    local size_mb=$(echo "scale=1; $size / 1048576" | bc)
    local agent=$(echo "$session" | grep -oP '(?<=agents/)[^/]+(?=/sessions)' || echo "$session" | sed 's|.*/agents/\([^/]*\)/sessions.*|\1|')
    local basename=$(basename "$session")
    total_size=$((total_size + size))

    local status color
    if (( $(echo "$size_mb > 5" | bc -l) )); then
      status="LARGE"
      color="$RED"
      ((large_count++))
    elif (( $(echo "$size_mb > 1" | bc -l) )); then
      status="MEDIUM"
      color="$YELLOW"
      ((medium_count++))
    else
      status="OK"
      color="$GREEN"
      ((small_count++))
    fi

    printf "%-25s %8.1fMB ${color}%10s${RESET} %s\n" "$agent" "$size_mb" "$status" "$basename"
  done <<< "$all_sessions"

  echo ""
  local total_mb=$(echo "scale=1; $total_size / 1048576" | bc)
  echo -e "${BOLD}Summary:${RESET}"
  echo "  Total sessions: $((large_count + medium_count + small_count))"
  echo "  Total size:     ${total_mb}MB"
  echo ""
  echo "  ${RED}Large (>5MB):${RESET}   $large_count  ← Should clean"
  echo "  ${YELLOW}Medium (>1MB):${RESET}  $medium_count  ← Consider cleaning"
  echo "  ${GREEN}OK (<1MB):${RESET}      $small_count"
  echo ""

  if [[ $large_count -gt 0 ]]; then
    warn "Run: ${CYAN}rack cleanup safe${RESET} to remove large sessions"
  else
    success "No large sessions found!"
  fi
}
