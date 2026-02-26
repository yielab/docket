#!/usr/bin/env bash
# JSON manipulation helpers - metadata reading/writing

# Read a field from the project's .rack-meta.json
meta_get() {
  local id="$1" field="$2" default="${3:-}"
  local meta="$PROJECTS_DIR/$id/$META_FILE"
  if [[ -f "$meta" ]]; then
    python3 -c "import json; d=json.load(open('$meta')); print(d.get('$field','$default'))" 2>/dev/null || echo "$default"
  else
    echo "$default"
  fi
}

# Write/update a field in .rack-meta.json
meta_set() {
  local id="$1" field="$2" value="$3"
  local meta="$PROJECTS_DIR/$id/$META_FILE"
  python3 - "$meta" "$field" "$value" <<'PY'
import json, sys, os
path, field, value = sys.argv[1], sys.argv[2], sys.argv[3]
data = {}
if os.path.exists(path):
    with open(path) as f:
        data = json.load(f)
data[field] = value
with open(path, 'w') as f:
    json.dump(data, f, indent=2)
PY
  chmod 600 "$meta"
}

# Get Telegram group ID bound to an agent (empty if none)
get_tg_binding() {
  local id="$1"
  python3 - "$CONFIG_FILE" "$id" <<'PY' 2>/dev/null || echo ""
import json, sys
config = json.load(open(sys.argv[1]))
for b in config.get("bindings", []):
    if b.get("agentId") == sys.argv[2]:
        print(b.get("match", {}).get("peer", {}).get("id", ""))
        sys.exit(0)
PY
}

# Append or replace binding in openclaw.json
upsert_binding() {
  local agent_id="$1" group_id="$2"
  python3 - "$CONFIG_FILE" "$agent_id" "$group_id" <<'PY'
import json, sys
path, agent_id, group_id = sys.argv[1], sys.argv[2], sys.argv[3]
with open(path) as f:
    config = json.load(f)
bindings = [b for b in config.get("bindings", [])
            if not (b.get("agentId") == agent_id or
                    b.get("match",{}).get("peer",{}).get("id") == group_id)]
bindings.append({"agentId": agent_id,
                 "match": {"channel": "telegram",
                           "peer": {"kind": "group", "id": group_id}}})
config["bindings"] = bindings
with open(path, "w") as f:
    json.dump(config, f, indent=2)
PY
}

# Remove binding for an agent from openclaw.json
remove_binding() {
  local agent_id="$1"
  python3 - "$CONFIG_FILE" "$agent_id" <<'PY'
import json, sys
path, agent_id = sys.argv[1], sys.argv[2]
with open(path) as f:
    config = json.load(f)
config["bindings"] = [b for b in config.get("bindings", [])
                      if b.get("agentId") != agent_id]
with open(path, "w") as f:
    json.dump(config, f, indent=2)
PY
}

# Remove agent from openclaw.json agents.list
remove_agent_config() {
  local agent_id="$1"
  python3 - "$CONFIG_FILE" "$agent_id" <<'PY'
import json, sys
path, agent_id = sys.argv[1], sys.argv[2]
with open(path) as f:
    config = json.load(f)
agents = config.get("agents", {})
agents["list"] = [a for a in agents.get("list", []) if a.get("id") != agent_id]
config["agents"] = agents
with open(path, "w") as f:
    json.dump(config, f, indent=2)
PY
}

# Check if agent is registered in openclaw.json
agent_registered() {
  local id="$1"
  python3 -c "
import json, sys
c = json.load(open('$CONFIG_FILE'))
ids = [a.get('id') for a in c.get('agents',{}).get('list',[])]
sys.exit(0 if '$id' in ids else 1)
" 2>/dev/null
}
