#!/usr/bin/env bash
# Command: profile

cmd_profile() {
  local id="${1:-}" profile="${2:-}"
  [[ -z "$id" ]] && id=$(pick_project "Set profile for")
  local workspace="$PROJECTS_DIR/$id"
  [[ ! -d "$workspace" ]] && error "Project '$id' not found."

  local name;    name=$(meta_get "$id" "name" "$id")
  local current; current=$(meta_get "$id" "model" "$DEFAULT_MODEL")
  local cur_profile; cur_profile=$(model_to_profile "$current")

  # No profile given — show current and available profiles
  if [[ -z "$profile" ]]; then
    header "Profile: $name ($id)"
    echo ""
    printf "  ${BOLD}Current model:${RESET}   %s\n" "$current"
    printf "  ${BOLD}Current profile:${RESET} %s\n" "$cur_profile"
    echo ""
    echo -e "${BOLD}Available profiles:${RESET}"
    printf "  ${GREEN}%-12s${RESET} %-35s %s\n" "economy"  "${MODEL_PROFILES[economy]}"  "\$0.80 / \$4.00 per MTok  — routine tasks, triage, simple Q&A"
    printf "  ${GREEN}%-12s${RESET} %-35s %s\n" "standard" "${MODEL_PROFILES[standard]}" "\$3.00 / \$15.00 per MTok — active development, code review"
    printf "  ${GREEN}%-12s${RESET} %-35s %s\n" "premium"  "${MODEL_PROFILES[premium]}"  "\$15.00 / \$75.00 per MTok — complex architecture, security"
    echo ""
    echo "Usage:  rack profile $id <economy|standard|premium>"
    echo ""
    return
  fi

  # Validate profile name
  local new_model
  new_model=$(resolve_model "$profile")
  if [[ "$new_model" == "$profile" && -z "${MODEL_PROFILES[$profile]:-}" ]]; then
    # Not a known profile name — check if it looks like a raw model ID
    if [[ "$profile" == *"/"* ]]; then
      info "Using raw model ID: $profile"
    else
      error_hint "Unknown profile '$profile'" "Use: economy, standard, premium, or a full model ID"
    fi
  fi

  # Skip if already set to this model
  if [[ "$new_model" == "$current" ]]; then
    warn "Already using $profile ($new_model). No change."
    return
  fi

  # Update .rack-meta.json
  meta_set "$id" "model" "$new_model"

  # Update openclaw.json agents list
  python3 - "$CONFIG_FILE" "$id" "$new_model" <<'PY'
import json, sys
path, agent_id, new_model = sys.argv[1], sys.argv[2], sys.argv[3]
with open(path) as f:
    config = json.load(f)
for agent in config.get("agents", {}).get("list", []):
    if agent.get("id") == agent_id:
        agent["model"] = new_model
        break
with open(path, "w") as f:
    json.dump(config, f, indent=2)
PY

  success "Profile changed: $cur_profile ($current) → $profile ($new_model)"
  restart_gateway
}

