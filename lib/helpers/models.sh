#!/usr/bin/env bash
# Model validation and fallback helpers
#
# Design: rack validates *format*, the OpenClaw daemon validates the actual model.
# A well-formed provider/model ID that rack doesn't recognise gets a warning (no
# pricing data) but is accepted and passed through — never rejected.

# Regex for a well-formed model ID (matches OpenClaw catalog format, including
# OpenRouter's nested provider/provider/model form).
_MODEL_ID_RE='^[a-z0-9_-]+/[A-Za-z0-9._:/-]+$'

# Legacy short-name aliases for backwards compat and typo healing.
# These are the only aliases rack owns; the daemon has its own alias system.
declare -A MODEL_ALIASES=(
  ["anthropic/claude-haiku-3-5"]="anthropic/claude-haiku-4-5"
  ["anthropic/claude-haiku-3"]="anthropic/claude-haiku-4-5"
  ["anthropic/claude-sonnet-3-5"]="anthropic/claude-sonnet-4-6"
  ["anthropic/claude-sonnet-4"]="anthropic/claude-sonnet-4-6"
  ["anthropic/claude-opus-3"]="anthropic/claude-opus-4-6"
  ["anthropic/claude-opus-4"]="anthropic/claude-opus-4-6"
  # Convenient short names resolve through the live tier mapping
  ["haiku"]="economy"
  ["sonnet"]="standard"
  ["opus"]="premium"
)

# Validate and normalise a model name.
# Returns: the canonical model ID on stdout; exits non-zero only on hard failure.
# Rules:
#   tier name (economy/standard/premium) → DEPRECATED; resolved via rank anchor + warn
#   MODEL_ALIASES entry                  → resolved (with warn if deprecated)
#   well-formed provider/model           → accepted as-is; warn if not in pricing table
#   malformed (no provider/ prefix)      → error with usage hint
validate_model() {
  local model="$1"

  # 1. Deprecated tier name → rank anchor
  if [[ -n "${MODEL_PROFILES[$model]:-}" ]]; then
    warn "Tier names are deprecated. '$model' → ${MODEL_PROFILES[$model]}. Use role policy (rack models) or a provider/model ID."
    echo "${MODEL_PROFILES[$model]}"
    return 0
  fi

  # 2. Alias (may resolve to a tier, which then resolves to a model)
  if [[ -n "${MODEL_ALIASES[$model]:-}" ]]; then
    local resolved="${MODEL_ALIASES[$model]}"
    # Alias may point to a tier name — resolve one more level
    if [[ -n "${MODEL_PROFILES[$resolved]:-}" ]]; then
      resolved="${MODEL_PROFILES[$resolved]}"
    fi
    warn "Model alias '$model' → '$resolved'."
    echo "$resolved"
    return 0
  fi

  # 3. Well-formed provider/model — accepted, warn if unpriced
  if [[ "$model" =~ $_MODEL_ID_RE ]]; then
    if [[ -z "${MODEL_PRICING[$model]:-}" ]]; then
      warn "Model '$model' is not in rack's pricing table — cost will show as n/a."
    fi
    echo "$model"
    return 0
  fi

  # 4. Malformed
  local roles
  roles=$(for r in "${RACK_ROLES[@]}"; do
    printf "  %-12s %s\n" "$r" "${ROLE_MODELS[$r]:-}"
  done)
  error "Invalid model: '$model'
Use a full provider/model ID (e.g. anthropic/claude-sonnet-4-6).
Current role policy:
$roles
Change a role's model: rack models set <role> <provider/model>"
  return 1
}

# Return the fallback model for a given model, walking the rank-anchor chain.
# strong-anchor models fall back to the next-cheaper anchor; floor = cheapest.
# premium → standard → economy → economy (floor)
get_fallback_model() {
  local model="$1"
  local economy="${MODEL_PROFILES[economy]:-anthropic/claude-haiku-4-5}"
  local standard="${MODEL_PROFILES[standard]:-anthropic/claude-sonnet-4-6}"
  local premium="${MODEL_PROFILES[premium]:-anthropic/claude-opus-4-6}"

  case "$model" in
    "$premium") echo "$standard" ;;
    "$standard") echo "$economy" ;;
    *) echo "$economy" ;;
  esac
}

# Policy role for an agent: specialists' role is their id; project agents'
# role is their type (repo|task).
agent_role() {
  local id="$1"
  if is_specialist "$id"; then
    echo "$id"
  else
    meta_get "$id" "type" "repo"
  fi
}

