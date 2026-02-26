#!/usr/bin/env bash
# Command: reset

cmd_reset() {
  local id="${1:-}"
  [[ -z "$id" ]] && id=$(pick_project "Reset project")
  local workspace="$PROJECTS_DIR/$id"
  [[ ! -d "$workspace" ]] && error "Project '$id' not found."

  local name; name=$(meta_get "$id" "name" "$id")

  header "Reset: $name ($id)"
  echo ""
  echo "Choose what to reset:"
  echo "  1) Memory only     — delete memory/*.md daily logs"
  echo "  2) Full reset      — memory + MEMORY.md + HEARTBEAT.md (keep identity)"
  echo "  3) Deep reset      — full reset + regenerate SOUL.md/AGENTS.md from scratch"
  echo ""
  read -rp "Choice [1/2/3]: " RESET_LEVEL

  case "$RESET_LEVEL" in
    1)
      local count; count=$(find "$workspace/memory" -maxdepth 1 -name '*.md' 2>/dev/null | wc -l | tr -d ' ')
      read -rp "Delete $count memory log files? [y/N]: " CONFIRM
      [[ "${CONFIRM,,}" != "y" ]] && { warn "Aborted."; exit 0; }
      rm -f "$workspace/memory/"*.md
      success "Memory logs cleared ($count files)"
      ;;
    2)
      read -rp "Clear memory, MEMORY.md and reset HEARTBEAT.md? [y/N]: " CONFIRM
      [[ "${CONFIRM,,}" != "y" ]] && { warn "Aborted."; exit 0; }
      rm -f "$workspace/memory/"*.md
      rm -f "$workspace/MEMORY.md"
      cat > "$workspace/HEARTBEAT.md" <<HEARTBEAT
# HEARTBEAT.md — $(meta_get "$id" "name" "$id")

Check every session. Follow strictly. Delete items when done.

## Active Tasks
_none_

## Pending Decisions
_none_

## Notes
_none_
HEARTBEAT
      chmod 600 "$workspace/HEARTBEAT.md"
      success "Full reset complete — SOUL.md and AGENTS.md preserved"
      ;;
    3)
      read -rp "Regenerate ALL workspace files from metadata? [y/N]: " CONFIRM
      [[ "${CONFIRM,,}" != "y" ]] && { warn "Aborted."; exit 0; }
      rm -f "$workspace/memory/"*.md "$workspace/MEMORY.md" "$workspace/REQUIREMENTS.md"
      local type;     type=$(meta_get "$id" "type" "repo")
      local name2;    name2=$(meta_get "$id" "name" "$id")
      local codebase; codebase=$(meta_get "$id" "codebase" "")
      local stack;    stack=$(meta_get "$id" "stack" "")
      local desc;     desc=$(meta_get "$id" "description" "No description.")
      local model;    model=$(meta_get "$id" "model" "$DEFAULT_MODEL")
      _create_workspace "$id" "$type" "$name2" "$codebase" "$stack" "$desc" "$model"
      success "Deep reset complete — workspace regenerated from metadata"
      ;;
    *) error "Invalid choice." ;;
  esac
}

