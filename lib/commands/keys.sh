#!/usr/bin/env bash
# Centralized API key management for rack CLI

cmd_keys() {
  local subcmd="${1:-list}"
  shift || true

  case "$subcmd" in
    add)      _keys_add "$@" ;;
    list)     _keys_list ;;
    remove)   _keys_remove "$@" ;;
    rotate)   _keys_rotate "$@" ;;
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
  ${GREEN}rotate${RESET} <KEY_NAME>    Replace an existing key's value and re-sync
  ${GREEN}remove${RESET} <KEY_NAME>    Remove an API key
  ${GREEN}export${RESET}               Export keys as environment variables (for shell)

${BOLD}Storage Backend:${RESET}
  ${CYAN}file${RESET}    (default)  ~/.openclaw/secrets.json (0600)
  ${CYAN}keyring${RESET}           OS keyring via libsecret; secrets.json holds names only
  Select with ${GREEN}RACK_SECRETS_BACKEND=keyring${RESET} (falls back to file if unavailable).

  Keys are automatically synced to:
    • Agent workspaces (.env files) — scoped: each agent gets only the
      provider key its model needs (least privilege)
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

  # Store via the active backend (value via environment — never interpolated).
  RACK_KEY_VALUE="$key_value" secret_put "$key_name" || return 1
  _keys_touch_meta "$key_name" "added"
  audit_log "keys.add" "$key_name"
  success "Added key: $key_name ($(secrets_backend) backend)"

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

# Record key lifecycle metadata in a sidecar (secrets.meta.json) so `rack doctor`
# can report key age. Stores first-seen (added_at) and last-rotation (rotated_at)
# timestamps. The timestamp arrives via the environment; nothing user-controlled
# is interpolated into source. Atomic write, mode 0600.
# Usage: _keys_touch_meta <KEY_NAME> <added|rotated|removed>
_keys_touch_meta() {
  local key_name="$1" event="$2"
  local meta_file="$OPENCLAW_DIR/secrets.meta.json"
  local now
  now=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  RACK_META_NOW="$now" python3 - "$meta_file" "$key_name" "$event" <<'PYEOF'
import json, os, sys
path, key_name, event = sys.argv[1], sys.argv[2], sys.argv[3]
now = os.environ.get("RACK_META_NOW", "")
try:
    with open(path) as f:
        meta = json.load(f)
except Exception:
    meta = {}
if event == "removed":
    meta.pop(key_name, None)
else:
    entry = meta.get(key_name) or {}
    entry.setdefault("added_at", now)
    if event == "rotated":
        entry["rotated_at"] = now
    meta[key_name] = entry
tmp = path + ".tmp"
with open(tmp, "w") as f:
    json.dump(meta, f, indent=2)
    f.write("\n")
os.chmod(tmp, 0o600)
os.replace(tmp, path)
PYEOF
}

# Report stored-key age for `rack doctor`. Emits one machine-parseable line per
# key: "<STATE>|<KEY>|<detail>" where STATE is OK, STALE, or UNKNOWN. A key is
# STALE when its last add/rotation is older than the threshold (default 90 days,
# override with RACK_KEY_MAX_AGE_DAYS).
_keys_age_report() {
  local secrets_file="$OPENCLAW_DIR/secrets.json"
  local meta_file="$OPENCLAW_DIR/secrets.meta.json"
  [[ -f "$secrets_file" ]] || return 0
  RACK_KEY_THRESHOLD="${RACK_KEY_MAX_AGE_DAYS:-90}" \
    python3 - "$secrets_file" "$meta_file" <<'PYEOF'
import json, os, sys
from datetime import datetime, timezone
secrets_path, meta_path = sys.argv[1], sys.argv[2]
threshold = int(os.environ.get("RACK_KEY_THRESHOLD", "90"))
try:
    with open(secrets_path) as f:
        secrets = json.load(f)
except Exception:
    sys.exit(0)
try:
    with open(meta_path) as f:
        meta = json.load(f)
except Exception:
    meta = {}
now = datetime.now(timezone.utc)
def parse(ts):
    try:
        return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except Exception:
        return None
for key in sorted(secrets.keys()):
    entry = meta.get(key) or {}
    rotated = bool(entry.get("rotated_at"))
    ref = entry.get("rotated_at") or entry.get("added_at")
    dt = parse(ref) if ref else None
    if dt is None:
        print(f"UNKNOWN|{key}|age unknown (added before tracking)")
        continue
    age = max(0, (now - dt).days)
    verb = "since rotation" if rotated else "old"
    state = "STALE" if age >= threshold else "OK"
    print(f"{state}|{key}|{age}d {verb}")
PYEOF
}

