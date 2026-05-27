#!/usr/bin/env bash
# Model validation and fallback helpers

# Valid Claude models (as of March 2026)
declare -A VALID_MODELS=(
  ["anthropic/claude-haiku-4-5"]=1
  ["anthropic/claude-sonnet-4-6"]=1
  ["anthropic/claude-opus-4-6"]=1
)

# Model aliases for common typos/old names
declare -A MODEL_ALIASES=(
  ["anthropic/claude-haiku-3-5"]="anthropic/claude-haiku-4-5"
  ["anthropic/claude-haiku-3"]="anthropic/claude-haiku-4-5"
  ["anthropic/claude-sonnet-3-5"]="anthropic/claude-sonnet-4-6"
  ["anthropic/claude-sonnet-4"]="anthropic/claude-sonnet-4-6"
  ["anthropic/claude-opus-3"]="anthropic/claude-opus-4-6"
  ["anthropic/claude-opus-4"]="anthropic/claude-opus-4-6"
  ["haiku"]="anthropic/claude-haiku-4-5"
  ["sonnet"]="anthropic/claude-sonnet-4-6"
  ["opus"]="anthropic/claude-opus-4-6"
)

# Validate and normalize a model name
# Usage: validate_model "anthropic/claude-haiku-3-5"
# Returns: normalized model name or empty if invalid
validate_model() {
  local model="$1"

  # Check if already valid
  if [[ -n "${VALID_MODELS[$model]}" ]]; then
    echo "$model"
    return 0
  fi

  # Check if there's an alias
  if [[ -n "${MODEL_ALIASES[$model]}" ]]; then
    local normalized="${MODEL_ALIASES[$model]}"
    warn "Model '$model' is deprecated/invalid. Using '$normalized' instead."
    echo "$normalized"
    return 0
  fi

  # Unknown model
  error "Invalid model: $model"
  echo "Valid models:"
  echo "  - anthropic/claude-haiku-4-5"
  echo "  - anthropic/claude-sonnet-4-6"
  echo "  - anthropic/claude-opus-4-6"
  return 1
}

# Get fallback model for a given model
# Usage: get_fallback_model "anthropic/claude-opus-4-6"
get_fallback_model() {
  local model="$1"

  case "$model" in
    anthropic/claude-opus-4-6)
      echo "anthropic/claude-sonnet-4-6"
      ;;
    anthropic/claude-sonnet-4-6)
      echo "anthropic/claude-haiku-4-5"
      ;;
    *)
      echo "anthropic/claude-haiku-4-5"
      ;;
  esac
}

# Fix all invalid models in OpenClaw config
fix_invalid_models() {
  python3 << 'PYEOF'
import json
import os

config_path = os.path.expanduser('~/.openclaw/openclaw.json')
with open(config_path, 'r') as f:
    config = json.load(f)

# Model aliases
aliases = {
    'anthropic/claude-haiku-3-5': 'anthropic/claude-haiku-4-5',
    'anthropic/claude-haiku-3': 'anthropic/claude-haiku-4-5',
    'anthropic/claude-sonnet-3-5': 'anthropic/claude-sonnet-4-6',
    'anthropic/claude-sonnet-4': 'anthropic/claude-sonnet-4-6',
    'anthropic/claude-opus-3': 'anthropic/claude-opus-4-6',
    'anthropic/claude-opus-4': 'anthropic/claude-opus-4-6',
}

fixed_count = 0

# Fix in main config
if 'model' in config:
    old = config['model']
    if old in aliases:
        config['model'] = aliases[old]
        print(f"Fixed root model: {old} → {config['model']}")
        fixed_count += 1

# Fix in agents
for agent in config.get('agents', {}).get('registered', []):
    if 'model' in agent:
        old = agent['model']
        if old in aliases:
            agent['model'] = aliases[old]
            print(f"Fixed {agent.get('id')} model: {old} → {agent['model']}")
            fixed_count += 1

# Fix in models config
if 'models' in config:
    for key, value in config['models'].items():
        if isinstance(value, dict) and 'model' in value:
            old = value['model']
            if old in aliases:
                value['model'] = aliases[old]
                print(f"Fixed models.{key}: {old} → {value['model']}")
                fixed_count += 1

if fixed_count > 0:
    with open(config_path, 'w') as f:
        json.dump(config, f, indent=2)
    print(f"\n✓ Fixed {fixed_count} invalid model references")
else:
    print("✓ No invalid models found")

PYEOF
}
