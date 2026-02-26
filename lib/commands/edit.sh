#!/usr/bin/env bash
# Command: edit

cmd_edit() {
  local id="${1:-}"
  [[ -z "$id" ]] && id=$(pick_agent "Edit workspace for")

  # Check both project and specialist agent locations
  local workspace="$PROJECTS_DIR/$id"
  local is_specialist=false
  if [[ ! -d "$workspace" ]]; then
    workspace="$OPENCLAW_DIR/workspaces/$id"
    if [[ -d "$workspace" ]]; then
      is_specialist=true
    else
      error "Agent '$id' not found"
    fi
  fi

  local editor="${EDITOR:-${VISUAL:-nano}}"

  # Get agent name
  local name
  if [[ "$is_specialist" == "true" ]]; then
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

  # Check if editor is available
  if ! command -v "$editor" &>/dev/null; then
    warn "Editor '$editor' not found. Trying nano..."
    editor="nano"
    if ! command -v "$editor" &>/dev/null; then
      error "No editor available. Set \$EDITOR or install nano."
    fi
  fi

  header "Edit: $name ($id)"
  echo ""

  # Collect files to edit
  local files=()

  [[ -f "$workspace/SOUL.md" ]] && files+=("$workspace/SOUL.md")
  [[ -f "$workspace/IDENTITY.md" ]] && files+=("$workspace/IDENTITY.md")
  [[ -f "$workspace/AGENTS.md" ]] && files+=("$workspace/AGENTS.md")
  [[ -f "$workspace/TOOLS.md" ]] && files+=("$workspace/TOOLS.md")
  [[ -f "$workspace/HEARTBEAT.md" ]] && files+=("$workspace/HEARTBEAT.md")

  echo "Opening files in $editor:"
  for f in "${files[@]}"; do
    echo "  $(basename "$f")"
  done
  echo ""

  # Open files
  "$editor" "${files[@]}"

  success "Edits saved."
  echo ""
  info "Restart gateway to apply changes: systemctl --user restart openclaw-gateway.service"
}

