#!/usr/bin/env bash
# Command: edit

cmd_edit() {
  local id="${1:-}"
  [[ -z "$id" ]] && id=$(pick_project "Edit workspace for")
  local workspace="$PROJECTS_DIR/$id"
  [[ ! -d "$workspace" ]] && error "Project '$id' not found."

  local editor="${EDITOR:-${VISUAL:-nano}}"
  local name; name=$(meta_get "$id" "name" "$id")

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
  echo "Opening workspace files in $editor..."
  echo "  $workspace/SOUL.md"
  echo "  $workspace/AGENTS.md"
  echo "  $workspace/TOOLS.md"
  echo "  $workspace/HEARTBEAT.md"
  echo ""

  # Open the main workspace files (editor gets all four)
  "$editor" \
    "$workspace/SOUL.md" \
    "$workspace/AGENTS.md" \
    "$workspace/TOOLS.md" \
    "$workspace/HEARTBEAT.md"

  success "Edits saved."
}

