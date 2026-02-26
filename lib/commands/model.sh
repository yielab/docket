#!/usr/bin/env bash
# Command: model

cmd_model() {
  local id="${1:-}" new_model="${2:-}"
  [[ -z "$id" ]] && id=$(pick_project "Change model for")
  local workspace="$PROJECTS_DIR/$id"
  [[ ! -d "$workspace" ]] && error "Project '$id' not found."

  local name;    name=$(meta_get "$id" "name" "$id")
  local current; current=$(meta_get "$id" "model" "$DEFAULT_MODEL")

  local cur_profile; cur_profile=$(model_to_profile "$current")

  # If no new model provided, just show current
  if [[ -z "$new_model" ]]; then
    header "Model: $name ($id)"
    echo ""
    printf "  ${BOLD}Current:${RESET}  %s (%s)\n" "$current" "$cur_profile"
    printf "  ${BOLD}Default:${RESET}  %s\n" "$DEFAULT_MODEL"
    echo ""
    echo "Change with a profile:  rack profile $id economy|standard|premium"
    echo "Change with model ID:   rack model $id anthropic/claude-sonnet-4-6"
    echo ""
    return
  fi

  # Resolve profile names to model IDs
  new_model=$(resolve_model "$new_model")

  # Update model in .rack-meta.json
  meta_set "$id" "model" "$new_model"

  # Update model in openclaw.json agents list
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

  local new_profile; new_profile=$(model_to_profile "$new_model")
  success "Model updated: $current ($cur_profile) → $new_model ($new_profile)"
  restart_gateway
}

