#!/usr/bin/env bash
# JSON manipulation helpers - metadata reading/writing

# ── Write-safety primitives (Phase 1) ─────────────────────────────────────────

# Atomically replace a JSON file with the content read from stdin.
# Refuses to write if stdin isn't valid JSON (so a failed producer can't truncate
# the target); keeps a rolling .bak; writes via tmp + os.replace; enforces 0600.
# Usage:  produce_new_json_on_stdout | json_atomic_write <file>
json_atomic_write() {
  # NB: -c (not `python3 - <<heredoc`) so stdin stays the piped JSON, not the script.
  python3 -c '
import json, os, sys, shutil
path = sys.argv[1]
raw = sys.stdin.read()
try:
    data = json.loads(raw)
except Exception as e:
    print(f"json_atomic_write: refusing to write invalid JSON to {path}: {e}", file=sys.stderr)
    sys.exit(1)
if os.path.exists(path):
    try:
        shutil.copy2(path, path + ".bak")
    except Exception:
        pass
tmp = path + ".tmp"
with open(tmp, "w") as f:
    json.dump(data, f, indent=2)
    f.write("\n")
os.chmod(tmp, 0o600)
os.replace(tmp, path)
' "$1"
}

# Run "$@" while holding an exclusive lock, so two concurrent docket invocations
# can't interleave a read-modify-write and lose an update. Only LEAF writers are
# wrapped (they never call each other), so the lock never nests/deadlocks.
# Falls back to running unlocked if flock or the lock file is unavailable.
with_docket_lock() {
  local lock="${OPENCLAW_DIR:-$HOME/.openclaw}/.docket.lock"
  if command -v flock >/dev/null 2>&1 && ( : >"$lock" ) 2>/dev/null; then
    ( flock -x -w 10 9 2>/dev/null || true; "$@" ) 9>"$lock"
  else
    "$@"
  fi
}

# Read a field from the project's .docket-meta.json.
# Missing file → default silently (normal). Present-but-unparseable → warn loudly
# to stderr (corruption shouldn't be silently masked) but still return the default
# so the command stays alive.
meta_get() {
  local id="$1" field="$2" default="${3:-}"
  local meta; meta="$(agent_workspace_dir "$id")/$META_FILE"
  [[ -f "$meta" ]] || { echo "$default"; return; }
  local out
  if out=$(python3 - "$meta" "$field" "$default" <<'PY'
import json, sys
path, field, default = sys.argv[1], sys.argv[2], sys.argv[3]
with open(path) as f:
    d = json.load(f)
print(d.get(field, default))
PY
  ); then
    echo "$out"
  else
    echo "docket: warning: cannot read ${meta} (corrupt JSON?); using default for '${field}'" >&2
    echo "$default"
  fi
}

# Write/update a field in .docket-meta.json (atomic + locked).
# Validates the field name and value against AGENT_SCHEMA (lib/core/schema.sh)
# before writing. Unknown fields and type/enum violations abort without writing.
# Set DOCKET_NO_SCHEMA_CHECK=1 to skip validation (internal bootstrap only).
meta_set() { with_docket_lock _meta_set "$@"; }
_meta_set() {
  local id="$1" field="$2" value="$3"
  local meta; meta="$(agent_workspace_dir "$id")/$META_FILE"

  # Schema validation — skip only during bootstrap (DOCKET_NO_SCHEMA_CHECK=1).
  if [[ "${DOCKET_NO_SCHEMA_CHECK:-0}" != "1" ]] && \
     [[ "$(type -t schema_field)" == "function" ]]; then
    local _desc; _desc=$(schema_field "$field" 2>/dev/null || true)
    if [[ -z "$_desc" ]]; then
      error "meta_set: unknown field '$field' (not in AGENT_SCHEMA); check for typos"
      return 1
    fi
    local _type; _type=$(printf '%s' "$_desc" | cut -f2)
    local _enum; _enum=$(printf '%s' "$_desc" | cut -f3)
    case "$_type" in
      number)
        # Allow empty string (field clear/unset). Non-empty must be a non-negative number.
        if [[ -n "$value" ]] && ! printf '%s' "$value" | python3 -c "import sys; v=sys.stdin.read().strip(); sys.exit(0 if float(v)>=0 else 1)" 2>/dev/null; then
          error "meta_set: field '$field' must be a non-negative number, got: $value"
          return 1
        fi
        ;;
      bool)
        # Accept "true", "false", or "" (empty = unset/false for optional bools like `paused`).
        if [[ "$value" != "true" && "$value" != "false" && "$value" != "" ]]; then
          error "meta_set: field '$field' must be 'true', 'false', or '' (unset), got: $value"
          return 1
        fi
        ;;
      enum)
        if [[ "$_enum" != "-" ]]; then
          local _valid=0
          local _opt
          IFS='|' read -ra _opts <<< "$_enum"
          for _opt in "${_opts[@]}"; do
            [[ "$value" == "$_opt" ]] && { _valid=1; break; }
          done
          if [[ "$_valid" -eq 0 ]]; then
            error "meta_set: field '$field' must be one of: ${_enum//|/, }; got: $value"
            return 1
          fi
        fi
        ;;
    esac
  fi

  python3 - "$meta" "$field" "$value" <<'PY' | json_atomic_write "$meta"
