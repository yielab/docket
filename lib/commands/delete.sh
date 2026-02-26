#!/usr/bin/env bash
# Command: delete

cmd_delete() {
  local id="${1:-}"
  [[ -z "$id" ]] && id=$(pick_project "Delete project")
  local workspace="$PROJECTS_DIR/$id"
  [[ ! -d "$workspace" ]] && error "Project '$id' not found."

  local name; name=$(meta_get "$id" "name" "$id")
  local tg;   tg=$(get_tg_binding "$id")

  header "Delete: $name ($id)"
  echo ""
  echo -e "  Workspace:    $workspace"
  echo -e "  Registered:   $(agent_registered "$id" && echo "yes" || echo "no")"
  echo -e "  Telegram:     ${tg:-none}"
  echo ""
  warn "This will:"
  echo "  - Remove agent registration from openclaw.json"
  echo "  - Remove Telegram binding (if any)"
  echo ""
  read -rp "Also delete workspace directory? [y/N]: " DEL_WORKSPACE
  echo ""
  read -rp "Type the agent ID to confirm deletion [$id]: " CONFIRM
  [[ "$CONFIRM" != "$id" ]] && { warn "Aborted."; exit 0; }

  # Remove from openclaw
  remove_agent_config "$id"
  success "Removed from agent registry"

  # Remove binding
  if [[ -n "$tg" ]]; then
    remove_binding "$id"
    success "Telegram binding removed"
  fi

  # Remove workspace
  if [[ "${DEL_WORKSPACE,,}" == "y" ]]; then
    rm -rf "$workspace"
    success "Workspace deleted: $workspace"
  else
    warn "Workspace kept at: $workspace"
  fi

  restart_gateway
  success "Done. Project '$id' deleted."
}

