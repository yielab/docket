#!/usr/bin/env bash
# Command: info

# Machine-readable single-agent detail (docket info <id> --json).
_info_json() {
  local id="$1"
  local workspace="$PROJECTS_DIR/$id"
  [[ -d "$workspace" ]] || error "Project '$id' not found."
  local registered="false"; agent_registered "$id" && registered="true"
  local tg; tg=$(get_tg_binding "$id")
  local activity; activity=$(last_activity "$id")
  python3 - "$workspace/$META_FILE" "$id" "$registered" "$tg" "$activity" "$DEFAULT_MODEL" <<'PY'
import json, sys
meta_path, aid, registered, tg, activity, default_model = sys.argv[1:7]
try:
    meta = json.load(open(meta_path))
except Exception:
    meta = {}
print(json.dumps({
    "id": aid,
    "name": meta.get("name", aid),
    "type": meta.get("type", "repo"),
    "codebase": meta.get("codebase", ""),
    "stack": meta.get("stack", ""),
    "model": meta.get("model", default_model),
    "budgetUsd": meta.get("budgetUsd", ""),
    "paused": meta.get("paused", "") == "true",
    "sessionKey": meta.get("sessionKey", f"agent:{aid}:default"),
    "projectKey": meta.get("projectKey", "default"),
    "registered": registered == "true",
    "telegram": tg or None,
    "lastActive": activity,
}, indent=2))
PY
}

cmd_info() {
  local id="" json=0 a
  for a in "$@"; do
    case "$a" in
      --json) json=1 ;;
      *) [[ -z "$id" ]] && id="$a" ;;
    esac
  done
  [[ -z "$id" && "$json" -eq 0 ]] && id=$(pick_project "Inspect project")
  [[ -z "$id" ]] && error "An agent id is required (e.g. docket info <id> --json)."

  if [[ "$json" -eq 1 ]]; then
    _info_json "$id"
    return 0
  fi

  local workspace="$PROJECTS_DIR/$id"
  [[ ! -d "$workspace" ]] && error "Project '$id' not found."

  local type;       type=$(meta_get "$id" "type" "repo")
  local name;       name=$(meta_get "$id" "name" "$id")
  local codebase;   codebase=$(meta_get "$id" "codebase" "—")
  local stack;      stack=$(meta_get "$id" "stack" "—")
  local model;      model=$(meta_get "$id" "model" "$DEFAULT_MODEL")
  local budget;     budget=$(meta_get "$id" "budgetUsd" "")
  local paused;     paused=$(meta_get "$id" "paused" "")
  local paused_reason; paused_reason=$(meta_get "$id" "pausedReason" "")
  local tg;         tg=$(get_tg_binding "$id")
  local activity;   activity=$(last_activity "$id")
  local mem_count;  mem_count=$(find "$workspace/memory" -maxdepth 1 -name '*.md' 2>/dev/null | wc -l | tr -d ' ')
  local has_memory; [[ -f "$workspace/MEMORY.md" ]] && has_memory="yes" || has_memory="no"
  local has_reqs;   [[ -f "$workspace/REQUIREMENTS.md" ]] && has_reqs="yes" || has_reqs="no"

  header "Project: $name ($id)"
  echo ""
  printf "  ${BOLD}%-18s${RESET} %s\n" "Type:"        "$type"
  printf "  ${BOLD}%-18s${RESET} %s\n" "Workspace:"   "$workspace"
  printf "  ${BOLD}%-18s${RESET} %s\n" "Codebase:"    "$codebase"
  printf "  ${BOLD}%-18s${RESET} %s\n" "Stack:"       "$stack"
  printf "  ${BOLD}%-18s${RESET} %s\n" "Model:"       "$model"
  if [[ -n "$budget" && "$budget" != "0" ]]; then
    printf "  ${BOLD}%-18s${RESET} \$%.2f\n" "Budget cap:"  "$budget"
  fi
  if [[ "$paused" == "true" ]]; then
    printf "  ${BOLD}%-18s${RESET} ${RED}PAUSED${RESET}%s\n" "Status:" "${paused_reason:+ (${paused_reason})}"
  fi

  local session_key; session_key=$(meta_get "$id" "sessionKey" "agent:${id}:default")
  local project_key; project_key=$(meta_get "$id" "projectKey" "default")
  printf "  ${BOLD}%-18s${RESET} %s\n" "Session Key:"  "$session_key"
  printf "  ${BOLD}%-18s${RESET} %s\n" "Project Scope:" "$project_key"
  echo ""
  printf "  ${BOLD}%-18s${RESET} %s\n" "Registered:"  "$(agent_registered "$id" && echo "${GREEN}yes${RESET}" || echo "${RED}no${RESET}")"
  local expected_group="${TELEGRAM_GROUP_NAMES[$id]:-}"
  local tg_display
  if [[ -n "$tg" ]]; then
    tg_display="${GREEN}${tg}${RESET}"
    [[ -n "$expected_group" ]] && tg_display+=" ${DIM}(${expected_group})${RESET}"
  elif [[ -n "$expected_group" ]]; then
    tg_display="${YELLOW}not wired${RESET} ${DIM}→ create group \"${expected_group}\"${RESET}"
  else
    tg_display="${YELLOW}not wired${RESET}"
  fi
  printf "  ${BOLD}%-18s${RESET} %s\n" "Telegram:"    "$tg_display"
  printf "  ${BOLD}%-18s${RESET} %s\n" "Last active:" "$activity"
  printf "  ${BOLD}%-18s${RESET} %s\n" "Memory days:" "$mem_count"
  printf "  ${BOLD}%-18s${RESET} %s\n" "MEMORY.md:"   "$has_memory"
  printf "  ${BOLD}%-18s${RESET} %s\n" "REQUIREMENTS:" "$has_reqs"

  echo ""
  header "Workspace files"
  find "$workspace" -maxdepth 1 -type f | sort | while read -r f; do
    local size; size=$(wc -l < "$f" 2>/dev/null || echo "?")
    printf "  %-30s %s lines\n" "$(basename "$f")" "$size"
  done

  if [[ -n "$tg" && "$type" == "repo" && -n "$codebase" ]]; then
    echo ""
    header "First-run prompt (send in Telegram group if MEMORY.md is missing)"
    echo ""
    echo "  Read the codebase at $codebase and update your"
    echo "  SOUL.md and MEMORY.md with: tech stack, entry points,"
    echo "  architecture, current state, recent git activity."
    echo ""
  fi
}

