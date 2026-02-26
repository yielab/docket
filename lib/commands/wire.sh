#!/usr/bin/env bash
# Command: wire

cmd_wire() {
  local id="${1:-}"
  [[ -z "$id" ]] && id=$(pick_project "Wire Telegram group")
  local workspace="$PROJECTS_DIR/$id"
  [[ ! -d "$workspace" ]] && error "Project '$id' not found."

  local name; name=$(meta_get "$id" "name" "$id")
  local existing_tg; existing_tg=$(get_tg_binding "$id")

  header "Wire Telegram: $name ($id)"
  echo ""
  [[ -n "$existing_tg" ]] && warn "Currently wired to group: $existing_tg"

  _show_unbound_groups
  read -rp "Telegram group ID: " TG_GROUP_ID
  [[ -z "$TG_GROUP_ID" ]] && { warn "Aborted."; exit 0; }

  _wire_group "$id" "$TG_GROUP_ID"
  restart_gateway
  success "Done. '$id' is now wired to group $TG_GROUP_ID"
}

