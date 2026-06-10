#!/usr/bin/env bash
# Centralized API key management for rack CLI

cmd_keys() {
  local subcmd="${1:-list}"
  shift || true

  case "$subcmd" in
    add)      _keys_add "$@" ;;
    list)     _keys_list ;;
    remove)   _keys_remove "$@" ;;
    setup)    _keys_setup ;;
    validate) _keys_validate "$@" ;;
    export)   _keys_export ;;
    *)
      cat <<EOF
${BOLD}Usage:${RESET} rack keys <command>

${BOLD}Commands:${RESET}
  ${GREEN}setup${RESET}                Interactive setup wizard for all API keys
  ${GREEN}add${RESET} <KEY_NAME>       Add or update a specific API key
  ${GREEN}list${RESET}                 List all stored keys (values masked)
  ${GREEN}validate${RESET} [KEY_NAME]  Test if API keys are working
  ${GREEN}remove${RESET} <KEY_NAME>    Remove an API key
  ${GREEN}export${RESET}               Export keys as environment variables (for shell)

${BOLD}Storage Location (Single Source of Truth):${RESET}
  ${CYAN}~/.openclaw/secrets.json${RESET}

  All API keys are stored in ONE file with secure permissions (600).
  Keys are automatically synced to:
    • Agent workspaces (.env files)
    • OpenClaw gateway (via environment)
    • Shell environment (via 'export' command)

${BOLD}Quick Start:${RESET}
  ${GREEN}rack keys setup${RESET}      Run interactive wizard (recommended)
  ${GREEN}rack keys list${RESET}       See what keys you have

${BOLD}Supported Providers:${RESET}
  ${CYAN}ANTHROPIC_API_KEY${RESET}     Anthropic Claude (claude-3/4 models)
  ${CYAN}OPENAI_API_KEY${RESET}        OpenAI GPT/DALL-E
  ${CYAN}GOOGLE_AI_API_KEY${RESET}     Google Gemini/Imagen/Veo
  ${CYAN}OPENROUTER_API_KEY${RESET}    OpenRouter (unified access to many models)

${BOLD}Get API Keys:${RESET}
  Anthropic:  ${BLUE}https://console.anthropic.com/settings/keys${RESET}
  OpenAI:     ${BLUE}https://platform.openai.com/api-keys${RESET}
  Google AI:  ${BLUE}https://aistudio.google.com/apikey${RESET}
  OpenRouter: ${BLUE}https://openrouter.ai/settings/keys${RESET}
EOF
      ;;
  esac
}

# Add or update a key
_keys_add() {
  local key_name="$1"
  if [[ -z "$key_name" ]]; then
    error "Key name required. Usage: rack keys add <KEY_NAME>"
  fi

  # Validate key name format (uppercase, alphanumeric + underscore)
  if [[ ! "$key_name" =~ ^[A-Z][A-Z0-9_]*$ ]]; then
    error "Invalid key name. Use UPPERCASE_WITH_UNDERSCORES (e.g., GOOGLE_AI_API_KEY)"
  fi

  # Prompt for value (hidden input)
  echo -e "${BOLD}Add API Key${RESET}"
  echo -e "Key name: ${CYAN}$key_name${RESET}"
  echo ""
  read -rsp "Enter key value (hidden): " key_value
  echo ""

  if [[ -z "$key_value" ]]; then
    error "Key value cannot be empty"
  fi

  # Create secrets.json if it doesn't exist
  local secrets_file="$OPENCLAW_DIR/secrets.json"
  if [[ ! -f "$secrets_file" ]]; then
    echo '{}' > "$secrets_file"
    chmod 600 "$secrets_file"
    info "Created $secrets_file"
  fi

  # Add/update key (value passed via environment — never interpolated into code)
  RACK_KEY_VALUE="$key_value" _keys_store "$secrets_file" "$key_name"
  success "Added key: $key_name"

  # Sync to all agent .env files
  _sync_keys_to_agents

  # Restart gateway to pick up new keys
  info "Restarting OpenClaw gateway to apply changes..."
  restart_gateway
}

# Safely write one key into secrets.json.
# The value is read from $RACK_KEY_VALUE (environment), the name and path arrive
# via argv — nothing user-controlled is ever interpolated into Python source.
# Writes atomically (tmp + replace) and enforces 0600.
# Usage: RACK_KEY_VALUE="$value" _keys_store <secrets-file> <KEY_NAME>
_keys_store() {
  local secrets_file="$1" key_name="$2"
  python3 - "$secrets_file" "$key_name" <<'PYEOF'
import json, os, sys
path, key_name = sys.argv[1], sys.argv[2]
value = os.environ.get("RACK_KEY_VALUE", "")
try:
    with open(path) as f:
        secrets = json.load(f)
except Exception:
    secrets = {}
secrets[key_name] = value
tmp = path + ".tmp"
with open(tmp, "w") as f:
    json.dump(secrets, f, indent=2)
    f.write("\n")
os.chmod(tmp, 0o600)
os.replace(tmp, path)
PYEOF
}

