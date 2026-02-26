#!/usr/bin/env bash
# Centralized API key management for rack CLI

cmd_keys() {
  local subcmd="${1:-list}"
  shift || true

  case "$subcmd" in
    add)    _keys_add "$@" ;;
    list)   _keys_list ;;
    remove) _keys_remove "$@" ;;
    *)
      cat <<EOF
${BOLD}Usage:${RESET} rack keys <command>

${BOLD}Commands:${RESET}
  ${GREEN}add${RESET} <KEY_NAME>      Add or update an API key (prompts for value)
  ${GREEN}list${RESET}                List all stored keys (values masked)
  ${GREEN}remove${RESET} <KEY_NAME>   Remove an API key

${BOLD}Examples:${RESET}
  rack keys add GOOGLE_AI_API_KEY
  rack keys list
  rack keys remove GOOGLE_AI_API_KEY

${BOLD}Storage:${RESET}
  Keys are stored in: ${DIM}~/.openclaw/secrets.json${RESET}
  File permissions: ${DIM}600 (secure, user-only access)${RESET}
  Available to all agents automatically via environment variables.

${BOLD}Common Keys:${RESET}
  ${CYAN}GOOGLE_AI_API_KEY${RESET}     - Google Imagen 3 & Veo (images/video)
  ${CYAN}OPENAI_API_KEY${RESET}        - OpenAI DALL-E 3 (images)
  ${CYAN}ANTHROPIC_API_KEY${RESET}     - Anthropic Claude (if not using OpenRouter)

Get Google AI key: ${BLUE}https://aistudio.google.com/${RESET}
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

  # Add/update key using Python
  python3 <<PYEOF
import json, sys

try:
    with open('$secrets_file', 'r') as f:
        secrets = json.load(f)
except:
    secrets = {}

secrets['$key_name'] = '''$key_value'''

with open('$secrets_file', 'w') as f:
    json.dump(secrets, f, indent=2)
    f.write('\n')

print("✓ Added key: $key_name")
PYEOF

  # Sync to all agent .env files
  _sync_keys_to_agents

  # Restart gateway to pick up new keys
  info "Restarting OpenClaw gateway to apply changes..."
  restart_gateway
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
  exists=$(python3 -c "import json; secrets=json.load(open('$secrets_file')); print('$key_name' in secrets)" 2>/dev/null || echo "False")

  if [[ "$exists" != "True" ]]; then
    error "Key '$key_name' not found"
  fi

  # Confirm removal
  read -rp "Remove key '$key_name'? [y/N]: " confirm
  if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
    echo "Cancelled."
    return
  fi

  # Remove key
  python3 <<PYEOF
import json

with open('$secrets_file', 'r') as f:
    secrets = json.load(f)

if '$key_name' in secrets:
    del secrets['$key_name']

with open('$secrets_file', 'w') as f:
    json.dump(secrets, f, indent=2)
    f.write('\n')

print("✓ Removed key: $key_name")
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

  local secrets_data
  secrets_data=$(cat "$secrets_file")

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

    # Create/update .env with secrets
    python3 <<EOF
import json, os

secrets = json.loads('''$secrets_data''')
env_file = '$env_file'

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
