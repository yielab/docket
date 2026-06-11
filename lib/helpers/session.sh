#!/usr/bin/env bash
# Session key management - multi-project isolation

# Generate session key for multi-project isolation
# Format: agent:<agentId>:<projectKey>
# This prevents agents from mixing information across different projects
generate_session_key() {
  local id="$1"
  local project_key="${2:-default}"
  echo "agent:${id}:${project_key}"
}

# Extract project key from session coordinate
parse_session_key() {
  local session="$1"
  echo "$session" | awk -F: '{print $3}'
}

# Sync session key to OpenClaw agent metadata
# OpenClaw uses the agent.metadata field for custom properties
sync_session_key() {
  local agent_id="$1" session_key="$2"
  # The daemon owns openclaw.json; `openclaw agents add` creates it before we get
  # here. If it's genuinely absent there's nothing to sync into — warn and skip
  # rather than abort (so a fleet provision isn't halted by one missing config).
  if [[ ! -f "$CONFIG_FILE" ]]; then
    warn "Cannot sync session key for $agent_id — config missing: $CONFIG_FILE"
    return 0
  fi
  python3 - "$CONFIG_FILE" "$agent_id" "$session_key" <<'PY'
import json, sys
path, agent_id, session_key = sys.argv[1], sys.argv[2], sys.argv[3]
with open(path) as f:
    config = json.load(f)
for agent in config.get("agents", {}).get("list", []):
    if agent.get("id") == agent_id:
        if "metadata" not in agent:
            agent["metadata"] = {}
        agent["metadata"]["sessionKey"] = session_key
        agent["metadata"]["projectKey"] = session_key.split(":")[-1] if ":" in session_key else "default"
        break
with open(path, "w") as f:
    json.dump(config, f, indent=2)
PY
}
