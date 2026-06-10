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
  [[ -z "$id" ]] && id=$(pick_project "Set profile for")
  local workspace="$PROJECTS_DIR/$id"
  [[ ! -d "$workspace" ]] && error "Project '$id' not found."

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
  local cur_profile; cur_profile=$(model_to_profile "$current")
  local budget;  budget=$(meta_get "$id" "budgetUsd" "")

  # No profile given — show current and available profiles
  if [[ -z "$profile" ]]; then
    header "Profile: $name ($id)"
    echo ""
    printf "  ${BOLD}Current model:${RESET}   %s\n" "$current"
    printf "  ${BOLD}Current profile:${RESET} %s\n" "$cur_profile"
    if [[ -n "$budget" && "$budget" != "0" ]]; then
      printf "  ${BOLD}Budget cap:${RESET}      \$%.2f\n" "$budget"
    else
      printf "  ${BOLD}Budget cap:${RESET}      none\n"
    fi
    echo ""
    echo -e "${BOLD}Available profiles:${RESET}"
    printf "  ${GREEN}%-12s${RESET} %-35s %s\n" "economy"  "${MODEL_PROFILES[economy]}"  "\$0.80 / \$4.00 per MTok  — routine tasks, triage, simple Q&A"
    printf "  ${GREEN}%-12s${RESET} %-35s %s\n" "standard" "${MODEL_PROFILES[standard]}" "\$3.00 / \$15.00 per MTok — active development, code review"
    printf "  ${GREEN}%-12s${RESET} %-35s %s\n" "premium"  "${MODEL_PROFILES[premium]}"  "\$15.00 / \$75.00 per MTok — complex architecture, security"
    echo ""
    echo "Usage:  rack profile $id <economy|standard|premium>"
    echo "        rack profile $id --budget <USD>   (0 = no cap)"
    echo ""
    return
  fi

  # Validate profile name
  local new_model
  new_model=$(resolve_model "$profile")
  if [[ "$new_model" == "$profile" && -z "${MODEL_PROFILES[$profile]:-}" ]]; then
    if [[ "$profile" == *"/"* ]]; then
      info "Using raw model ID: $profile"
    else
      error "Unknown profile '$profile'. Use: economy, standard, premium, or a full model ID."
    fi
  fi

  # Skip if already set to this model
  if [[ "$new_model" == "$current" ]]; then
    warn "Already using $profile ($new_model). No change."
    return
  fi

  # Update both openclaw.json and .rack-meta.json atomically
  set_agent_model "$id" "$new_model"

  success "Profile changed: $cur_profile ($current) → $profile ($new_model)"
  audit_log "profile.model" "$id=$profile ($new_model)"
  mark_gateway_dirty
  restart_gateway_if_dirty
}
