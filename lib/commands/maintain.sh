#!/usr/bin/env bash
# Command: maintain - Unified agent maintenance (replaces reset/repair/cleanup)

cmd_maintain() {
  local id="${1:-}"
  local mode="${2:-check}"

  # Interactive picker if no ID provided
  [[ -z "$id" ]] && id=$(pick_project "Select agent to maintain")

  local workspace="$PROJECTS_DIR/$id"
  [[ ! -d "$workspace" ]] && error "Agent '$id' not found"

  case "$mode" in
    check)
      _maintain_check "$id" "$workspace"
      ;;
    clean)
      _maintain_clean "$id" "$workspace"
      ;;
    reset)
      _maintain_reset "$id" "$workspace"
      ;;
    rebuild)
      _maintain_rebuild "$id" "$workspace"
      ;;
    sessions)
      _maintain_sessions "$id" "$workspace"
      ;;
    *)
      _maintain_help
      ;;
  esac
}

_maintain_help() {
  header "Rack Maintain — Agent Maintenance"
  echo ""
  echo "${BOLD}Usage:${RESET}"
  echo "  rack maintain [agent-id] [mode]"
  echo ""
  echo "${BOLD}Modes:${RESET}"
  echo "  ${GREEN}check${RESET}       Health check & auto-fix issues (default)"
  echo "              • Fix permissions (700/600)"
  echo "              • Regenerate missing files"
  echo "              • Sync session keys"
  echo "              ${DIM}Replaces: rack repair${RESET}"
  echo ""
  echo "  ${GREEN}clean${RESET}       Clear memory logs only"
  echo "              • Delete memory/*.md files"
  echo "              • Preserve SOUL.md, AGENTS.md, TOOLS.md"
  echo "              ${DIM}Replaces: rack reset 1${RESET}"
  echo ""
  echo "  ${GREEN}reset${RESET}       Clear memory + heartbeat"
  echo "              • Delete memory logs"
  echo "              • Clear MEMORY.md"
  echo "              • Clear HEARTBEAT.md"
  echo "              ${DIM}Replaces: rack reset 2${RESET}"
  echo ""
  echo "  ${GREEN}rebuild${RESET}     Deep rebuild from metadata"
  echo "              • Regenerate SOUL.md, AGENTS.md, TOOLS.md"
  echo "              • Clear all memory"
  echo "              • Fix all issues"
  echo "              ${DIM}Replaces: rack reset 3${RESET}"
  echo ""
  echo "  ${GREEN}sessions${RESET}    Clean large/old sessions"
  echo "              • Archive sessions >5MB or >30 days"
  echo "              • Free up disk space"
  echo "              ${DIM}Replaces: rack cleanup safe${RESET}"
  echo ""
  echo "${BOLD}Examples:${RESET}"
  echo "  rack maintain myproject              # Health check (default)"
  echo "  rack maintain myproject clean        # Clear memory logs"
  echo "  rack maintain myproject sessions     # Clean old sessions"
  echo "  rack maintain                        # Interactive picker"
  echo ""
  echo "${BOLD}Migration from old commands:${RESET}"
  echo "  ${DIM}rack repair → rack maintain check${RESET}"
  echo "  ${DIM}rack reset 1 → rack maintain clean${RESET}"
  echo "  ${DIM}rack reset 2 → rack maintain reset${RESET}"
  echo "  ${DIM}rack reset 3 → rack maintain rebuild${RESET}"
  echo "  ${DIM}rack cleanup safe → rack maintain sessions${RESET}"
}

