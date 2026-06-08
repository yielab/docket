#!/usr/bin/env bash
# Command: doctor

cmd_doctor() {
  header "Rack Doctor — System Health Check"
  echo ""
  local issues=0

  # 1. openclaw binary
  if command -v openclaw &>/dev/null; then
    success "openclaw: $(command -v openclaw)"
    dbg "openclaw version: $(openclaw --version 2>/dev/null || echo 'n/a')"
  else
    fail "openclaw not found in PATH"
    echo "  Install from: https://openclaw.dev"
    issues=$(( issues + 1 ))
  fi

  # 2. python3
  if command -v python3 &>/dev/null; then
    success "python3: $(command -v python3)"
  else
    fail "python3 not found — required for JSON operations"
    issues=$(( issues + 1 ))
  fi

  # 3. fzf (optional)
  if command -v fzf &>/dev/null; then
    success "fzf: $(command -v fzf)"
  else
    warn "fzf not installed — interactive pickers will use numbered fallback"
    echo "  Install with: brew install fzf"
  fi

  # 4. Config file
  if [[ ! -f "$CONFIG_FILE" ]]; then
    fail "Config missing: $CONFIG_FILE"
    echo "  Run: openclaw onboard"
    issues=$(( issues + 1 ))
  elif python3 -c "import json; json.load(open('$CONFIG_FILE'))" 2>/dev/null; then
    success "Config JSON valid: $CONFIG_FILE"
    dbg "Agents in config: $(python3 -c "import json; c=json.load(open('$CONFIG_FILE')); print(len(c.get('agents',{}).get('list',[])))" 2>/dev/null)"
    dbg "Bindings in config: $(python3 -c "import json; c=json.load(open('$CONFIG_FILE')); print(len(c.get('bindings',[])))" 2>/dev/null)"
  else
    fail "Config JSON is invalid: $CONFIG_FILE"
    echo "  Run: openclaw doctor"
    issues=$(( issues + 1 ))
  fi

  # 5. Gateway service
  local svc_status="unknown"
  svc_status=$(systemctl --user is-active openclaw-gateway.service 2>/dev/null) || true
  if [[ "$svc_status" == "active" ]]; then
    success "Gateway service: active"
    if [[ "$DEBUG" == "1" ]]; then
      systemctl --user status openclaw-gateway.service --no-pager -l 2>/dev/null \
        | head -12 | sed 's/^/  /'
    fi
  else
    fail "Gateway service: $svc_status"
    echo "  Run: systemctl --user start openclaw-gateway.service"
    issues=$(( issues + 1 ))
  fi

  # 6. Telegram channel
  if [[ -f "$CONFIG_FILE" ]]; then
    local tg_enabled
    tg_enabled=$(python3 -c "
import json
c = json.load(open('$CONFIG_FILE'))
print('yes' if c.get('channels',{}).get('telegram',{}).get('enabled') else 'no')
" 2>/dev/null || echo "unknown")
    if [[ "$tg_enabled" == "yes" ]]; then
      success "Telegram channel: enabled"
    else
      warn "Telegram channel: disabled or not configured"
      echo "  Run: openclaw onboard  (to configure Telegram)"
    fi
  fi

  # 7. Per-project checks
  local ids; ids=$(project_ids)
  if [[ -z "$ids" ]]; then
    echo ""
    warn "No project agents found — run: rack add"
  else
    echo ""
    echo -e "${BOLD}Project agents:${RESET}"
    while IFS= read -r id; do
      local proj_issues=()
      local tg; tg=$(get_tg_binding "$id")

      for f in SOUL.md AGENTS.md TOOLS.md HEARTBEAT.md; do
        [[ ! -f "$PROJECTS_DIR/$id/$f" ]] && proj_issues+=("missing $f")
      done
      [[ ! -f "$PROJECTS_DIR/$id/$META_FILE" ]] && proj_issues+=("no $META_FILE")

      if ! openclaw agents list 2>/dev/null | grep -q "^- ${id}$"; then
        proj_issues+=("not registered in openclaw")
      fi

      if [[ "${#proj_issues[@]}" -gt 0 ]]; then
        fail "  $id: ${proj_issues[*]}"
        echo "    Fix with: rack repair $id"
        issues=$(( issues + 1 ))
      elif [[ -z "$tg" ]]; then
        warn "  $id: OK, no Telegram binding  →  rack wire $id"
      else
        success "  $id: OK  →  group $tg"
      fi
    done <<< "$ids"
  fi

  # 8. Brave browser connection (for OpenClaw web UI)
  echo ""
  local brave_procs
  brave_procs=$(ps aux | grep "openclaw/browser" | grep -v grep | wc -l)
  if [[ "$brave_procs" -gt 0 ]]; then
    # Check if processes are stale (older than 3 days)
    local oldest_brave
    oldest_brave=$(ps -eo pid,etimes,cmd | grep "openclaw/browser" | grep -v grep | awk '{print $2}' | sort -n | tail -1)
    local days_old=$(( oldest_brave / 86400 ))

    if [[ "$days_old" -gt 2 ]]; then
      warn "Brave browser: $brave_procs processes (oldest: ${days_old} days old)"
      echo "  ${DIM}Old browser processes can cause disconnections${RESET}"
      echo "  ${YELLOW}Fix: RACK_EXPERIMENTAL=1 rack browser restart${RESET}"
    else
      success "Brave browser: $brave_procs processes running"
    fi
  else
    dim "  Brave browser: not running (OpenClaw will auto-start when needed)"
  fi

  # 9. Today's log
  echo ""
  if [[ -f "$LOG_FILE" ]]; then
    local lines; lines=$(wc -l < "$LOG_FILE" | tr -d ' ')
    success "Today's log: $LOG_FILE ($lines lines)"

    # Check for disconnection patterns
    if grep -qi "disconnect\|timeout\|connection.*closed" "$LOG_FILE" 2>/dev/null; then
      local disconnect_count
      disconnect_count=$(grep -ci "disconnect\|timeout\|connection.*closed" "$LOG_FILE" 2>/dev/null)
      warn "  Found $disconnect_count disconnect/timeout events in log"
      echo "  ${DIM}If Brave disconnects frequently, run: ${RESET}${YELLOW}RACK_EXPERIMENTAL=1 rack browser restart${RESET}"
    fi

    if [[ "$DEBUG" == "1" && "$lines" -gt 0 ]]; then
      echo ""
      echo -e "${DIM}Last 5 log lines:${RESET}"
      tail -5 "$LOG_FILE" 2>/dev/null | sed 's/^/  /'
    fi
  else
    dim "  No log today: $LOG_FILE"
    dim "  (Normal if the gateway hasn't received messages yet)"
  fi

  # 10. Check for invalid model names
  echo ""
  echo -e "${BOLD}Model Configuration${RESET}"
  local invalid_models
  invalid_models=$(python3 << 'PYEOF'
import json, os
config_path = os.path.expanduser('~/.openclaw/openclaw.json')
with open(config_path, 'r') as f:
    config = json.load(f)

invalid = []
aliases = {
    'anthropic/claude-haiku-3-5': 'anthropic/claude-haiku-4-5',
    'anthropic/claude-haiku-3': 'anthropic/claude-haiku-4-5',
    'anthropic/claude-sonnet-3-5': 'anthropic/claude-sonnet-4-6',
}

# Check all agents
for agent in config.get('agents', {}).get('list', []):
    if 'model' in agent and agent['model'] in aliases:
        invalid.append(f"{agent.get('id')}: {agent['model']}")

for line in invalid:
    print(line)
PYEOF
)

  if [[ -z "$invalid_models" ]]; then
    success "  All agent models are valid"
  else
    fail "  Found invalid model configurations:"
    echo "$invalid_models" | sed 's/^/    /'
    echo "  ${YELLOW}Fix with: rack doctor --fix${RESET}"
    issues=$(( issues + 1 ))
  fi

  # 11. Config drift detection (meta vs openclaw.json)
  # Run as a single Python call over all project agents to avoid heredoc-in-loop warnings.
  local drift_ids; drift_ids=$(project_ids)
  if [[ -n "$drift_ids" ]]; then
    echo ""
    echo -e "${BOLD}Config drift check (meta ↔ openclaw.json):${RESET}"

    local _drift_script
    _drift_script=$(cat <<'PYEOF'
import json, sys, os

config_path  = sys.argv[1]
projects_dir = sys.argv[2]
meta_file    = sys.argv[3]
agent_ids    = sys.argv[4:]

config = json.load(open(config_path))
oc_agents = {a.get('id'): a for a in config.get('agents', {}).get('list', [])}

drift = []
ok    = []
for aid in agent_ids:
    meta_path = os.path.join(projects_dir, aid, meta_file)
    if not os.path.exists(meta_path):
        continue
    meta_model = json.load(open(meta_path)).get('model', '')
    if not meta_model:
        continue
    oc_model = oc_agents.get(aid, {}).get('model', '')
    if oc_model and meta_model != oc_model:
        drift.append(f"DRIFT {aid} meta={meta_model} openclaw={oc_model}")
    else:
        ok.append(f"OK {aid}")

for line in ok:
    print(line)
for line in drift:
    print(line)
PYEOF
)

    local _drift_results
    _drift_results=$(python3 -c "$_drift_script" \
      "$CONFIG_FILE" "$PROJECTS_DIR" "$META_FILE" $drift_ids 2>/dev/null || true)

    local drift_found=0
    while IFS= read -r line; do
      [[ -z "$line" ]] && continue
      local _id="${line#* }"; _id="${_id%% *}"
      if [[ "$line" == DRIFT* ]]; then
        local _meta="${line##*meta=}"; _meta="${_meta%% *}"
        local _oc="${line##*openclaw=}"
        fail "  $_id: drift — model meta=${_meta} openclaw=${_oc}"
        issues=$(( issues + 1 ))
        drift_found=$(( drift_found + 1 ))
      else
        success "  $_id: in sync"
      fi
    done <<< "$_drift_results"

    if [[ "$drift_found" -gt 0 ]]; then
      echo "  Fix with: rack doctor --fix"
    fi
  fi

  # 12. Budget and runaway session check
  local budget_ids; budget_ids=$(project_ids)
  if [[ -n "$budget_ids" ]]; then
    echo ""
    echo -e "${BOLD}Budget check:${RESET}"
    while IFS= read -r bid; do
      local b_budget; b_budget=$(meta_get "$bid" "budgetUsd" "")
      if [[ -z "$b_budget" || "$b_budget" == "0" ]]; then
        dim "  $bid: no cap"
        continue
      fi
      local b_data; b_data=$(_aggregate_cost "$bid")
      local b_cost b_turns
      IFS='|' read -r _ _ _ _ b_cost b_turns <<< "$b_data"
      local b_pct
      b_pct=$(python3 -c "print(int(float('$b_cost') / float('$b_budget') * 100))" 2>/dev/null || echo "0")
      if [[ "$b_pct" -ge 100 ]]; then
        fail "  $bid: over budget — ${b_pct}% of \$$b_budget (\$$b_cost used)"
        issues=$(( issues + 1 ))
      elif [[ "$b_pct" -ge 80 ]]; then
        warn "  $bid: ${b_pct}% of \$$b_budget (\$$b_cost used)"
      else
        success "  $bid: \$$b_cost / \$$b_budget (${b_pct}%)"
      fi
    done <<< "$budget_ids"

    echo ""
    echo -e "${BOLD}Runaway session check:${RESET}"
    while IFS= read -r rid; do
      local r_data; r_data=$(_aggregate_cost "$rid")
      local r_cost r_turns
      IFS='|' read -r _ _ _ _ r_cost r_turns <<< "$r_data"
      local r_flag=0
      [[ "$r_turns" -gt "${RUNAWAY_TURNS_THRESHOLD:-200}" ]] && r_flag=1
      python3 -c "import sys; sys.exit(0 if float('$r_cost') >= ${RUNAWAY_COST_THRESHOLD:-20} else 1)" \
        2>/dev/null && r_flag=1
      if [[ "$r_flag" -eq 1 ]]; then
        fail "  $rid: runaway — $r_turns turns, \$$r_cost"
        issues=$(( issues + 1 ))
      else
        success "  $rid: ok ($r_turns turns, \$$r_cost)"
      fi
    done <<< "$budget_ids"
  fi

  # Summary
  echo ""
  if [[ "$issues" -eq 0 ]]; then
    success "All checks passed — rack is healthy."
  else
    echo -e "${RED}${BOLD}${issues} critical issue(s) found.${RESET}"
    echo "  Project issues:  rack repair [id]"
    echo "  Gateway issues:  openclaw doctor"
    echo "  Model issues:    rack doctor --fix"
    exit 1
  fi
}