import json, sys, os
path, field, value = sys.argv[1], sys.argv[2], sys.argv[3]
data = {}
if os.path.exists(path):
    with open(path) as f:
        data = json.load(f)
data[field] = value
print(json.dumps(data, indent=2))
PY
}

# Get Telegram group ID bound to an agent (empty if none)
# Get peer ID for an agent binding on a specific channel (default: telegram)
get_channel_binding() {
  local id="$1" channel="${2:-telegram}"
  python3 - "$CONFIG_FILE" "$id" "$channel" <<'PY' 2>/dev/null || echo ""
import json, sys
config = json.load(open(sys.argv[1]))
agent_id, channel = sys.argv[2], sys.argv[3]
for b in config.get("bindings", []):
    if b.get("agentId") == agent_id and b.get("match", {}).get("channel") == channel:
        print(b.get("match", {}).get("peer", {}).get("id", ""))
        sys.exit(0)
PY
}

# Backwards-compat alias — callers that only care about Telegram still work
get_tg_binding() { get_channel_binding "$1" "telegram"; }

# Append or replace binding in openclaw.json (atomic + locked)
# upsert_binding <agent_id> <peer_id> [channel=telegram] [peer_kind=group]
upsert_binding() { with_docket_lock _upsert_binding "$@"; }
_upsert_binding() {
  local agent_id="$1" peer_id="$2" channel="${3:-telegram}" peer_kind="${4:-group}"
  python3 - "$CONFIG_FILE" "$agent_id" "$peer_id" "$channel" "$peer_kind" <<'PY' | json_atomic_write "$CONFIG_FILE"
import json, sys
path, agent_id, peer_id, channel, peer_kind = sys.argv[1:]
with open(path) as f:
    config = json.load(f)
bindings = [b for b in config.get("bindings", [])
            if not (b.get("agentId") == agent_id and
                    b.get("match", {}).get("channel") == channel)]
bindings.append({"agentId": agent_id,
                 "match": {"channel": channel,
                           "peer": {"kind": peer_kind, "id": peer_id}}})
config["bindings"] = bindings
print(json.dumps(config, indent=2))
PY
}

# Remove binding for an agent from openclaw.json (atomic + locked)
remove_binding() { with_docket_lock _remove_binding "$@"; }
_remove_binding() {
  local agent_id="$1"
  python3 - "$CONFIG_FILE" "$agent_id" <<'PY' | json_atomic_write "$CONFIG_FILE"
import json, sys
path, agent_id = sys.argv[1], sys.argv[2]
with open(path) as f:
    config = json.load(f)
config["bindings"] = [b for b in config.get("bindings", [])
                      if b.get("agentId") != agent_id]
print(json.dumps(config, indent=2))
PY
}

# Remove agent from openclaw.json agents.list (atomic + locked)
remove_agent_config() { with_docket_lock _remove_agent_config "$@"; }
_remove_agent_config() {
  local agent_id="$1"
  python3 - "$CONFIG_FILE" "$agent_id" <<'PY' | json_atomic_write "$CONFIG_FILE"
import json, sys
path, agent_id = sys.argv[1], sys.argv[2]
with open(path) as f:
    config = json.load(f)
agents = config.get("agents", {})
agents["list"] = [a for a in agents.get("list", []) if a.get("id") != agent_id]
config["agents"] = agents
print(json.dumps(config, indent=2))
PY
}