# List all stored keys (masked)
_keys_list() {
  local names; names=$(secret_names)
  if [[ -z "$names" ]]; then
    echo -e "${DIM}No API keys stored yet.${RESET}"
    echo ""
    echo -e "Add a key with: ${GREEN}rack keys add <KEY_NAME>${RESET}"
    return
  fi

  echo -e "${BOLD}Stored API Keys${RESET}"
  echo -e "${DIM}Backend: $(secrets_backend)${RESET}"
  echo ""

  # Mask values in-shell (value never crosses a process boundary as argv).
  local key val n masked maxlen=0
  while IFS= read -r key; do [[ -n "$key" ]] && (( ${#key} > maxlen )) && maxlen=${#key}; done <<< "$names"
  while IFS= read -r key; do
    [[ -z "$key" ]] && continue
    val=$(secret_get "$key"); n=${#val}
    if (( n > 12 )); then
      masked="${val:0:4}$(printf '%*s' $((n - 8)) '' | tr ' ' '*')${val: -4}"
    else
      masked="$(printf '%*s' "$n" '' | tr ' ' '*')"
    fi
    printf "  %-${maxlen}s  %s\n" "$key" "$masked"
  done <<< "$names"

  echo ""
  echo -e "${DIM}Tip: Remove a key with${RESET} rack keys remove <KEY_NAME>"
}

# Remove a key
_keys_remove() {
  local key_name="$1"
  if [[ -z "$key_name" ]]; then
    error "Key name required. Usage: rack keys remove <KEY_NAME>"
  fi

  if ! secret_has "$key_name"; then
    error "Key '$key_name' not found"
  fi

  # Confirm removal
  read -rp "Remove key '$key_name'? [y/N]: " confirm
  if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
    echo "Cancelled."
    return
  fi

  # Remove from the active backend (keyring + index)
  secret_del "$key_name"
  audit_log "keys.remove" "$key_name"
  success "Removed key: $key_name"

  # Drop lifecycle metadata for the removed key
  _keys_touch_meta "$key_name" "removed"

  # Sync to all agent .env files
  _sync_keys_to_agents

  # Restart gateway
  info "Restarting OpenClaw gateway..."
  restart_gateway
}

# Rotate an existing key: replace its value and re-sync. Unlike `add`, the key
# MUST already exist — rotation is for replacing a leaked/expired credential.
_keys_rotate() {
  local key_name="$1"
  if [[ -z "$key_name" ]]; then
    error "Key name required. Usage: rack keys rotate <KEY_NAME>"
  fi

  if [[ ! "$key_name" =~ ^[A-Z][A-Z0-9_]*$ ]]; then
    error "Invalid key name. Use UPPERCASE_WITH_UNDERSCORES (e.g., ANTHROPIC_API_KEY)"
  fi

  # Must already exist (rotation replaces an existing credential, never creates)
  if ! secret_has "$key_name"; then
    error "Key '$key_name' not found. Use 'rack keys add $key_name' to create it."
  fi

  echo -e "${BOLD}Rotate API Key${RESET}"
  echo -e "Key name: ${CYAN}$key_name${RESET}"
  echo ""
  read -rsp "Enter NEW key value (hidden): " key_value
  echo ""

  if [[ -z "$key_value" ]]; then
    error "Key value cannot be empty"
  fi

  # Replace value (via environment — never interpolated into code) and stamp rotation
  RACK_KEY_VALUE="$key_value" secret_put "$key_name" || return 1
  _keys_touch_meta "$key_name" "rotated"
  audit_log "keys.rotate" "$key_name"
  success "Rotated key: $key_name"

  # Re-sync scoped keys and restart gateway
  _sync_keys_to_agents
  info "Restarting OpenClaw gateway to apply changes..."
  restart_gateway
}

# Determine an agent's model provider from its .rack-meta.json.
# Models are stored as "<provider>/<model>" (e.g. anthropic/claude-sonnet-4-6),
# so the provider is the prefix. Falls back to the default model's provider when
# the agent has no recorded model.
# Usage: _agent_provider <workspace-dir>  ->  echoes provider (e.g. "anthropic")
_agent_provider() {
  local workspace="$1"
  local meta="$workspace/.rack-meta.json"
  local model=""
  if [[ -f "$meta" ]]; then
    model=$(python3 -c "import json,sys
try:
    print(json.load(open(sys.argv[1])).get('model','') or '')
except Exception:
    print('')" "$meta" 2>/dev/null || echo "")
  fi
  [[ -z "$model" ]] && model="$DEFAULT_MODEL"
  printf '%s' "${model%%/*}"
}

# Sync secrets.json to all agent .env files, scoped to least privilege.
#
# Each agent receives only the provider API key its configured model needs
# (an anthropic agent gets ANTHROPIC_API_KEY, not OPENAI_API_KEY, etc.). Any
# secret whose name is not a known provider key is treated as a shared secret
# and synced to every agent. This limits the blast radius if one agent
# workspace is compromised — it no longer exposes every provider's key.
_sync_keys_to_agents() {
  # Materialise current secret values (from whichever backend) into a 0600 temp
  # the per-agent writer reads. For the keyring backend this is the only place
  # plaintext values surface, transiently — and they must be written to .env
  # regardless. For the file backend it is just a copy of secrets.json.
  local secrets_file
  secrets_file=$(mktemp)
  chmod 600 "$secrets_file"
  secret_export_json > "$secrets_file" 2>/dev/null

  # Nothing to sync if there are no keys.
  if ! python3 -c "import json,sys; sys.exit(0 if json.load(open(sys.argv[1])) else 1)" "$secrets_file" 2>/dev/null; then
    rm -f "$secrets_file"
    return
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
    local provider
    provider=$(_agent_provider "$workspace")

    # Create/update .env, scoped to the agent's provider. Paths and provider
    # arrive via argv; secrets are read inside Python (never interpolated into
    # source). The write is atomic (tmp + os.replace) and mode 0600.
    python3 - "$secrets_file" "$env_file" "$provider" <<'EOF'
import json, os, sys

secrets_path, env_file, provider = sys.argv[1], sys.argv[2], sys.argv[3]
with open(secrets_path) as f:
    all_secrets = json.load(f)

# Known provider API keys -> the provider that needs them. A secret not in this
# map is a custom/shared secret and goes to every agent.
PROVIDER_KEYS = {
    "ANTHROPIC_API_KEY": "anthropic",
    "OPENAI_API_KEY": "openai",
    "GOOGLE_AI_API_KEY": "google",
    "OPENROUTER_API_KEY": "openrouter",
}

def needed(name):
    owner = PROVIDER_KEYS.get(name)
    return True if owner is None else owner == provider

scoped = {k: v for k, v in all_secrets.items() if needed(k)}

# Preserve user-authored lines: anything that isn't a managed secret assignment
# or one of our header comments survives the rewrite.
preserved = []
if os.path.exists(env_file):
    with open(env_file) as f:
        for raw in f:
            line = raw.rstrip("\n")
            stripped = line.strip()
            if not stripped:
                continue
            key = stripped.split("=", 1)[0].strip() if "=" in stripped else ""
            if key in all_secrets:
                continue  # drop any managed secret line (scoped or not)
            if stripped.startswith("#") and (
                "Agent Environment Variables" in stripped
                or "Managed by rack keys" in stripped
                or "User-defined (preserved)" in stripped
            ):
                continue
            preserved.append(line)

tmp = env_file + ".tmp"
with open(tmp, "w") as f:
    f.write("# Agent Environment Variables\n")
    f.write("# Managed by rack keys - do not edit secret lines manually\n\n")
    for key, value in scoped.items():
        f.write(f"{key}={value}\n")
    if preserved:
        f.write("\n# User-defined (preserved)\n")
        for line in preserved:
            f.write(line + "\n")
os.chmod(tmp, 0o600)
os.replace(tmp, env_file)
EOF

    ((count++))
  done

  rm -f "$secrets_file"   # discard the transient plaintext materialisation
  [[ $count -gt 0 ]] && info "Synced keys to $count agent workspace(s) (scoped per provider)"
}

# Interactive setup wizard
_keys_setup() {
  header "API Keys Setup Wizard"
  echo ""
  echo "This wizard will help you configure API keys for OpenClaw agents."
  echo "Storage backend: ${CYAN}$(secrets_backend)${RESET}"
  echo ""

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
    if secret_has "$key_name"; then
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
      RACK_KEY_VALUE="$key_value" secret_put "$key_name"
      _keys_touch_meta "$key_name" "added"

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
    warn "Remember to restart gateway manually: ${GREEN}$(service_hint restart)${RESET}"
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

  if [[ -z "$(secret_names)" ]]; then
    error "No API keys found. Run: rack keys setup"
  fi

  header "Validate API Keys"
  echo ""

  # If specific key provided, validate just that one
  if [[ -n "$key_name" ]]; then
    _validate_single_key "$key_name"
    return
  fi

  # Otherwise validate all keys
  while IFS= read -r key; do
    [[ -z "$key" ]] && continue
    _validate_single_key "$key"
  done <<< "$(secret_names)"

  echo ""
  success "Validation complete"
  echo ""
  echo "${DIM}Note: Validation checks format only, not actual API access${RESET}"
  echo "${DIM}For full API testing, try using the keys with agents${RESET}"
}

_validate_single_key() {
  local key_name="$1"

  local key_value
  key_value=$(secret_get "$key_name")

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
  if [[ -z "$(secret_names)" ]]; then
    error "No API keys found. Run: rack keys setup"
  fi

  # Materialise values (backend-agnostic) into a 0600 temp, then emit exports.
  local blob; blob=$(mktemp); chmod 600 "$blob"
  secret_export_json > "$blob"
  python3 - "$blob" <<'PYEOF'
import json, sys
for key_name, key_value in json.load(open(sys.argv[1])).items():
    safe_value = key_value.replace("'", "'\\''")
    print(f"export {key_name}='{safe_value}'")
PYEOF
  rm -f "$blob"
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
