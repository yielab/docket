#!/usr/bin/env bash
# Command: context - Unified context & memory management (replaces logs + memory)

cmd_context() {
  local id="${1:-}"
  local subcmd="${2:-show}"
  shift 2 2>/dev/null || shift 1 2>/dev/null || true

  # Interactive picker if no ID
  [[ -z "$id" ]] && id=$(pick_project "Select agent")

  local workspace="$PROJECTS_DIR/$id"
  [[ ! -d "$workspace" ]] && error "Agent '$id' not found"

  case "$subcmd" in
    show)
      _context_show "$id" "$workspace"
      ;;
    search)
      _context_search "$id" "$workspace" "$@"
      ;;
    snapshot)
      _context_snapshot "$id" "$workspace"
      ;;
    index)
      _context_index "$id" "$workspace"
      ;;
    compress)
      _context_compress "$id" "$workspace"
      ;;
    *)
      # If subcmd looks like a search query, treat as search
      if [[ -n "$subcmd" && "$subcmd" != "-"* ]]; then
        _context_search "$id" "$workspace" "$subcmd" "$@"
      else
        _context_show "$id" "$workspace"
      fi
      ;;
  esac
}

_context_show() {
  local id="$1"
  local workspace="$2"

  header "Context: $(meta_get "$id" "name" "$id")"
  echo ""

  # Show recent memory logs
  echo "${BOLD}Recent Activity${RESET}"
  echo "────────────────────────────────────────────────────────────"

  local memory_dir="$workspace/memory"
  if [[ -d "$memory_dir" ]]; then
    local recent_logs=$(find "$memory_dir" -name "*.md" -type f | sort -r | head -3)

    if [[ -z "$recent_logs" ]]; then
      dim "  No activity logs found"
    else
      while IFS= read -r log_file; do
        local date=$(basename "$log_file" .md)
        echo ""
        echo "${CYAN}$date${RESET}"
        tail -10 "$log_file" | head -5
      done <<< "$recent_logs"
    fi
  else
    dim "  No memory directory"
  fi

  echo ""
  echo ""

  # Show active tasks from HEARTBEAT
  if [[ -f "$workspace/HEARTBEAT.md" ]]; then
    echo "${BOLD}Active Tasks${RESET}"
    echo "────────────────────────────────────────────────────────────"
    local tasks=$(grep -E "^- \[" "$workspace/HEARTBEAT.md" | head -5)

    if [[ -n "$tasks" ]]; then
      echo "$tasks"
    else
      dim "  No active tasks"
    fi
  fi

  echo ""
  echo ""

  # Show gateway logs for this agent
  echo "${BOLD}Gateway Activity${RESET}"
  echo "────────────────────────────────────────────────────────────"

  local log_file="/tmp/openclaw/openclaw-$(date +%Y-%m-%d).log"
  if [[ -f "$log_file" ]]; then
    local agent_logs=$(grep "$id" "$log_file" 2>/dev/null | tail -5)

    if [[ -n "$agent_logs" ]]; then
      echo "$agent_logs" | cut -c1-100
    else
      dim "  No recent gateway activity"
    fi
  else
    dim "  No gateway log for today"
  fi

  echo ""
  echo ""

  # Quick stats
  echo "${BOLD}Context Statistics${RESET}"
  echo "────────────────────────────────────────────────────────────"

  local log_count=0
  [[ -d "$memory_dir" ]] && log_count=$(find "$memory_dir" -name "*.md" -type f | wc -l)

  local session_file="$HOME/.openclaw/agents/$id/sessions/$(ls -t "$HOME/.openclaw/agents/$id/sessions/" 2>/dev/null | head -1)"
  local session_size=0

  if [[ -f "$session_file" ]]; then
    session_size=$(stat -c%s "$session_file" 2>/dev/null || stat -f%z "$session_file" 2>/dev/null || echo 0)
  fi

  local size_mb=$(echo "scale=1; $session_size / 1048576" | bc 2>/dev/null || echo "0.0")

  echo "  Memory logs: $log_count"
  echo "  Session size: ${size_mb}MB"
  echo "  Last activity: $(last_activity "$id")"

  echo ""
  echo ""

  echo "${BOLD}Quick Actions${RESET}"
  echo "────────────────────────────────────────────────────────────"
  echo "  Search memory:    ${GREEN}rack context $id search <query>${RESET}"
  echo "  Create snapshot:  ${GREEN}rack context $id snapshot${RESET}"
  echo "  Index memory:     ${GREEN}rack context $id index${RESET}"
  echo "  Compress old:     ${GREEN}rack context $id compress${RESET}"
}

_context_search() {
  local id="$1"
  local workspace="$2"
  local query="$*"

  [[ -z "$query" ]] && error "Search query required"

  header "Search Context: $query"
  echo ""

  # Delegate to memory command for now
  cmd_memory "$id" search "$query"
}

_context_snapshot() {
  local id="$1"
  local workspace="$2"

  # Delegate to memory command
  cmd_memory "$id" snapshot
}

_context_index() {
  local id="$1"
  local workspace="$2"

  # Delegate to memory command
  cmd_memory "$id" index
}

_context_compress() {
  local id="$1"
  local workspace="$2"

  # Delegate to memory command
  cmd_memory "$id" compress
}