# ── Audited openclaw.json read/write path ─────────────────────────────────────

# Read a dotted-path value from openclaw.json
# Usage: oc_get "agents.defaults.model" [default]
oc_get() {
  local dotpath="$1" default="${2:-}"
  [[ -f "$CONFIG_FILE" ]] || { echo "$default"; return; }
  local out
  if out=$(python3 - "$CONFIG_FILE" "$dotpath" "$default" <<'PY'
import json, sys

def deep_get(obj, path, default):
    for key in path.split('.'):
        if isinstance(obj, dict):
            obj = obj.get(key)
        else:
            return default
        if obj is None:
            return default
    return obj

config = json.load(open(sys.argv[1]))
result = deep_get(config, sys.argv[2], sys.argv[3])
print(result if result is not None else sys.argv[3])
PY
  ); then
    echo "$out"
  else
    echo "docket: warning: cannot read ${CONFIG_FILE} (corrupt JSON?); using default for '${dotpath}'" >&2
    echo "$default"
  fi
}

# Write a value at a dotted path in openclaw.json (atomic + locked)
# Creates a rolling .bak before writing; validates JSON after write.
# Usage: oc_set "agents.defaults.model" '"anthropic/claude-sonnet-4-6"'
# The value must be valid JSON (strings need outer quotes).
oc_set() { with_docket_lock _oc_set "$@"; }
_oc_set() {
  local dotpath="$1" json_value="$2"
  python3 - "$CONFIG_FILE" "$dotpath" "$json_value" <<'PY'
import json, sys, os, shutil

path, dotpath, raw_value = sys.argv[1], sys.argv[2], sys.argv[3]

# Validate value is parseable JSON
try:
    value = json.loads(raw_value)
except json.JSONDecodeError as e:
    print(f"oc_set: invalid JSON value: {e}", file=sys.stderr)
    sys.exit(1)

# Rolling backup
bak = path + '.bak'
shutil.copy2(path, bak)

# Read, mutate, write
with open(path) as f:
    config = json.load(f)

keys = dotpath.split('.')
obj = config
for key in keys[:-1]:
    obj = obj.setdefault(key, {})
obj[keys[-1]] = value

tmp = path + '.tmp'
with open(tmp, 'w') as f:
    json.dump(config, f, indent=2)

# Verify the written file parses cleanly before replacing
try:
    json.load(open(tmp))
except json.JSONDecodeError as e:
    os.unlink(tmp)
    shutil.copy2(bak, path)  # restore from backup
    print(f"oc_set: write produced invalid JSON — restored from backup: {e}", file=sys.stderr)
    sys.exit(1)

os.replace(tmp, path)
PY
}

# Update model in BOTH openclaw.json (agents.list entry) and .docket-meta.json atomically.
# Returns 0 only if both writes succeed.
# Usage: set_agent_model <id> <model>
set_agent_model() {
  local id="$1" model="$2"

  # Update openclaw.json agents.list
  python3 - "$CONFIG_FILE" "$id" "$model" <<'PY'
import json, sys, os, shutil

path, agent_id, model = sys.argv[1], sys.argv[2], sys.argv[3]

bak = path + '.bak'
shutil.copy2(path, bak)

with open(path) as f:
    config = json.load(f)

updated = False
for agent in config.get('agents', {}).get('list', []):
    if agent.get('id') == agent_id:
        agent['model'] = model
        updated = True
        break

if not updated:
    print(f"set_agent_model: agent '{agent_id}' not found in agents.list", file=sys.stderr)
    sys.exit(1)

tmp = path + '.tmp'
with open(tmp, 'w') as f:
    json.dump(config, f, indent=2)

json.load(open(tmp))  # validate
os.replace(tmp, path)
PY
  local oc_exit=$?
  [[ "$oc_exit" -ne 0 ]] && return 1

  # Update .docket-meta.json
  meta_set "$id" "model" "$model"
}

# ── Agent registration ─────────────────────────────────────────────────────────

# Check if agent is registered in openclaw.json
agent_registered() {
  local id="$1"
  python3 - "$CONFIG_FILE" "$id" <<'PY' 2>/dev/null
import json, sys
with open(sys.argv[1]) as f:
    c = json.load(f)
ids = [a.get('id') for a in c.get('agents', {}).get('list', [])]
sys.exit(0 if sys.argv[2] in ids else 1)
PY
}