# List all stored keys (masked)
_keys_list() {
  local secrets_file="$OPENCLAW_DIR/secrets.json"

  if [[ ! -f "$secrets_file" ]]; then
    echo -e "${DIM}No API keys stored yet.${RESET}"
    echo ""
    echo -e "Add a key with: ${GREEN}rack keys add <KEY_NAME>${RESET}"
    return
  fi

  echo -e "${BOLD}Stored API Keys${RESET}"
  echo -e "${DIM}File: $secrets_file${RESET}"
  echo ""

  python3 - "$secrets_file" <<'PYEOF'
import json, sys

try:
    with open(sys.argv[1], 'r') as f:
        secrets = json.load(f)
except Exception as e:
    print(f"Error reading secrets: {e}", file=sys.stderr)
    sys.exit(1)

if not secrets:
    print("No keys found.")
else:
    max_len = max(len(k) for k in secrets.keys())
    for key, value in secrets.items():
        # Mask value (show first 4 and last 4 chars)
        if len(value) > 12:
            masked = value[:4] + '*' * (len(value) - 8) + value[-4:]
        else:
            masked = '*' * len(value)
        print(f"  {key:<{max_len}}  {masked}")
PYEOF

  echo ""
  echo -e "${DIM}Tip: Remove a key with${RESET} rack keys remove <KEY_NAME>"
}

# Remove a key
_keys_remove() {
  local key_name="$1"
  if [[ -z "$key_name" ]]; then
    error "Key name required. Usage: rack keys remove <KEY_NAME>"
  fi

  local secrets_file="$OPENCLAW_DIR/secrets.json"
  if [[ ! -f "$secrets_file" ]]; then
    error "No secrets file found"
  fi

  # Check if key exists
  local exists
  exists=$(python3 -c "import json,sys; secrets=json.load(open(sys.argv[1])); print(sys.argv[2] in secrets)" "$secrets_file" "$key_name" 2>/dev/null || echo "False")

  if [[ "$exists" != "True" ]]; then
    error "Key '$key_name' not found"
  fi

  # Confirm removal
  read -rp "Remove key '$key_name'? [y/N]: " confirm
  if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
    echo "Cancelled."
    return
  fi

  # Remove key (argv-passed, atomic write)
  python3 - "$secrets_file" "$key_name" <<'PYEOF'
import json, os, sys
path, key_name = sys.argv[1], sys.argv[2]
with open(path) as f:
    secrets = json.load(f)
secrets.pop(key_name, None)
tmp = path + ".tmp"
with open(tmp, "w") as f:
    json.dump(secrets, f, indent=2)
    f.write("\n")
os.chmod(tmp, 0o600)
os.replace(tmp, path)
print(f"✓ Removed key: {key_name}")
PYEOF

  # Sync to all agent .env files
  _sync_keys_to_agents

  # Restart gateway
  info "Restarting OpenClaw gateway..."
  restart_gateway
}

# Sync secrets.json to all agent .env files
_sync_keys_to_agents() {
  local secrets_file="$OPENCLAW_DIR/secrets.json"

  # Read secrets
  if [[ ! -f "$secrets_file" ]]; then
    return  # No secrets to sync
  fi

  # Find all agent workspaces
  local -a workspaces=()

  # Specialist agents (direct subdirs of workspaces/, excluding 'projects')
  if [[ -d "$OPENCLAW_DIR/workspaces" ]]; then
    for dir in "$OPENCLAW_DIR/workspaces"/*/; do
      local agent_id
      agent_id=$(basename "$dir")
      [[ "$agent_id" == "projects" ]] && continue
      [[ -d "$dir" ]] && workspaces+=("$dir")
    done
  fi

  # Project agents
  if [[ -d "$PROJECTS_DIR" ]]; then
    for dir in "$PROJECTS_DIR"/*/; do
      [[ -d "$dir" ]] && workspaces+=("$dir")
    done
  fi

  # Sync to each workspace
  local count=0
  for workspace in "${workspaces[@]}"; do
    local env_file="$workspace/.env"

    # Create/update .env with secrets (paths via argv; secrets read inside Python,
    # never interpolated into source)
    python3 - "$secrets_file" "$env_file" <<'EOF'
import json, os, sys

secrets_path, env_file = sys.argv[1], sys.argv[2]
with open(secrets_path) as f:
    secrets = json.load(f)

# Read existing .env if present
existing_lines = []
if os.path.exists(env_file):
    with open(env_file, 'r') as f:
        existing_lines = [line.rstrip() for line in f if not any(line.startswith(k + '=') for k in secrets.keys())]

# Write new .env
with open(env_file, 'w') as f:
    # Keep non-secret lines
    for line in existing_lines:
        if line.strip() and not line.strip().startswith('#'):
            continue  # Remove old non-comment content
        if line.strip():
            f.write(line + '\n')

    # Add header if file was empty
    if not existing_lines or not any('Agent Environment' in line for line in existing_lines):
        f.write('# Agent Environment Variables\n')
        f.write('# Managed by rack keys - do not edit manually\n\n')

    # Write all secrets
    for key, value in secrets.items():
        f.write(f'{key}={value}\n')

os.chmod(env_file, 0o600)
EOF

    ((count++))
  done

  [[ $count -gt 0 ]] && info "Synced keys to $count agent workspace(s)"
}

