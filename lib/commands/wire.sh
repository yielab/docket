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

  # Get all groups from logs (both bound and unbound)
  local -a all_groups=()
  local -a all_titles=()
  local -a all_bindings=()
  _get_all_groups all_groups all_titles all_bindings

  if [[ "${#all_groups[@]}" -eq 0 ]]; then
    warn "No Telegram groups found in today's logs."
    echo ""
    echo -e "${BOLD}To wire a group:${RESET}"
    echo "  ${CYAN}1.${RESET} Create a Telegram group"
    echo "  ${CYAN}2.${RESET} Add your OpenClaw bot to the group"
    echo "  ${CYAN}3.${RESET} Send a message in the group"
    echo "  ${CYAN}4.${RESET} Wait a few seconds, then run: ${GREEN}rack wire $id${RESET}"
    echo ""
    warn "Aborted - no groups available."
    exit 0
  fi

  # Filter to unbound groups
  local -a unbound_groups=()
  local -a group_titles=()
  for i in "${!all_groups[@]}"; do
    if [[ -z "${all_bindings[$i]}" ]]; then
      unbound_groups+=("${all_groups[$i]}")
      group_titles+=("${all_titles[$i]}")
    fi
  done

  # If no unbound groups, show all groups with current bindings
  if [[ "${#unbound_groups[@]}" -eq 0 ]]; then
    echo -e "${YELLOW}All groups are already bound:${RESET}"
    echo ""
    for i in "${!all_groups[@]}"; do
      local num=$((i+1))
      local binding_display="${all_bindings[$i]:-<unbound>}"
      printf "  ${BOLD}%2d.${RESET} %-20s %-30s → ${CYAN}%s${RESET}\n" \
        "$num" "${all_groups[$i]}" "${all_titles[$i]}" "$binding_display"
    done
    echo ""
    echo "You can:"
    echo "  ${CYAN}•${RESET} Create a new Telegram group, add bot, send message, then run: ${GREEN}rack wire $id${RESET}"
    echo "  ${CYAN}•${RESET} Unbind an existing group: ${GREEN}rack unwire <agent-id>${RESET}"
    echo "  ${CYAN}•${RESET} Override an existing binding (select number above)"
    echo ""

    read -rp "Select group (1-${#all_groups[@]}) or press Enter to cancel: " choice
    [[ -z "$choice" ]] && { warn "Aborted."; exit 0; }

    if [[ "$choice" =~ ^[0-9]+$ ]] && [[ "$choice" -ge 1 ]] && [[ "$choice" -le "${#all_groups[@]}" ]]; then
      TG_GROUP_ID="${all_groups[$((choice-1))]}"
      local prev_binding="${all_bindings[$((choice-1))]}"
      if [[ -n "$prev_binding" ]]; then
        warn "This will unbind '$prev_binding' from group '${all_titles[$((choice-1))]}'"
        read -rp "Continue? [y/N]: " confirm
        [[ "${confirm,,}" != "y" ]] && { warn "Aborted."; exit 0; }
      fi
    else
      warn "Invalid choice. Aborted."
      exit 0
    fi
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

