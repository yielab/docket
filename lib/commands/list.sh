#!/usr/bin/env bash
# Command: list

cmd_list() {
  local ids; ids=$(project_ids)
  if [[ -z "$ids" ]]; then
    warn "No project agents found."
    echo "Run: rack add"
    exit 0
  fi

  local count; count=$(echo "$ids" | wc -l | tr -d ' ')

  # ── OpenClaw status bar ──
  local gw_badge tg_badge total_agents
  local gw_status; gw_status=$(service_ctl is-active 2>/dev/null) || gw_status="inactive"
  if [[ "$gw_status" == "active" ]]; then
    gw_badge="${GREEN}● gateway up${RESET}"
  else
    gw_badge="${RED}○ gateway down${RESET}"
  fi

  local tg_enabled
  tg_enabled=$(python3 -c "
import json
c = json.load(open('$CONFIG_FILE'))
print('yes' if c.get('channels',{}).get('telegram',{}).get('enabled') else 'no')
" 2>/dev/null || echo "no")
  if [[ "$tg_enabled" == "yes" ]]; then
    tg_badge="${GREEN}● telegram on${RESET}"
  else
    tg_badge="${YELLOW}○ telegram off${RESET}"
  fi

  total_agents=$(python3 -c "
import json
c = json.load(open('$CONFIG_FILE'))
print(len(c.get('agents',{}).get('list',[])))
" 2>/dev/null || echo "?")

  local bindings_count
  bindings_count=$(python3 -c "
import json
c = json.load(open('$CONFIG_FILE'))
print(len(c.get('bindings',[])))
" 2>/dev/null || echo "0")

  echo ""
  echo -e "  ${BOLD}OpenClaw${RESET}  ${gw_badge}  ${tg_badge}  ${DIM}│${RESET}  ${total_agents} agents  ${bindings_count} binding(s)  ${DIM}│${RESET}  v$(openclaw --version 2>/dev/null || echo '?')"
  echo -e "  ${DIM}$(printf '%0.s─' {1..66})${RESET}"

  echo -e "${BOLD}${CYAN}PROJECT AGENTS${RESET} ${DIM}(your work - each is dedicated to one codebase/project)${RESET} ${BOLD}($count)${RESET}"
  echo ""

  while IFS= read -r id; do
    local name;       name=$(meta_get "$id" "name" "$id")
    local type;       type=$(meta_get "$id" "type" "repo")
    local model;      model=$(meta_get "$id" "model" "$DEFAULT_MODEL")
    local stack;      stack=$(meta_get "$id" "stack" "")
    local codebase;   codebase=$(meta_get "$id" "codebase" "")
    local tg;         tg=$(get_tg_binding "$id")
    local activity;   activity=$(last_activity "$id")
    local profile;    profile=$(model_to_profile "$model")
    local workspace="$PROJECTS_DIR/$id"
    local has_memory; [[ -f "$workspace/MEMORY.md" ]] && has_memory="yes" || has_memory="no"
    local has_reqs;   [[ -f "$workspace/REQUIREMENTS.md" ]] && has_reqs="yes" || has_reqs="no"
    local mem_days;   mem_days=$(find "$workspace/memory" -maxdepth 1 -name '*.md' 2>/dev/null | wc -l | tr -d ' ')

    # ── Build status badges ──
    local badges=""

    # Registration
    if agent_registered "$id"; then
      badges+="${GREEN}● registered${RESET}  "
    else
      badges+="${RED}○ not registered${RESET}  "
    fi

    # Telegram — show group ID and expected group name
    local expected_group="${TELEGRAM_GROUP_NAMES[$id]:-}"
    if [[ -n "$tg" ]]; then
      badges+="${GREEN}● telegram${RESET} ${DIM}(${tg})${RESET}  "
    elif [[ -n "$expected_group" ]]; then
      badges+="${YELLOW}○ needs group \"${expected_group}\"${RESET}  "
    else
      badges+="${YELLOW}○ no telegram${RESET}  "
    fi

    # Memory state
    if [[ "$has_memory" == "yes" ]]; then
      badges+="${GREEN}● memory${RESET}  "
    else
      badges+="${DIM}○ no memory${RESET}  "
    fi

    # Requirements
    if [[ "$has_reqs" == "yes" ]]; then
      badges+="${GREEN}● reqs${RESET}"
    else
      badges+="${DIM}○ no reqs${RESET}"
    fi

    # ── Shorten paths for display ──
    local path_short
    if [[ -n "$codebase" ]]; then
      path_short=$(echo "$codebase" | sed "s|$HOME|~|")
    else
      path_short="${DIM}none${RESET}"
    fi

    local model_short; model_short=$(echo "$model" | sed 's|anthropic/claude-||')

    # ── Render card ──
    echo ""
    echo -e "  ${BOLD}${CYAN}$id${RESET}  ${DIM}($name)${RESET}"
    echo -e "  ${type}  │  ${model_short} (${profile})  │  stack: ${stack:-${DIM}—${RESET}}  │  ${mem_days} day-log(s)"
    echo -e "  path: ${path_short}  │  active: ${activity}"
    echo -e "  ${badges}"
  done <<< "$ids"

  # ── Telegram setup summary ──
  # Collect agents that still need Telegram groups wired
  local unwired=()
  local wired_list=()

  # Check project agents
  while IFS= read -r id; do
    local tg_check; tg_check=$(get_tg_binding "$id")
    local expected="${TELEGRAM_GROUP_NAMES[$id]:-}"
    if [[ -n "$tg_check" ]]; then
      wired_list+=("$id")
    elif [[ -n "$expected" ]]; then
      unwired+=("$id|$expected")
    fi
  done <<< "$ids"

  # Check manager (specialist agent, not in project list but needs a group)
  local mgr_tg; mgr_tg=$(get_tg_binding "manager")
  if [[ -z "$mgr_tg" ]] && [[ -n "${TELEGRAM_GROUP_NAMES[manager]:-}" ]]; then
    unwired+=("manager|${TELEGRAM_GROUP_NAMES[manager]}")
  fi

  if [[ "${#unwired[@]}" -gt 0 ]]; then
    echo ""
    echo -e "  ${DIM}$(printf '%0.s─' {1..66})${RESET}"
    echo -e "  ${BOLD}${YELLOW}Telegram Setup Needed${RESET}  ${DIM}(${#unwired[@]} agent(s) without groups)${RESET}"
    echo ""
    for entry in "${unwired[@]}"; do
      local uw_id="${entry%%|*}"
      local uw_name="${entry##*|}"
      echo -e "    ${YELLOW}○${RESET} ${BOLD}${uw_id}${RESET}  ${DIM}→ create group \"${uw_name}\" then:${RESET} rack wire ${uw_id}"
    done
    echo ""
    dim "  Steps: 1) Create Telegram group  2) Add bot  3) Get group ID from logs  4) rack wire <id>"
  fi

  # Show specialist agents section
  echo ""
  echo -e "${BOLD}${GREEN}SPECIALIST AGENTS${RESET} ${DIM}(the team - shared across all projects)${RESET}"
  echo ""
  echo -e "  ${DIM}These work across ALL your projects. Don't wire them to individual groups.${RESET}"
  echo ""

  local specialists=("manager" "programmer" "reviewer" "tester" "knowledge" "security")
  for spec in "${specialists[@]}"; do
    local spec_dir="$OPENCLAW_DIR/workspaces/$spec"
    if [[ -d "$spec_dir" ]]; then
      local spec_model=""
      if [[ -f "$spec_dir/.rack-meta.json" ]]; then
        spec_model=$(python3 -c "import json; print(json.load(open('$spec_dir/.rack-meta.json')).get('model',''))" 2>/dev/null || echo "")
      fi
      [[ -z "$spec_model" ]] && spec_model="sonnet-4-6"

      # Shorten model name for display
      local model_short="${spec_model##*/}"
      model_short="${model_short//anthropic\//}"
      model_short="${model_short//claude-/}"

      printf "  ${GREEN}✓${RESET} %-12s ${DIM}%s${RESET}\n" "$spec" "$model_short"
    fi
  done

  echo ""
  printf '%0.s─' {1..70}; echo ""
  dim "  rack info <id>     detailed view"
  dim "  rack cost          token usage"
  dim "  rack profile <id>  change model tier"
  echo ""
}