# Interactive setup wizard
_keys_setup() {
  header "API Keys Setup Wizard"
  echo ""
  echo "This wizard will help you configure API keys for OpenClaw agents."
  echo "Keys are stored in: ${CYAN}~/.openclaw/secrets.json${RESET}"
  echo ""

  local secrets_file="$OPENCLAW_DIR/secrets.json"

  # Load existing secrets
  local existing_secrets="{}"
  if [[ -f "$secrets_file" ]]; then
    existing_secrets=$(cat "$secrets_file")
  fi

  # Define providers with validation patterns
  declare -A providers=(
    ["ANTHROPIC_API_KEY"]="sk-ant-"
    ["OPENAI_API_KEY"]="sk-"
    ["GOOGLE_AI_API_KEY"]="AIza"
    ["OPENROUTER_API_KEY"]="sk-or-"
  )

  declare -A descriptions=(
    ["ANTHROPIC_API_KEY"]="Anthropic Claude (Sonnet, Opus, Haiku)"
    ["OPENAI_API_KEY"]="OpenAI GPT-4, GPT-3.5, DALL-E"
    ["GOOGLE_AI_API_KEY"]="Google Gemini, Imagen 3, Veo 2"
    ["OPENROUTER_API_KEY"]="Unified access to 200+ models"
  )

  declare -A urls=(
    ["ANTHROPIC_API_KEY"]="https://console.anthropic.com/settings/keys"
    ["OPENAI_API_KEY"]="https://platform.openai.com/api-keys"
    ["GOOGLE_AI_API_KEY"]="https://aistudio.google.com/apikey"
    ["OPENROUTER_API_KEY"]="https://openrouter.ai/settings/keys"
  )

  local keys_added=0

  # Iterate through each provider
  for key_name in ANTHROPIC_API_KEY OPENAI_API_KEY GOOGLE_AI_API_KEY OPENROUTER_API_KEY; do
    echo "────────────────────────────────────────────────────────────"
    echo ""
    echo "${BOLD}${key_name}${RESET}"
    echo "${DIM}${descriptions[$key_name]}${RESET}"
    echo ""

    # Check if key exists
    local has_key
    has_key=$(echo "$existing_secrets" | python3 -c "import json, sys; secrets=json.load(sys.stdin); print(sys.argv[1] in secrets)" "$key_name")

    if [[ "$has_key" == "True" ]]; then
      echo "${GREEN}✓${RESET} Key already configured"
      read -rp "Update this key? [y/N]: " update
      [[ ! "$update" =~ ^[Yy]$ ]] && continue
    fi

    echo "Get your key: ${BLUE}${urls[$key_name]}${RESET}"
    echo ""
    read -rp "Configure $key_name? [Y/n]: " configure

    if [[ "$configure" =~ ^[Nn]$ ]]; then
      echo "${DIM}Skipped${RESET}"
      echo ""
      continue
    fi

    # Read key value
    local key_value=""
    while true; do
      read -rsp "Paste your ${key_name} (hidden): " key_value
      echo ""

      if [[ -z "$key_value" ]]; then
        echo "${YELLOW}⚠${RESET} Empty value, skipping"
        break
      fi

      # Validate prefix
      local prefix="${providers[$key_name]}"
      if [[ "$key_value" != ${prefix}* ]]; then
        echo "${RED}✗${RESET} Invalid key format (should start with '${prefix}')"
        read -rp "Try again? [Y/n]: " retry
        [[ "$retry" =~ ^[Nn]$ ]] && break
        continue
      fi

      # Save key (value via environment — never interpolated into code)
      RACK_KEY_VALUE="$key_value" _keys_store "$secrets_file" "$key_name"

      echo "${GREEN}✓${RESET} Saved $key_name"
      echo ""
      ((keys_added++))
      break
    done
  done

  echo "────────────────────────────────────────────────────────────"
  echo ""

  if [[ $keys_added -eq 0 ]]; then
    info "No keys were added"
    return 0
  fi

  success "Added $keys_added API key(s)!"
  echo ""

  # Sync to agents
  echo "${BOLD}Syncing keys to agents...${RESET}"
  _sync_keys_to_agents

  # Restart gateway
  echo ""
  read -rp "Restart OpenClaw gateway to apply changes? [Y/n]: " restart
  if [[ ! "$restart" =~ ^[Nn]$ ]]; then
    restart_gateway
  else
    warn "Remember to restart gateway manually: ${GREEN}systemctl --user restart openclaw-gateway${RESET}"
  fi

  echo ""
  success "Setup complete!"
  echo ""
  echo "${BOLD}Next steps:${RESET}"
  echo "  • Validate keys: ${GREEN}rack keys validate${RESET}"
  echo "  • View keys: ${GREEN}rack keys list${RESET}"
  echo "  • Export to shell: ${GREEN}eval \$(rack keys export)${RESET}"
}

