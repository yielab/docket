#!/usr/bin/env bash
# Command: scope

cmd_scope() {
  local id="${1:-}" action="${2:-show}" project_key="${3:-}"
  [[ -z "$id" ]] && id=$(pick_project "Manage scope for")
  local workspace="$PROJECTS_DIR/$id"
  [[ ! -d "$workspace" ]] && error "Project '$id' not found."

  local name; name=$(meta_get "$id" "name" "$id")
  local current_key; current_key=$(meta_get "$id" "projectKey" "default")
  local current_session; current_session=$(meta_get "$id" "sessionKey" "agent:${id}:default")

  case "$action" in
    show)
      header "Session Scope: $name ($id)"
      echo ""
      printf "  ${BOLD}%-18s${RESET} %s\n" "Current Scope:"   "$current_key"
      printf "  ${BOLD}%-18s${RESET} %s\n" "Session Key:"     "$current_session"
      echo ""
      echo "This session key prevents the agent from accessing other project contexts."
      echo "Each project scope gets isolated workspace memory and routing."
      echo ""
      echo "Usage:"
      echo "  rack scope $id set <project-key>    # Change project scope"
      echo "  rack scope $id reset                # Reset to 'default'"
      echo ""
      ;;
    set)
      [[ -z "$project_key" ]] && error_hint "Project key required" "Usage: rack scope $id set <project-key>"
      local new_session; new_session=$(generate_session_key "$id" "$project_key")
      meta_set "$id" "projectKey" "$project_key"
      meta_set "$id" "sessionKey" "$new_session"
      sync_session_key "$id" "$new_session"
      mark_gateway_dirty
      audit_log "scope.set" "$id=$project_key"
      success "Session scope updated: $current_key → $project_key"
      success "Session key: $new_session"
      info "Update SOUL.md to reflect the new scope if needed."
      restart_gateway_if_dirty
      ;;
    reset)
      local default_session; default_session=$(generate_session_key "$id" "default")
      meta_set "$id" "projectKey" "default"
      meta_set "$id" "sessionKey" "$default_session"
      sync_session_key "$id" "$default_session"
      mark_gateway_dirty
      audit_log "scope.reset" "$id"
      success "Session scope reset to: default"
      success "Session key: $default_session"
      restart_gateway_if_dirty
      ;;
    *)
      error_hint "Unknown action '$action'" "Use: show, set, or reset"
      ;;
  esac
}

