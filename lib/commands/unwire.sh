#!/usr/bin/env bash
# Command: unwire

cmd_unwire() {
  local id="${1:-}"
  [[ -z "$id" ]] && id=$(pick_project "Unwire Telegram group")
  local workspace="$PROJECTS_DIR/$id"
  [[ ! -d "$workspace" ]] && error "Project '$id' not found."

  local name; name=$(meta_get "$id" "name" "$id")
  local tg;   tg=$(get_tg_binding "$id")

  [[ -z "$tg" ]] && { warn "'$id' has no Telegram binding."; exit 0; }

  header "Unwire Telegram: $name ($id)"
  echo ""
  warn "This will remove the binding for group $tg"
  read -rp "Confirm? [y/N]: " CONFIRM
  [[ "${CONFIRM,,}" != "y" ]] && { warn "Aborted."; exit 0; }

  remove_binding "$id"
  success "Binding removed"
  restart_gateway
}