# Validate API keys by testing them
_keys_validate() {
  local key_name="${1:-}"
  local secrets_file="$OPENCLAW_DIR/secrets.json"

  if [[ ! -f "$secrets_file" ]]; then
    error "No API keys found. Run: rack keys setup"
  fi

  header "Validate API Keys"
  echo ""

  # If specific key provided, validate just that one
  if [[ -n "$key_name" ]]; then
    _validate_single_key "$key_name" "$secrets_file"
    return
  fi

  # Otherwise validate all keys
  local keys_to_validate
  keys_to_validate=$(python3 - "$secrets_file" <<'PYEOF'
import json, sys

with open(sys.argv[1]) as f:
    secrets = json.load(f)

for key_name in secrets.keys():
    print(f"{key_name}")
PYEOF
)

  while IFS= read -r key; do
    [[ -z "$key" ]] && continue
    _validate_single_key "$key" "$secrets_file"
  done <<< "$keys_to_validate"

  echo ""
  success "Validation complete"
  echo ""
  echo "${DIM}Note: Validation checks format only, not actual API access${RESET}"
  echo "${DIM}For full API testing, try using the keys with agents${RESET}"
}

_validate_single_key() {
  local key_name="$1"
  local secrets_file="$2"

  local key_value
  key_value=$(python3 -c "import json,sys; secrets=json.load(open(sys.argv[1])); print(secrets.get(sys.argv[2], ''))" "$secrets_file" "$key_name")

  if [[ -z "$key_value" ]]; then
    echo "  ${RED}✗${RESET} $key_name - Not found"
    return 1
  fi

  # Validate format
  local valid=true
  local reason=""

  case "$key_name" in
    ANTHROPIC_API_KEY)
      [[ "$key_value" != sk-ant-* ]] && valid=false && reason="Should start with 'sk-ant-'"
      [[ ${#key_value} -lt 40 ]] && valid=false && reason="Too short (expected 40+ chars)"
      ;;
    OPENAI_API_KEY)
      [[ "$key_value" != sk-* ]] && valid=false && reason="Should start with 'sk-'"
      [[ ${#key_value} -lt 40 ]] && valid=false && reason="Too short"
      ;;
    GOOGLE_AI_API_KEY)
      [[ "$key_value" != AIza* ]] && valid=false && reason="Should start with 'AIza'"
      [[ ${#key_value} -lt 35 ]] && valid=false && reason="Too short"
      ;;
    OPENROUTER_API_KEY)
      [[ "$key_value" != sk-or-* ]] && valid=false && reason="Should start with 'sk-or-'"
      ;;
  esac

  if $valid; then
    local masked="${key_value:0:8}...${key_value: -4}"
    echo "  ${GREEN}✓${RESET} $key_name - ${masked}"
  else
    echo "  ${YELLOW}⚠${RESET} $key_name - ${reason}"
  fi
}

# Export keys as environment variables
_keys_export() {
  local secrets_file="$OPENCLAW_DIR/secrets.json"

  if [[ ! -f "$secrets_file" ]]; then
    error "No API keys found. Run: rack keys setup"
  fi

  # Output export commands
  python3 - "$secrets_file" <<'PYEOF'
import json, sys

with open(sys.argv[1]) as f:
    secrets = json.load(f)

for key_name, key_value in secrets.items():
    # Escape single quotes in value
    safe_value = key_value.replace("'", "'\\''")
    print(f"export {key_name}='{safe_value}'")
PYEOF
}

# Show current environment status
_keys_env_status() {
  echo "${BOLD}Environment Variable Status${RESET}"
  echo ""

  for key_name in ANTHROPIC_API_KEY OPENAI_API_KEY GOOGLE_AI_API_KEY OPENROUTER_API_KEY; do
    if [[ -n "${!key_name}" ]]; then
      local value="${!key_name}"
      local masked="${value:0:8}...${value: -4}"
      echo "  ${GREEN}✓${RESET} $key_name = $masked"
    else
      echo "  ${DIM}✗${RESET} $key_name ${DIM}(not set)${RESET}"
    fi
  done
}
