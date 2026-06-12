#!/usr/bin/env bash
# Command: list

# Single Python pass: all project-agent metas + config header stats + TG bindings.
# Outputs a HEADER line then one AGENT line per agent (TAB-separated).
# Called once per cmd_list invocation instead of 7N separate Python spawns.
# shellcheck disable=SC2120
_list_meta_batch() {
  python3 - "$PROJECTS_DIR" "$CONFIG_FILE" "$DEFAULT_MODEL" "$META_FILE" "$@" <<'PY'
import json, os, sys
projects_dir, config_file, default_model, meta_file = sys.argv[1:5]
agent_ids = sys.argv[5:]
try:
    cfg = json.load(open(config_file))
except Exception:
    cfg = {}
registered_set = {a.get("id") for a in cfg.get("agents", {}).get("list", [])}
total_agents   = len(cfg.get("agents", {}).get("list", []))
bindings_count = len(cfg.get("bindings", []))
tg_enabled     = "yes" if cfg.get("channels", {}).get("telegram", {}).get("enabled") else "no"
tg_map = {}
for b in cfg.get("bindings", []):
    m = b.get("match", {}) or {}
    if m.get("channel") == "telegram":
        tg_map[b.get("agentId")] = str((m.get("peer", {}) or {}).get("id", ""))
print(f"HEADER\t{total_agents}\t{bindings_count}\t{tg_enabled}")
def safe(v): return str(v).replace("\t", " ")
for aid in agent_ids:
    meta_path = os.path.join(projects_dir, aid, meta_file)
    try:    meta = json.load(open(meta_path))
    except: meta = {}
    print("\t".join([
        "AGENT", safe(aid),
        safe(meta.get("name", aid)),
        safe(meta.get("type", "repo")),
        safe(meta.get("model", default_model)),
        safe(meta.get("stack", "")),
        safe(meta.get("codebase", "")),
        tg_map.get(aid, ""),
        "1" if aid in registered_set else "0",
        safe(meta.get("modelSource", "")),
    ]))
PY
}

# Single Python pass for all specialist-agent models.
# Outputs SPEC\t<id>\t<model>\t<modelSource> or ABSENT\t<id>.
_list_spec_batch() {
  python3 - "$OPENCLAW_DIR" "$DEFAULT_MODEL" "$@" <<'PY'
import json, os, sys
openclaw_dir, default_model = sys.argv[1], sys.argv[2]
for spec in sys.argv[3:]:
    spec_dir = os.path.join(openclaw_dir, "workspaces", spec)
    if not os.path.isdir(spec_dir):
        print(f"ABSENT\t{spec}")
        continue
    try:    meta = json.load(open(os.path.join(spec_dir, ".rack-meta.json")))
    except: meta = {}
    model = meta.get("model") or default_model
    print(f"SPEC\t{spec}\t{model}\t{meta.get('modelSource', '')}")
PY
}

# Machine-readable agent inventory (rack list --json). A single Python pass over
# all project metas + the daemon config — stable output for scripting/CI, and it
# also avoids the per-field interpreter spawns the human view does.
_list_json() {
  python3 - "$PROJECTS_DIR" "$CONFIG_FILE" "$DEFAULT_MODEL" "$META_FILE" <<'PY'
import json, os, sys
projects_dir, config_file, default_model, meta_file = sys.argv[1:5]
try:
    cfg = json.load(open(config_file))
except Exception:
    cfg = {}
registered = {a.get("id") for a in cfg.get("agents", {}).get("list", [])}
bindings = {}
for b in cfg.get("bindings", []):
    m = b.get("match", {}) or {}
    if m.get("channel") == "telegram":
        bindings[b.get("agentId")] = (m.get("peer", {}) or {}).get("id")
agents = []
if os.path.isdir(projects_dir):
    for aid in sorted(os.listdir(projects_dir)):
        meta_path = os.path.join(projects_dir, aid, meta_file)
        if not os.path.isfile(meta_path):
            continue
        try:
            meta = json.load(open(meta_path))
        except Exception:
            meta = {}
        agents.append({
            "id": aid,
            "kind": meta.get("kind", "project"),
            "name": meta.get("name", aid),
            "type": meta.get("type", "repo"),
            "model": meta.get("model", default_model),
            "modelSource": meta.get("modelSource", ""),
            "stack": meta.get("stack", ""),
            "codebase": meta.get("codebase", ""),
            "budgetUsd": meta.get("budgetUsd", ""),
            "telegram": bindings.get(aid),
            "registered": aid in registered,
        })
print(json.dumps({"agents": agents}, indent=2))
PY
}

