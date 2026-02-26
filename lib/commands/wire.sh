#!/usr/bin/env bash
# Command: wire

cmd_wire() {
  local id="${1:-}"
  [[ -z "$id" ]] && id=$(pick_agent "Wire Telegram group")

  # Check both project and specialist agent locations
  local workspace="$PROJECTS_DIR/$id"
  local is_specialist=false
  if [[ ! -d "$workspace" ]]; then
    # Try specialist agent location
    workspace="$OPENCLAW_DIR/workspaces/$id"
    if [[ -d "$workspace" ]]; then
      is_specialist=true
    else
      error "Agent '$id' not found in projects or specialists."
    fi
  fi

  # Get agent name (from meta for projects, from SOUL.md or id for specialists)
  local name
  if [[ "$is_specialist" == "true" ]]; then
    # Extract name from SOUL.md or IDENTITY.md if available
    if [[ -f "$workspace/IDENTITY.md" ]]; then
      name=$(grep -m1 "^# " "$workspace/IDENTITY.md" 2>/dev/null | sed 's/^# //' || echo "$id")
    elif [[ -f "$workspace/SOUL.md" ]]; then
      name=$(grep -m1 "^# " "$workspace/SOUL.md" 2>/dev/null | sed 's/^# //' || echo "$id")
    else
      name="$id"
    fi
  else
    name=$(meta_get "$id" "name" "$id")
  fi
  local existing_tg; existing_tg=$(get_tg_binding "$id")

  header "Wire Telegram: $name ($id)"
  echo ""
  [[ -n "$existing_tg" ]] && warn "Currently wired to group: $existing_tg"

  # Get unbound groups
  local -a unbound_groups=()
  local -a group_titles=()
  _get_unbound_groups unbound_groups group_titles

  if [[ "${#unbound_groups[@]}" -eq 0 ]]; then
    warn "No unbound Telegram groups found in today's logs."
    echo ""
    echo "To wire a group:"
    echo "  1. Create a Telegram group"
    echo "  2. Add @claw_x9m_bot to the group"
    echo "  3. Send a message in the group"
    echo "  4. Wait a few seconds, then run: rack wire $id"
    echo ""
    echo "Or enter the group ID manually:"
    read -rp "Telegram group ID (or press Enter to cancel): " TG_GROUP_ID
    [[ -z "$TG_GROUP_ID" ]] && { warn "Aborted."; exit 0; }
  elif [[ "${#unbound_groups[@]}" -eq 1 ]]; then
    # Auto-select single unbound group
    local gid="${unbound_groups[0]}"
    local gtitle="${group_titles[0]}"
    echo -e "${GREEN}Found 1 unbound group:${RESET}"
    echo "  $gid - $gtitle"
    echo ""
    read -rp "Wire to this group? [Y/n]: " CONFIRM
    if [[ "${CONFIRM,,}" == "n" ]]; then
      warn "Aborted."
      exit 0
    fi
    TG_GROUP_ID="$gid"
  else
    # Multiple groups - show numbered menu
    echo -e "${GREEN}Available unbound groups:${RESET}"
    echo ""
    for i in "${!unbound_groups[@]}"; do
      printf "  ${BOLD}%2d.${RESET} %-20s %s\n" "$((i+1))" "${unbound_groups[$i]}" "${group_titles[$i]}"
    done
    echo ""
    echo "  ${BOLD} 0.${RESET} Enter group ID manually"
    echo ""

    local choice
    while true; do
      read -rp "Select group (1-${#unbound_groups[@]}, 0 for manual, or Enter to cancel): " choice
      [[ -z "$choice" ]] && { warn "Aborted."; exit 0; }

      if [[ "$choice" == "0" ]]; then
        read -rp "Telegram group ID: " TG_GROUP_ID
        [[ -z "$TG_GROUP_ID" ]] && { warn "Aborted."; exit 0; }
        break
      elif [[ "$choice" =~ ^[0-9]+$ ]] && [[ "$choice" -ge 1 ]] && [[ "$choice" -le "${#unbound_groups[@]}" ]]; then
        TG_GROUP_ID="${unbound_groups[$((choice-1))]}"
        break
      else
        warn "Invalid choice. Please enter 1-${#unbound_groups[@]} or 0."
      fi
    done
  fi

  _wire_group "$id" "$TG_GROUP_ID"
  restart_gateway
  success "Done. '$id' is now wired to group $TG_GROUP_ID"
}

