#!/usr/bin/env bash
# Command: browser

cmd_browser() {
  local subcmd="${1:-status}"
  shift || true

  case "$subcmd" in
    restart)  _browser_restart ;;
    kill)     _browser_kill ;;
    status)   _browser_status ;;
    clean)    _browser_clean ;;
    *)
      header "Rack Browser — Manage OpenClaw Brave Connection"
      echo ""
      echo -e "${BOLD}Usage:${RESET}"
      echo "  ${GREEN}rack browser status${RESET}      Show browser connection status"
      echo "  ${GREEN}rack browser restart${RESET}     Restart browser (fixes disconnections)"
      echo "  ${GREEN}rack browser kill${RESET}        Force kill all browser processes"
      echo "  ${GREEN}rack browser clean${RESET}       Clean browser cache and data"
      echo ""
      echo -e "${BOLD}Common Issues:${RESET}"
      echo "  ${YELLOW}• Browser disconnects frequently${RESET}"
      echo "    → Old processes accumulate and cause memory issues"
      echo "    → Solution: ${GREEN}rack browser restart${RESET}"
      echo ""
      echo "  ${YELLOW}• Work not staying in same tab${RESET}"
      echo "    → Browser profile corrupted or session lost"
      echo "    → Solution: ${GREEN}rack browser clean${RESET} then restart gateway"
      echo ""
      echo "  ${YELLOW}• Brave shows 'Aw, Snap!' error${RESET}"
      echo "    → Shared memory exhausted"
      echo "    → Solution: ${GREEN}rack browser kill${RESET} then restart gateway"
      ;;
  esac
}

_browser_status() {
  header "Browser Status"
  echo ""

  local brave_procs
  brave_procs=$(ps aux | grep "openclaw/browser" | grep -v grep | wc -l)

  if [[ "$brave_procs" -eq 0 ]]; then
    warn "No Brave browser processes found"
    echo "  ${DIM}OpenClaw will auto-start browser when needed${RESET}"
    return 0
  fi

  success "Found $brave_procs Brave processes"
  echo ""

  # Check extension connection status
  echo -e "${BOLD}Extension Connection:${RESET}"
  local tab_error_count
  tab_error_count=$(grep -c "no tab is connected" "/tmp/openclaw/openclaw-$(date +%Y-%m-%d).log" 2>/dev/null || echo "0")

  if [[ "$tab_error_count" -gt 0 ]]; then
    echo -e "  ${RED}✗ No tab connected${RESET} ${DIM}(${tab_error_count} error(s) today)${RESET}"
    echo ""
    echo -e "  ${YELLOW}${BOLD}ACTION REQUIRED:${RESET}"
    echo -e "  ${YELLOW}1.${RESET} Open Brave browser"
    echo -e "  ${YELLOW}2.${RESET} Open or navigate to any tab"
    echo -e "  ${YELLOW}3.${RESET} Click the ${CYAN}OpenClaw Browser Relay${RESET} extension icon"
    echo -e "  ${YELLOW}4.${RESET} Icon should change to show 'Connected'"
    echo ""
    echo -e "  ${DIM}Extension icon location: top-right corner of Brave${RESET}"
    echo -e "  ${DIM}If not visible: Click puzzle piece icon → Pin OpenClaw extension${RESET}"
    echo ""
  else
    echo -e "  ${GREEN}✓${RESET} Extension appears to be connected"
    echo -e "    ${DIM}(or hasn't been used yet today)${RESET}"
  fi
  echo ""

  # Show process ages
  echo -e "${BOLD}Process Ages:${RESET}"
  local process_list
  process_list=$(ps -eo pid,etimes,cmd 2>/dev/null | grep "openclaw/browser" | grep -v grep || true)

  if [[ -z "$process_list" ]]; then
    echo -e "  ${DIM}No browser processes running${RESET}"
  else
    while read pid elapsed cmd; do
      local days=$(( elapsed / 86400 ))
      local hours=$(( (elapsed % 86400) / 3600 ))
      local mins=$(( (elapsed % 3600) / 60 ))

      local age_str=""
      [[ $days -gt 0 ]] && age_str="${days}d "
      [[ $hours -gt 0 ]] && age_str="${age_str}${hours}h "
      age_str="${age_str}${mins}m"

      if [[ $days -gt 2 ]]; then
        echo -e "  ${RED}PID $pid${RESET}: ${age_str} ${DIM}(too old - restart recommended)${RESET}"
      elif [[ $days -gt 0 ]]; then
        echo -e "  ${YELLOW}PID $pid${RESET}: ${age_str}"
      else
        echo -e "  ${GREEN}PID $pid${RESET}: ${age_str}"
      fi
    done <<< "$process_list"
  fi

  # Check memory usage
  echo ""
  echo -e "${BOLD}Memory Usage:${RESET}"
  local total_mem
  total_mem=$(ps aux | grep "openclaw/browser" | grep -v grep | awk '{sum+=$6} END {print sum/1024}')
  echo -e "  ${CYAN}Total: ${total_mem} MB${RESET}"

  # Show remote debugging port
  echo ""
  echo -e "${BOLD}Remote Debugging:${RESET}"
  if ps aux | grep -q "remote-debugging-port=18800"; then
    success "  Listening on port 18800"
  else
    warn "  Port not found (may cause connection issues)"
  fi

  # Check for disconnection patterns in logs
  if [[ -f "$LOG_FILE" ]]; then
    local disconnect_count
    disconnect_count=$(grep -ci "disconnect\|timeout\|connection.*closed" "$LOG_FILE" 2>/dev/null || echo "0")
    if [[ "$disconnect_count" -gt 10 ]]; then
      echo ""
      warn "Found $disconnect_count disconnect events in today's log"
      echo "  ${DIM}Recommendation: ${RESET}${YELLOW}rack browser restart${RESET}"
    fi
  fi
}

