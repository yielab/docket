#!/usr/bin/env bash
# Command: logs

cmd_logs() {
  local id="${1:-}"
  [[ -z "$id" ]] && id=$(pick_project "View logs for")
  local workspace="$PROJECTS_DIR/$id"
  [[ ! -d "$workspace" ]] && error "Project '$id' not found."

  local name; name=$(meta_get "$id" "name" "$id")
  header "Logs: $name ($id)"

  # Show most recent memory day-log (if any)
  local latest_mem
  latest_mem=$(find "$workspace/memory" -maxdepth 1 -name '*.md' -printf '%T@ %p\n' 2>/dev/null | sort -rn | head -1 | cut -d' ' -f2-)
  if [[ -n "$latest_mem" ]]; then
    echo ""
    echo -e "${BOLD}Latest memory log:${RESET} $(basename "$latest_mem")"
    echo -e "${DIM}$(head -40 "$latest_mem")${RESET}"
    local total_lines; total_lines=$(wc -l < "$latest_mem" | tr -d ' ')
    [[ "$total_lines" -gt 40 ]] && dim "  ... ($((total_lines - 40)) more lines)"
  else
    echo ""
    dim "  No memory logs yet."
  fi

  # Show gateway log entries for this agent (if today's log exists)
  if [[ -f "$LOG_FILE" ]]; then
    local tg; tg=$(get_tg_binding "$id")
    if [[ -n "$tg" ]]; then
      local gateway_lines
      gateway_lines=$(grep -c "$tg" "$LOG_FILE" 2>/dev/null || echo "0")
      echo ""
      echo -e "${BOLD}Gateway log:${RESET} $gateway_lines entries today for group $tg"
      if [[ "$gateway_lines" -gt 0 ]]; then
        grep "$tg" "$LOG_FILE" 2>/dev/null | tail -10 | sed 's/^/  /'
        [[ "$gateway_lines" -gt 10 ]] && dim "  ... ($((gateway_lines - 10)) more entries)"
      fi
    fi
  fi
  echo ""
}

