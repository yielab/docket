#!/usr/bin/env bash
# Command: unwire

cmd_unwire() {
  local id="${1:-}" channel="telegram"
  # Parse --channel flag
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --channel) channel="$2"; shift 2 ;;
      *) [[ -z "$id" ]] && id="$1"; shift ;;
    esac
  done
  [[ -z "$id" ]] && id=$(pick_project "Unwire channel")

  # Check both project and specialist agent locations
  local workspace="$PROJECTS_DIR/$id"
  if [[ ! -d "$workspace" ]]; then
    workspace="$OPENCLAW_DIR/workspaces/$id"
    [[ ! -d "$workspace" ]] && error "Agent '$id' not found."
  fi

  local name; name=$(meta_get "$id" "name" "$id" 2>/dev/null || echo "$id")
  local peer; peer=$(get_channel_binding "$id" "$channel")

  [[ -z "$peer" ]] && { warn "'$id' has no ${channel} binding."; exit 0; }

  header "Unwire ${channel^}: $name ($id)"
  echo ""
  warn "This will remove the $channel binding for peer $peer"
  read -rp "Confirm? [y/N]: " CONFIRM
  [[ "${CONFIRM,,}" != "y" ]] && { warn "Aborted."; exit 0; }

  remove_binding "$id"
  success "Binding removed"
  restart_gateway
}

