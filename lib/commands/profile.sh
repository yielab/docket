#!/usr/bin/env bash
# Command: profile

cmd_profile() {
  local budget_amount=""
  local -a pos=()

  # Parse flags, collecting positional args separately
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --budget)
        shift
        budget_amount="${1:-}"
        ;;
      *)
        pos+=("$1")
        ;;
    esac
    shift
  done

  local id="${pos[0]:-}" profile="${pos[1]:-}"
  [[ -z "$id" ]] && id=$(pick_agent "Set model for")
  local workspace; workspace=$(agent_workspace_dir "$id")
  [[ ! -d "$workspace" ]] && error "Agent '$id' not found."

  # Handle --budget flag
  if [[ -n "$budget_amount" ]]; then
    if ! python3 -c "
import sys
v = sys.argv[1]
try:
    f = float(v)
    sys.exit(0 if f >= 0 else 1)
except ValueError:
    sys.exit(1)
" "$budget_amount" 2>/dev/null; then
      error "Invalid budget amount '$budget_amount'. Must be a non-negative number (e.g. 5 or 10.50)."
    fi
    meta_set "$id" "budgetUsd" "$budget_amount"
    # Clear paused flag when budget is changed
    if [[ "$budget_amount" != "0" ]]; then
      meta_set "$id" "paused" ""
      meta_set "$id" "pausedReason" ""
      success "Budget cap set to \$${budget_amount} for '$id'."
    else
      success "Budget cap removed for '$id'."
    fi
    audit_log "profile.budget" "$id=\$${budget_amount}"
    [[ -z "$profile" ]] && return
  fi

  local name;    name=$(meta_get "$id" "name" "$id")
  local current; current=$(meta_get "$id" "model" "$DEFAULT_MODEL")
  local role;    role=$(agent_role "$id")
  local source;  source=$(agent_model_source "$id")
  local budget;  budget=$(meta_get "$id" "budgetUsd" "")

  # No model given — show current model, intent, and the role policy
  if [[ -z "$profile" ]]; then
    header "Model: $name ($id)"
    echo ""
    printf "  ${BOLD}Current model:${RESET}  %s\n" "$current"
    printf "  ${BOLD}Role:${RESET}           %s ${DIM}(%s)${RESET}\n" "$role" "${ROLE_WHY[$role]:-}"
    if [[ "$source" == "policy" ]]; then
      printf "  ${BOLD}Source:${RESET}         policy — follows the role's model (docket models)\n"
    else
      printf "  ${BOLD}Source:${RESET}         pinned — unaffected by policy changes\n"
    fi
    if [[ -n "$budget" && "$budget" != "0" ]]; then
      printf "  ${BOLD}Budget cap:${RESET}     \$%.2f\n" "$budget"
    else
      printf "  ${BOLD}Budget cap:${RESET}     none\n"
    fi
    echo ""
    printf "  ${BOLD}Policy for role '%s':${RESET} %s\n" "$role" "$(resolve_role_model "$role")"
    echo ""
    echo "Usage:  docket profile $id <provider/model>   # pin this agent to a model"
    echo "        docket profile $id default            # follow the role policy"
    echo "        docket profile $id --budget <USD>     # spending cap (0 = none)"
    echo "        docket models                         # view/change the role policy"
    echo ""
    return
  fi

  # Resolve the requested model. `default` re-attaches the agent to its role
  # policy; anything else (model ID, or a deprecated tier name) becomes a pin.
  local new_model new_source
  if [[ "$profile" == "default" || "$profile" == "policy" ]]; then
    new_model=$(resolve_role_model "$role")
    new_source="policy"
  else
    new_model=$(validate_model "$profile") || exit 1
    new_source="pinned"
  fi

  # Skip if nothing changes
  if [[ "$new_model" == "$current" && "$new_source" == "$source" ]]; then
    warn "Already using $new_model ($new_source). No change."
    return
  fi

  # Update both openclaw.json and .docket-meta.json atomically
  set_agent_model "$id" "$new_model"
  meta_set "$id" "modelSource" "$new_source"

  if [[ "$new_source" == "policy" ]]; then
    success "Model: $current → $new_model (follows role policy '$role')"
  else
    success "Model pinned: $current → $new_model"
  fi
  audit_log "profile.model" "$id=$new_model ($new_source)"
  mark_gateway_dirty
  restart_gateway_if_dirty
}