_maintain_check() {
  local id="$1"
  local workspace="$2"

  header "Maintenance Check: $(meta_get "$id" "name" "$id")"
  echo ""

  local issues_found=0
  local fixes_applied=0

  # Check permissions
  echo "${BOLD}Checking permissions...${RESET}"
  local workspace_perms=$(stat -c%a "$workspace" 2>/dev/null || stat -f%Lp "$workspace" 2>/dev/null)

  if [[ "$workspace_perms" != "700" ]]; then
    warn "  Workspace permissions: $workspace_perms (expected 700)"
    chmod 700 "$workspace"
    success "  ✓ Fixed workspace permissions"
    ((fixes_applied++))
    ((issues_found++))
  else
    success "  ✓ Workspace permissions OK"
  fi

  # Check file permissions
  local bad_perms=0
  for file in "$workspace"/{SOUL.md,AGENTS.md,TOOLS.md,HEARTBEAT.md,.rack-meta.json}; do
    if [[ -f "$file" ]]; then
      local perms=$(stat -c%a "$file" 2>/dev/null || stat -f%Lp "$file" 2>/dev/null)
      if [[ "$perms" != "600" ]]; then
        chmod 600 "$file"
        ((bad_perms++))
      fi
    fi
  done

  if [[ $bad_perms -gt 0 ]]; then
    success "  ✓ Fixed $bad_perms file permission(s)"
    ((fixes_applied++))
    ((issues_found++))
  else
    success "  ✓ File permissions OK"
  fi

  echo ""

  # Check missing files
  echo "${BOLD}Checking workspace files...${RESET}"
  local missing_files=()

  [[ ! -f "$workspace/SOUL.md" ]] && missing_files+=("SOUL.md")
  [[ ! -f "$workspace/AGENTS.md" ]] && missing_files+=("AGENTS.md")
  [[ ! -f "$workspace/TOOLS.md" ]] && missing_files+=("TOOLS.md")
  [[ ! -f "$workspace/HEARTBEAT.md" ]] && missing_files+=("HEARTBEAT.md")
  [[ ! -f "$workspace/.rack-meta.json" ]] && missing_files+=(".rack-meta.json")

  if [[ ${#missing_files[@]} -gt 0 ]]; then
    warn "  Missing files: ${missing_files[*]}"
    ((issues_found++))

    echo ""
    read -rp "  Regenerate missing files? [Y/n]: " confirm
    if [[ ! "$confirm" =~ ^[Nn]$ ]]; then
      # Call repair logic to regenerate
      _regenerate_workspace_files "$id" "$workspace"
      success "  ✓ Regenerated ${#missing_files[@]} file(s)"
      ((fixes_applied++))
    fi
  else
    success "  ✓ All workspace files present"
  fi

  echo ""

  # Check session key sync
  echo "${BOLD}Checking session key sync...${RESET}"
  local meta_key=$(meta_get "$id" "sessionKey" "")
  local soul_key=""

  if [[ -f "$workspace/SOUL.md" ]]; then
    soul_key=$(grep -oP 'Session Key: \K.*' "$workspace/SOUL.md" 2>/dev/null || echo "")
  fi

  if [[ "$meta_key" != "$soul_key" ]]; then
    warn "  Session key mismatch"
    echo "    Metadata: $meta_key"
    echo "    SOUL.md:  $soul_key"
    ((issues_found++))

    sync_session_key "$id"
    success "  ✓ Session key synced"
    ((fixes_applied++))
  else
    success "  ✓ Session key in sync"
  fi

  echo ""

  # Check memory directory
  echo "${BOLD}Checking memory...${RESET}"
  if [[ ! -d "$workspace/memory" ]]; then
    warn "  Memory directory missing"
    mkdir -p "$workspace/memory"
    chmod 700 "$workspace/memory"
    success "  ✓ Created memory directory"
    ((fixes_applied++))
    ((issues_found++))
  else
    local log_count=$(find "$workspace/memory" -name "*.md" -type f 2>/dev/null | wc -l)
    success "  ✓ Memory directory OK ($log_count logs)"
  fi

  echo ""

  # Summary
  if [[ $issues_found -eq 0 ]]; then
    header "Status: ${GREEN}✓ HEALTHY${RESET}"
    echo ""
    success "No issues found. Agent is in good condition!"
  else
    header "Status: ${YELLOW}⚠ ISSUES FOUND${RESET}"
    echo ""
    info "Found $issues_found issue(s), applied $fixes_applied fix(es)"

    if [[ $fixes_applied -lt $issues_found ]]; then
      echo ""
      warn "Some issues require manual attention"
      echo ""
      echo "${BOLD}Next steps:${RESET}"
      echo "  • Run ${GREEN}rack maintain $id rebuild${RESET} for full rebuild"
      echo "  • Check logs: ${GREEN}rack logs $id${RESET}"
    fi
  fi

  echo ""
  dim "Tip: Run 'rack maintain $id sessions' to clean old session data"
}

_maintain_clean() {
  local id="$1"
  local workspace="$2"

  header "Clean Memory: $(meta_get "$id" "name" "$id")"
  echo ""

  local memory_dir="$workspace/memory"

  if [[ ! -d "$memory_dir" ]]; then
    warn "No memory directory found"
    return 0
  fi

  local log_count=$(find "$memory_dir" -name "*.md" -type f 2>/dev/null | wc -l)

  if [[ $log_count -eq 0 ]]; then
    success "Memory already clean (no logs found)"
    return 0
  fi

  echo "This will delete ${BOLD}$log_count${RESET} memory log file(s)"
  echo "Files: $memory_dir/*.md"
  echo ""

  read -rp "Continue? [y/N]: " confirm
  if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
    warn "Cancelled"
    return 0
  fi

  # Delete memory logs
  find "$memory_dir" -name "*.md" -type f -delete

  success "✓ Deleted $log_count memory log(s)"
  echo ""
  info "SOUL.md, AGENTS.md, TOOLS.md preserved"
  info "Agent will start with fresh memory on next interaction"
}

_maintain_reset() {
  local id="$1"
  local workspace="$2"

  header "Reset Agent: $(meta_get "$id" "name" "$id")"
  echo ""

  warn "This will clear:"
  echo "  • All memory logs (memory/*.md)"
  echo "  • MEMORY.md (architectural decisions)"
  echo "  • HEARTBEAT.md (active tasks)"
  echo ""
  echo "Preserved:"
  echo "  • SOUL.md (identity)"
  echo "  • AGENTS.md (delegation rules)"
  echo "  • TOOLS.md (commands)"
  echo "  • .rack-meta.json (metadata)"
  echo ""

  read -rp "Continue? [y/N]: " confirm
  if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
    warn "Cancelled"
    return 0
  fi

  # Clean memory logs
  if [[ -d "$workspace/memory" ]]; then
    find "$workspace/memory" -name "*.md" -type f -delete
    info "✓ Cleared memory logs"
  fi

  # Clear MEMORY.md
  if [[ -f "$workspace/MEMORY.md" ]]; then
    > "$workspace/MEMORY.md"
    info "✓ Cleared MEMORY.md"
  fi

  # Clear HEARTBEAT.md
  if [[ -f "$workspace/HEARTBEAT.md" ]]; then
    cat > "$workspace/HEARTBEAT.md" <<EOF
# Heartbeat — Active Tasks & Decisions

No active tasks.

---
*Last reset: $(date)*
EOF
    chmod 600 "$workspace/HEARTBEAT.md"
    info "✓ Reset HEARTBEAT.md"
  fi

  echo ""
  success "Agent reset complete"
  echo ""
  info "Agent will start fresh on next interaction"
  info "Identity and tools preserved"
}

_maintain_rebuild() {
  local id="$1"
  local workspace="$2"

  header "Rebuild Agent: $(meta_get "$id" "name" "$id")"
  echo ""

  error "⚠ DEEP REBUILD"
  echo ""
  warn "This will regenerate:"
  echo "  • SOUL.md"
  echo "  • AGENTS.md"
  echo "  • TOOLS.md"
  echo "  • HEARTBEAT.md"
  echo "  • All memory logs"
  echo ""
  echo "Source of truth:"
  echo "  • .rack-meta.json (preserved)"
  echo "  • openclaw.json (preserved)"
  echo ""

  read -rp "Type agent ID to confirm: " confirm_id
  if [[ "$confirm_id" != "$id" ]]; then
    error "Confirmation failed. Aborted."
    return 1
  fi

  # Backup current files
  local backup_dir="$workspace/.backup-$(date +%Y%m%d-%H%M%S)"
  mkdir -p "$backup_dir"

  for file in SOUL.md AGENTS.md TOOLS.md HEARTBEAT.md MEMORY.md; do
    [[ -f "$workspace/$file" ]] && cp "$workspace/$file" "$backup_dir/"
  done

  info "✓ Backed up to: $backup_dir"
  echo ""

  # Regenerate workspace files
  _regenerate_workspace_files "$id" "$workspace"

  # Clear memory
  if [[ -d "$workspace/memory" ]]; then
    find "$workspace/memory" -name "*.md" -type f -delete
  fi

  # Clear MEMORY.md
  [[ -f "$workspace/MEMORY.md" ]] && > "$workspace/MEMORY.md"

  echo ""
  success "Rebuild complete!"
  echo ""
  info "Backup available: $backup_dir"
  info "Agent fully regenerated from metadata"
  echo ""
  warn "Restart gateway to apply changes:"
  echo "  ${GREEN}systemctl --user restart openclaw-gateway${RESET}"
}

_maintain_sessions() {
  local id="$1"
  local workspace="$2"

  header "Clean Sessions: $(meta_get "$id" "name" "$id")"
  echo ""

  local sessions_dir="$HOME/.openclaw/agents/$id/sessions"

  if [[ ! -d "$sessions_dir" ]]; then
    warn "No sessions directory found"
    return 0
  fi

  info "Scanning for large or old sessions..."
  echo ""

  # Find large sessions (>5MB)
  local large_sessions=()
  while IFS= read -r session; do
    [[ -n "$session" ]] && large_sessions+=("$session")
  done < <(find "$sessions_dir" -name "*.jsonl" -size +5M 2>/dev/null)

  # Find old sessions (>30 days)
  local old_sessions=()
  while IFS= read -r session; do
    [[ -n "$session" ]] && old_sessions+=("$session")
  done < <(find "$sessions_dir" -name "*.jsonl" -mtime +30 2>/dev/null)

  # Combine and deduplicate
  local sessions_to_clean=()
  for session in "${large_sessions[@]}" "${old_sessions[@]}"; do
    [[ " ${sessions_to_clean[@]} " =~ " ${session} " ]] || sessions_to_clean+=("$session")
  done

  if [[ ${#sessions_to_clean[@]} -eq 0 ]]; then
    success "No sessions to clean"
    echo ""
    echo "All sessions are:"
    echo "  • Smaller than 5MB"
    echo "  • Newer than 30 days"
    return 0
  fi

  echo "Found ${BOLD}${#sessions_to_clean[@]}${RESET} session(s) to clean:"
  echo ""

  local total_size=0
  for session in "${sessions_to_clean[@]}"; do
    local size=$(stat -c%s "$session" 2>/dev/null || stat -f%z "$session" 2>/dev/null)
    local size_mb=$(echo "scale=1; $size / 1048576" | bc)
    total_size=$((total_size + size))

    echo "  • $(basename "$session") - ${size_mb}MB"
  done

  local total_mb=$(echo "scale=1; $total_size / 1048576" | bc)
  echo ""
  warn "Total: ${total_mb}MB to clean"
  echo ""

  read -rp "Archive these sessions? [Y/n]: " confirm
  if [[ "$confirm" =~ ^[Nn]$ ]]; then
    warn "Cancelled"
    return 0
  fi

  # Create archive directory
  local archive_dir="$sessions_dir/archive"
  mkdir -p "$archive_dir"

  # Move sessions to archive
  local count=0
  for session in "${sessions_to_clean[@]}"; do
    mv "$session" "$archive_dir/"
    ((count++))
  done

  success "✓ Archived $count session(s)"
  echo ""
  info "Location: $archive_dir"
  info "Space freed: ${total_mb}MB"
  echo ""
  dim "To restore: mv $archive_dir/*.jsonl $sessions_dir/"
}

# Helper: Regenerate workspace files from metadata
_regenerate_workspace_files() {
  local id="$1"
  local workspace="$2"

  info "Regenerating workspace files..."

  local name=$(meta_get "$id" "name" "$id")
  local type=$(meta_get "$id" "type" "task")
  local codebase=$(meta_get "$id" "codebase" "")
  local stack=$(meta_get "$id" "stack" "")
  local model=$(meta_get "$id" "model" "$DEFAULT_MODEL")
  local description=$(meta_get "$id" "description" "")
  local session_key=$(meta_get "$id" "sessionKey" "agent:$id:default")

  # Regenerate SOUL.md
  _create_workspace "$id" "$type" "$name" "$codebase" "$stack" "$description"

  success "  ✓ Regenerated workspace files"
}
