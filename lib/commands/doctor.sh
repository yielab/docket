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
  # `|| true` so a no-match grep (exit 1) doesn't trip `set -e`/pipefail and abort
  # doctor before the later checks run. wc still prints 0 on empty input.
  brave_procs=$( { ps aux | grep "openclaw/browser" | grep -v grep | wc -l; } 2>/dev/null || true )
  brave_procs=${brave_procs:-0}
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

  # 13. API key hygiene (age since add/rotation)
  local key_report; key_report=$(_keys_age_report)
  if [[ -n "$key_report" ]]; then
    echo ""
    echo -e "${BOLD}API key hygiene:${RESET}"
    local stale_keys=0
    while IFS='|' read -r k_state k_name k_detail; do
      [[ -z "$k_name" ]] && continue
      case "$k_state" in
        STALE)
          warn "  $k_name: $k_detail — consider: rack keys rotate $k_name"
          stale_keys=$(( stale_keys + 1 ))
          ;;
        UNKNOWN)
          dim "  $k_name: $k_detail"
          ;;
        *)
          success "  $k_name: $k_detail"
          ;;
      esac
    done <<< "$key_report"
    [[ "$stale_keys" -gt 0 ]] && echo "  ${DIM}Rotate keys older than ${RACK_KEY_MAX_AGE_DAYS:-90} days${RESET}"
  fi

  # 14. Security gates (config hardening + exec-approval policy + daemon audit)
  echo ""
  echo -e "${BOLD}Security gates:${RESET}"

  # Capture the daemon audit once; it owns issue-counting for its findings when
  # available, so the config-perms check below doesn't double-count.
  local audit_out; audit_out=$(_security_audit_report)
  local audit_available=0; [[ -n "$audit_out" ]] && audit_available=1

  # G2 — config-file hardening: openclaw.json must not be group/other-accessible.
  local cfg_mode
  cfg_mode=$(stat -c '%a' "$CONFIG_FILE" 2>/dev/null || stat -f '%Lp' "$CONFIG_FILE" 2>/dev/null || echo "")
  if [[ -n "$cfg_mode" && "${cfg_mode: -2}" != "00" ]]; then
    fail "  Config group/other-accessible (mode $cfg_mode): $CONFIG_FILE"
    echo "    Another local user could change tool/auth policy. Fix: chmod 600 \"$CONFIG_FILE\""
    issues=$(( issues + 1 ))
  elif [[ -n "$cfg_mode" ]]; then
    success "  Config perms: $cfg_mode (owner-only)"
  fi

  # G1 — exec-approval policy (advisory: gates are spec'd as Planned, so an
  # inactive policy warns but does not fail the health check).
  local gate_line gs_state gs_policy gs_counts
  gate_line=$(_security_gate_report)
  IFS='|' read -r gs_state gs_policy gs_counts <<< "$gate_line"
  case "$gs_state" in
    OK)    success "  Exec approvals: $gs_policy ($gs_counts)" ;;
    OPEN)  warn "  Exec approvals: $gs_policy — host exec is ungated ($gs_counts)" ;;
    UNSET) warn "  Exec approvals: not configured — gates inactive"
           echo "    ${DIM}Enable via rack gates enable (spec: specs/functional/security-gates.spec.md)${RESET}" ;;
    *)     dim "  Exec approvals: ${gs_policy:-status unavailable}" ;;
  esac

  # G4 — approval routing (how prompts reach an approver)
  local route_line r_state r_mode
  route_line=$(_approval_routing_status)
  IFS='|' read -r r_state r_mode <<< "$route_line"
  case "$r_state" in
    on)  success "  Approval routing: on (mode=${r_mode:-?})" ;;
    off) [[ "$gs_state" == "OK" ]] && warn "  Approval routing: off — gated prompts won't reach chat" ;;
    *)   [[ "$gs_state" == "OK" ]] && dim "  Approval routing: not configured — rack gates enable" ;;
  esac

  # G1 — daemon security audit summary (config-perms finding excluded; rack owns it).
  if [[ "$audit_available" -eq 1 ]]; then
    local summary_line a_crit a_warn a_info
    summary_line=$(printf '%s\n' "$audit_out" | head -1)
    IFS='|' read -r a_crit a_warn a_info <<< "$summary_line"
    if [[ "${a_crit:-0}" -gt 0 ]]; then
      fail "  openclaw security audit: ${a_crit} critical, ${a_warn} warning(s)"
      issues=$(( issues + a_crit ))
      printf '%s\n' "$audit_out" | tail -n +2 | while IFS='|' read -r title remediation; do
        [[ -z "$title" ]] && continue
        echo "    ${RED}•${RESET} $title"
        [[ -n "$remediation" ]] && echo "      ${DIM}fix: $remediation${RESET}"
      done
      echo "    ${DIM}Remediate: openclaw security audit --fix${RESET}"
    elif [[ "${a_warn:-0}" -gt 0 ]]; then
      warn "  openclaw security audit: ${a_warn} warning(s), 0 critical"
      echo "    ${DIM}Details: openclaw security audit${RESET}"
    else
      success "  openclaw security audit: clean"
    fi
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