_browser_restart() {
  header "Restarting Browser"
  echo ""

  # First show current status
  local brave_procs
  brave_procs=$(ps aux | grep "openclaw/browser" | grep -v grep | wc -l)

  if [[ "$brave_procs" -eq 0 ]]; then
    warn "No browser processes to restart"
    echo "  ${DIM}OpenClaw will auto-start when needed${RESET}"
    return 0
  fi

  echo -e "${BOLD}Step 1: Killing existing processes${RESET}"
  _browser_kill

  echo ""
  echo -e "${BOLD}Step 2: Restarting OpenClaw gateway${RESET}"
  restart_gateway

  echo ""
  success "Browser restart complete"
  echo "  ${DIM}Browser will auto-start on next OpenClaw web request${RESET}"
}

_browser_kill() {
  local pids
  pids=$(ps aux | grep "openclaw/browser" | grep -v grep | awk '{print $2}')

  if [[ -z "$pids" ]]; then
    warn "No browser processes found"
    return 0
  fi

  local count=0
  while IFS= read -r pid; do
    echo "  Killing PID $pid..."
    kill -9 "$pid" 2>/dev/null || true
    count=$((count + 1))
  done <<< "$pids"

  sleep 1
  success "Killed $count browser process(es)"
}

_browser_clean() {
  header "Cleaning Browser Data"
  echo ""

  local browser_dir="$HOME/.openclaw/browser/openclaw"

  if [[ ! -d "$browser_dir" ]]; then
    warn "Browser data directory not found: $browser_dir"
    return 0
  fi

  # Check if browser is running
  local brave_procs
  brave_procs=$(ps aux | grep "openclaw/browser" | grep -v grep | wc -l)

  if [[ "$brave_procs" -gt 0 ]]; then
    echo -e "${YELLOW}Browser is currently running${RESET}"
    echo "  Must kill processes first..."
    echo ""
    _browser_kill
    echo ""
  fi

  # Show current size
  local size_before
  size_before=$(du -sh "$browser_dir" 2>/dev/null | awk '{print $1}')
  echo "  Current size: ${CYAN}$size_before${RESET}"
  echo ""

  # Clean specific directories
  echo -e "${BOLD}Cleaning cache and temporary data...${RESET}"

  local cleaned=0

  # Cache
  if [[ -d "$browser_dir/user-data/Default/Cache" ]]; then
    rm -rf "$browser_dir/user-data/Default/Cache"/*
    echo "  ✓ Cleared cache"
    cleaned=1
  fi

  # Code Cache
  if [[ -d "$browser_dir/user-data/Default/Code Cache" ]]; then
    rm -rf "$browser_dir/user-data/Default/Code Cache"/*
    echo "  ✓ Cleared code cache"
    cleaned=1
  fi

  # Service Worker Cache
  if [[ -d "$browser_dir/user-data/Default/Service Worker" ]]; then
    rm -rf "$browser_dir/user-data/Default/Service Worker"/*
    echo "  ✓ Cleared service worker cache"
    cleaned=1
  fi

  # GPUCache
  if [[ -d "$browser_dir/user-data/Default/GPUCache" ]]; then
    rm -rf "$browser_dir/user-data/Default/GPUCache"/*
    echo "  ✓ Cleared GPU cache"
    cleaned=1
  fi

  # Session files (can cause tab persistence issues)
  if [[ -f "$browser_dir/user-data/Default/Current Session" ]]; then
    rm -f "$browser_dir/user-data/Default/Current Session"
    rm -f "$browser_dir/user-data/Default/Current Tabs"
    echo "  ✓ Cleared session data (fixes tab persistence)"
    cleaned=1
  fi

  if [[ "$cleaned" -eq 1 ]]; then
    local size_after
    size_after=$(du -sh "$browser_dir" 2>/dev/null | awk '{print $1}')
    echo ""
    success "Browser data cleaned"
    echo "  New size: ${CYAN}$size_after${RESET}"
    echo ""
    echo -e "${YELLOW}Next step: ${RESET}${GREEN}$(service_hint restart)${RESET}"
  else
    warn "Nothing to clean (or directory structure unexpected)"
  fi
}