# Model intent for an agent: "policy" (follow the role policy) or "pinned"
# (explicit model choice). Agents created before this field existed get it
# inferred: model matches the role's policy model → policy, else pinned.
agent_model_source() {
  local id="$1"
  local src; src=$(meta_get "$id" "modelSource" "")
  if [[ -n "$src" ]]; then
    echo "$src"
    return
  fi
  local role; role=$(agent_role "$id")
  local model; model=$(meta_get "$id" "model" "")
  if [[ -z "$model" || "$model" == "$(resolve_role_model "$role")" ]]; then
    echo "policy"
  else
    echo "pinned"
  fi
}

# All agent ids the model policy governs: project agents + installed specialists.
policy_agent_ids() {
  project_ids
  local s
  for s in "${RACK_SPECIALISTS[@]}"; do
    [[ -d "$OPENCLAW_DIR/workspaces/$s" ]] && echo "$s"
  done
}

# Re-resolve every policy-following agent against the live role policy.
# Pinned agents are never touched. Prints one line per change, audit-logs each,
# and marks the gateway dirty when anything changed (caller restarts once).
reapply_role_policy() {
  local id role target current src changed=0
  while IFS= read -r id; do
    [[ -n "$id" ]] || continue
    src=$(agent_model_source "$id")
    [[ "$src" == "policy" ]] || continue
    role=$(agent_role "$id")
    target=$(resolve_role_model "$role")
    current=$(meta_get "$id" "model" "")
    [[ "$target" == "$current" ]] && continue
    if set_agent_model "$id" "$target" 2>/dev/null; then
      echo "  $id ($role): ${current:-unset} → $target"
    else
      # Not in the daemon's agents.list — keep rack's view consistent anyway.
      meta_set "$id" "model" "$target"
      echo "  $id ($role): ${current:-unset} → $target (meta only — not registered)"
    fi
    meta_set "$id" "modelSource" "policy"
    audit_log "models.reapply" "$id=$target"
    changed=$(( changed + 1 ))
  done < <(policy_agent_ids)
  [[ "$changed" -gt 0 ]] && mark_gateway_dirty
  return 0
}

# Fix all invalid/deprecated model IDs in openclaw.json using the MODEL_ALIASES
# table. Safe to run multiple times (idempotent).
fix_invalid_models() {
  python3 - "$CONFIG_FILE" <<PYEOF
import json, sys, os, re

config_path = sys.argv[1]
with open(config_path, 'r') as f:
    config = json.load(f)

# Build alias map from bash-compatible representation passed via heredoc
# (kept identical to MODEL_ALIASES above)
aliases = {
    'anthropic/claude-haiku-3-5': 'anthropic/claude-haiku-4-5',
    'anthropic/claude-haiku-3':   'anthropic/claude-haiku-4-5',
    'anthropic/claude-sonnet-3-5': 'anthropic/claude-sonnet-4-6',
    'anthropic/claude-sonnet-4':  'anthropic/claude-sonnet-4-6',
    'anthropic/claude-opus-3':    'anthropic/claude-opus-4-6',
    'anthropic/claude-opus-4':    'anthropic/claude-opus-4-6',
}

fixed_count = 0

def fix_model(old):
    new = aliases.get(old)
    if new:
        return new, True
    return old, False

if 'model' in config:
    new_val, changed = fix_model(config['model'])
    if changed:
        print(f"Fixed root model: {config['model']} → {new_val}")
        config['model'] = new_val
        fixed_count += 1

for agent in config.get('agents', {}).get('list', []):
    if 'model' in agent:
        new_val, changed = fix_model(agent['model'])
        if changed:
            print(f"Fixed {agent.get('id')} model: {agent['model']} → {new_val}")
            agent['model'] = new_val
            fixed_count += 1

if 'models' in config:
    for key, value in config['models'].items():
        if isinstance(value, dict) and 'model' in value:
            new_val, changed = fix_model(value['model'])
            if changed:
                print(f"Fixed models.{key}: {value['model']} → {new_val}")
                value['model'] = new_val
                fixed_count += 1

if fixed_count > 0:
    with open(config_path, 'w') as f:
        json.dump(config, f, indent=2)
    print(f"\n✓ Fixed {fixed_count} invalid model references")
else:
    print("✓ No invalid models found")
PYEOF
}
