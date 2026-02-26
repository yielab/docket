#!/usr/bin/env bash
# Command: repair

cmd_repair() {
  local id="${1:-}"
  [[ -z "$id" ]] && id=$(pick_project "Repair project")
  local workspace="$PROJECTS_DIR/$id"
  [[ ! -d "$workspace" ]] && error "Project '$id' not found at $workspace"

  local name; name=$(meta_get "$id" "name" "$id")
  header "Repair: $name ($id)"
  echo ""
  local fixed=0

  # 1. Check required files
  local model; model=$(meta_get "$id" "model" "$DEFAULT_MODEL")
  for f in SOUL.md AGENTS.md TOOLS.md HEARTBEAT.md; do
    if [[ ! -f "$workspace/$f" ]]; then
      warn "Missing: $f"
      local type;     type=$(meta_get "$id" "type" "repo")
      local name2;    name2=$(meta_get "$id" "name" "$id")
      local codebase; codebase=$(meta_get "$id" "codebase" "")
      local stack;    stack=$(meta_get "$id" "stack" "")
      local desc;     desc=$(meta_get "$id" "description" "No description.")
      _create_workspace "$id" "$type" "$name2" "$codebase" "$stack" "$desc" "$model"
      success "Regenerated missing workspace files"
      ((fixed++)); break
    fi
  done

  # 2. Check memory directory
  if [[ ! -d "$workspace/memory" ]]; then
    mkdir -p "$workspace/memory"
    chmod 700 "$workspace/memory"
    success "Created missing memory/ directory"
    ((fixed++))
  fi

  # 3. Fix permissions
  local bad_dirs;  bad_dirs=$(find "$workspace" -type d ! -perm 700 2>/dev/null | wc -l | tr -d ' ')
  local bad_files; bad_files=$(find "$workspace" -type f ! -perm 600 2>/dev/null | wc -l | tr -d ' ')
  if [[ "$bad_dirs" -gt 0 || "$bad_files" -gt 0 ]]; then
    find "$workspace" -type d -exec chmod 700 {} \;
    find "$workspace" -type f -exec chmod 600 {} \;
    success "Fixed permissions ($bad_dirs dirs, $bad_files files)"
    ((fixed++))
  else
    success "Permissions OK"
  fi

  # 4. Check agent registration
  if ! agent_registered "$id"; then
    warn "Agent not registered — re-registering..."
    openclaw agents add "$id" \
      --workspace "$workspace" \
      --model "$model" \
      --non-interactive 2>&1 | grep -v "^$"
    success "Agent re-registered"
    ((fixed++))
  else
    success "Agent registration OK"
  fi

  # 5. Check Telegram binding
  local tg; tg=$(get_tg_binding "$id")
  if [[ -z "$tg" ]]; then
    warn "No Telegram binding"
    read -rp "Wire a Telegram group now? Enter group ID or blank to skip: " TG_INPUT
    if [[ -n "$TG_INPUT" ]]; then
      _wire_group "$id" "$TG_INPUT"
      ((fixed++))
    fi
  else
    success "Telegram binding OK ($tg)"
    # Verify group is in allowlist
    local in_allowlist
    in_allowlist=$(python3 -c "
import json
c = json.load(open('$CONFIG_FILE'))
groups = c.get('channels',{}).get('telegram',{}).get('groups',{})
print('yes' if '$tg' in groups else 'no')
" 2>/dev/null || echo "no")
    if [[ "$in_allowlist" != "yes" ]]; then
      warn "Group $tg not in allowlist — fixing..."
      openclaw config set "channels.telegram.groups.${tg}" '{"requireMention": false}' 2>&1 || true
      success "Group added to allowlist"
      ((fixed++))
    else
      success "Telegram allowlist OK"
    fi
  fi

  # 6. Restart if anything changed
  echo ""
  if [[ "$fixed" -gt 0 ]]; then
    success "$fixed issue(s) fixed"
    restart_gateway
  else
    success "Everything looks healthy — nothing to fix"
  fi
}