cmd_list() {
  if [[ "${1:-}" == "--json" ]]; then
    _list_json
    return 0
  fi

  local ids; ids=$(project_ids)
  if [[ -z "$ids" ]]; then
    warn "No project agents found."
    echo "Run: rack add"
    exit 0
  fi

  local count; count=$(echo "$ids" | wc -l | tr -d ' ')

  # ── One Python pass: all agent metas + config stats + TG bindings ──
  # shellcheck disable=SC2086
  local _batch_out; _batch_out=$(_list_meta_batch $ids)

  local _hdr_agents="?" _hdr_bindings="0" _hdr_tgenabled="no"
  declare -A _b_name _b_type _b_model _b_stack _b_codebase _b_tg _b_reg _b_src
  while IFS=$'\t' read -r rectype f1 f2 f3 f4 f5 f6 f7 f8 f9; do
    case "$rectype" in
      HEADER) _hdr_agents="$f1"; _hdr_bindings="$f2"; _hdr_tgenabled="$f3" ;;
      AGENT)
        _b_name[$f1]="$f2"; _b_type[$f1]="$f3"; _b_model[$f1]="$f4"
        _b_stack[$f1]="$f5"; _b_codebase[$f1]="$f6"; _b_tg[$f1]="$f7"; _b_reg[$f1]="$f8"
        _b_src[$f1]="$f9"
        ;;
    esac
  done <<< "$_batch_out"

  # ── OpenClaw status bar ──
  local gw_badge tg_badge
  local gw_status; gw_status=$(service_ctl is-active 2>/dev/null) || gw_status="inactive"
  if [[ "$gw_status" == "active" ]]; then
    gw_badge="${GREEN}● gateway up${RESET}"
  else
    gw_badge="${RED}○ gateway down${RESET}"
  fi
  if [[ "$_hdr_tgenabled" == "yes" ]]; then
    tg_badge="${GREEN}● telegram on${RESET}"
  else
    tg_badge="${YELLOW}○ telegram off${RESET}"
  fi

  echo ""
  echo -e "  ${BOLD}OpenClaw${RESET}  ${gw_badge}  ${tg_badge}  ${DIM}│${RESET}  ${_hdr_agents} agents  ${_hdr_bindings} binding(s)  ${DIM}│${RESET}  v$(openclaw --version 2>/dev/null || echo '?')"
  echo -e "  ${DIM}$(printf '%0.s─' {1..66})${RESET}"

  echo -e "${BOLD}${CYAN}PROJECT AGENTS${RESET} ${DIM}(your work - each is dedicated to one codebase/project)${RESET} ${BOLD}($count)${RESET}"
  echo ""

  while IFS= read -r id; do
    local name="${_b_name[$id]:-$id}"
    local type="${_b_type[$id]:-repo}"
    local model="${_b_model[$id]:-$DEFAULT_MODEL}"
    local stack="${_b_stack[$id]:-}"
    local codebase="${_b_codebase[$id]:-}"
    local tg="${_b_tg[$id]:-}"
    local registered="${_b_reg[$id]:-0}"
    local activity;   activity=$(last_activity "$id")
    # Model intent: stored modelSource, or inferred from the role policy.
    local src="${_b_src[$id]:-}"
    if [[ -z "$src" ]]; then
      [[ "$model" == "$(resolve_role_model "$type")" ]] && src="policy" || src="pinned"
    fi
    local workspace="$PROJECTS_DIR/$id"
    local has_memory; [[ -f "$workspace/MEMORY.md" ]] && has_memory="yes" || has_memory="no"
    local has_reqs;   [[ -f "$workspace/REQUIREMENTS.md" ]] && has_reqs="yes" || has_reqs="no"
    local mem_days;   mem_days=$(find "$workspace/memory" -maxdepth 1 -name '*.md' 2>/dev/null | wc -l | tr -d ' ')

    # ── Build status badges ──
    local badges=""

    if [[ "$registered" == "1" ]]; then
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

    if [[ "$has_memory" == "yes" ]]; then
      badges+="${GREEN}● memory${RESET}  "
    else
      badges+="${DIM}○ no memory${RESET}  "
    fi

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

    # Short form for the card view: last path segment (e.g. "claude-sonnet-4-6", "gpt-4.1-mini")
    # Full model ID is visible in `rack info` and `rack models`.
    local model_short="${model##*/}"

    # ── Render card ──
    echo ""
    echo -e "  ${BOLD}${CYAN}$id${RESET}  ${DIM}($name)${RESET}"
    echo -e "  ${type}  │  ${model_short} (${src})  │  stack: ${stack:-${DIM}—${RESET}}  │  ${mem_days} day-log(s)"
    echo -e "  path: ${path_short}  │  active: ${activity}"
    echo -e "  ${badges}"
  done <<< "$ids"

  # ── Telegram setup summary ──
  local unwired=()
  local wired_list=()

  while IFS= read -r id; do
    local tg_check="${_b_tg[$id]:-}"
    local expected="${TELEGRAM_GROUP_NAMES[$id]:-}"
    if [[ -n "$tg_check" ]]; then
      wired_list+=("$id")
    elif [[ -n "$expected" ]]; then
      unwired+=("$id|$expected")
    fi
  done <<< "$ids"

  # Manager is a specialist not in project list — still needs a direct call
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

  # ── Specialist agents section ──
  echo ""
  echo -e "${BOLD}${GREEN}SPECIALIST AGENTS${RESET} ${DIM}(the team - shared across all projects)${RESET}"
  echo ""
  echo -e "  ${DIM}These work across ALL your projects. Don't wire them to individual groups.${RESET}"
  echo ""

  # One batch call replaces 6 per-specialist python3 -c spawns
  local _spec_out; _spec_out=$(_list_spec_batch "${RACK_SPECIALISTS[@]}")
  declare -A _spec_model _spec_src
  while IFS=$'\t' read -r rectype spec model src; do
    [[ "$rectype" == "SPEC" ]] && { _spec_model[$spec]="$model"; _spec_src[$spec]="$src"; }
  done <<< "$_spec_out"

  local spec
  for spec in "${RACK_SPECIALISTS[@]}"; do
    [[ -z "${_spec_model[$spec]:-}" ]] && continue
    local model_short="${_spec_model[$spec]##*/}"
    local spec_src="${_spec_src[$spec]:-}"
    if [[ -z "$spec_src" ]]; then
      [[ "${_spec_model[$spec]}" == "$(resolve_role_model "$spec")" ]] && spec_src="policy" || spec_src="pinned"
    fi
    printf "  ${GREEN}✓${RESET} %-12s ${DIM}%-28s (%s) — %s${RESET}\n" \
      "$spec" "$model_short" "$spec_src" "${ROLE_WHY[$spec]:-}"
  done

  echo ""
  printf '%0.s─' {1..70}; echo ""
  dim "  rack info <id>     detailed view"
  dim "  rack cost          token usage"
  dim "  rack models        role→model policy"
  dim "  rack profile <id>  pin/unpin an agent's model"
  echo ""
}

