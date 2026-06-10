#!/usr/bin/env bash
# Command: snapshot — emit JSON system state for dashboards / CI artifacts

cmd_snapshot() {
  local output_file=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --output|-o) output_file="$2"; shift 2 ;;
      *) shift ;;
    esac
  done

  local gw_status
  gw_status=$(systemctl --user is-active openclaw-gateway.service 2>/dev/null || echo "inactive")

  # Collect configured channel names
  local channels_json
  channels_json=$(python3 -c "
import json, sys
try:
    c = json.load(open('$CONFIG_FILE'))
    chs = list(c.get('channels', {}).keys())
    print(json.dumps(chs))
except Exception:
    print('[]')
" 2>/dev/null || echo "[]")

  # Build agents array (project + specialist)
  local agents_json
  agents_json=$(python3 - "$CONFIG_FILE" "$PROJECTS_DIR" "$OPENCLAW_DIR" <<'PY'
import json, os, sys, glob, re

config_path, projects_dir, openclaw_dir = sys.argv[1:]
try:
    with open(config_path) as f:
        config = json.load(f)
except Exception:
    config = {}

bindings = config.get("bindings", [])
agents_list = config.get("agents", {}).get("list", [])
registered_ids = {a["id"] for a in agents_list}

def agent_bindings(agent_id):
    return [
        {"channel": b["match"]["channel"],
         "peerId": b["match"].get("peer", {}).get("id", "")}
        for b in bindings if b.get("agentId") == agent_id
    ]

def read_meta(path):
    try:
        return json.load(open(path))
    except Exception:
        return {}

def last_activity(agent_id):
    mem_dir = os.path.join(openclaw_dir, "workspaces", "projects", agent_id, "memory")
    if not os.path.isdir(mem_dir):
        mem_dir = os.path.join(openclaw_dir, "workspaces", agent_id, "memory")
    if not os.path.isdir(mem_dir):
        return "never"
    logs = sorted(glob.glob(os.path.join(mem_dir, "*.md")), reverse=True)
    return os.path.basename(logs[0]).replace(".md", "") if logs else "never"

def aggregate_cost(agent_id):
    sessions_dir = os.path.join(openclaw_dir, "agents", agent_id, "sessions")
    total = 0.0
    if os.path.isdir(sessions_dir):
        for f in glob.glob(os.path.join(sessions_dir, "*.jsonl")):
            with open(f) as fh:
                for line in fh:
                    try:
                        d = json.loads(line)
                        usage = d.get("message", {}).get("usage", {})
                        cost = usage.get("cost", {})
                        total += cost.get("total", 0) if isinstance(cost, dict) else 0
                    except Exception:
                        pass
    return round(total, 6)

agents = []
total_cost = 0.0

# Project agents
if os.path.isdir(projects_dir):
    for d in sorted(os.listdir(projects_dir)):
        agent_dir = os.path.join(projects_dir, d)
        if not os.path.isdir(agent_dir):
            continue
        meta = read_meta(os.path.join(agent_dir, ".rack-meta.json"))
        cost = aggregate_cost(d)
        total_cost += cost
        agents.append({
            "id": d,
            "name": meta.get("name", d),
            "type": meta.get("type", "repo"),
            "kind": "project",
            "model": meta.get("model", ""),
            "registered": d in registered_ids,
            "bindings": agent_bindings(d),
            "lastActivity": last_activity(d),
            "costUsd": cost,
        })

# Specialist agents
specialists = ["manager", "programmer", "reviewer", "tester", "knowledge", "security"]
for spec in specialists:
    spec_dir = os.path.join(openclaw_dir, "workspaces", spec)
    if not os.path.isdir(spec_dir):
        continue
    meta = read_meta(os.path.join(spec_dir, ".rack-meta.json"))
    cost = aggregate_cost(spec)
    total_cost += cost
    agents.append({
        "id": spec,
        "name": meta.get("name", spec),
        "type": "specialist",
        "kind": "specialist",
        "model": meta.get("model", ""),
        "registered": spec in registered_ids,
        "bindings": agent_bindings(spec),
        "lastActivity": last_activity(spec),
        "costUsd": cost,
    })

print(json.dumps({"agents": agents, "totalCostUsd": round(total_cost, 6)}))
PY
)

  # Assemble final JSON
  local timestamp; timestamp=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
  local json
  json=$(python3 - "$timestamp" "$gw_status" "$channels_json" "$agents_json" <<'PY'
import json, sys
timestamp, gateway, channels_raw, agents_raw = sys.argv[1:]
channels = json.loads(channels_raw)
agents_data = json.loads(agents_raw)
out = {
    "timestamp": timestamp,
    "gateway": gateway,
    "channels": channels,
    "agents": agents_data["agents"],
    "totalCostUsd": agents_data["totalCostUsd"],
}
print(json.dumps(out, indent=2))
PY
)

  if [[ -n "$output_file" ]]; then
    echo "$json" > "$output_file"
    success "Snapshot written to $output_file"
  else
    echo "$json"
  fi
}
