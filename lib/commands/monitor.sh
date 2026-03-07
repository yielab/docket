#!/usr/bin/env bash
# lib/commands/monitor.sh — Real-time cost monitoring and logging

cmd_monitor() {
  local subcmd="${1:-status}"
  shift

  case "$subcmd" in
    status)    _monitor_status "$@" ;;
    log)       _monitor_log "$@" ;;
    alerts)    _monitor_alerts "$@" ;;
    dashboard) _monitor_dashboard "$@" ;;
    export)    _monitor_export "$@" ;;
    *)
      error "Unknown monitor command: $subcmd
  rack monitor status      Show current usage and limits
  rack monitor log [id]    Show interaction log for agent
  rack monitor alerts      Configure cost alerts
  rack monitor dashboard   Real-time cost dashboard
  rack monitor export      Export usage data to CSV"
      ;;
  esac
}

# Show current status
_monitor_status() {
  header "Cost Monitor — Current Status"

  # Get total cost from all agents
  local total_cost
  total_cost=$(python3 << 'PYEOF'
import json, glob, os

agents_dir = os.path.expanduser('~/.openclaw/agents')
total = 0.0

for agent_dir in glob.glob(f"{agents_dir}/*/sessions"):
    for session_file in glob.glob(f"{agent_dir}/*.jsonl"):
        try:
            with open(session_file, 'r') as f:
                for line in f:
                    try:
                        data = json.loads(line)
                        usage = data.get('usage', {})
                        i_tok = usage.get('input_tokens', 0)
                        o_tok = usage.get('output_tokens', 0)
                        c_read = usage.get('cache_read_input_tokens', 0)
                        c_write = usage.get('cache_creation_input_tokens', 0)
                        cost = (i_tok * 3 + o_tok * 15 + c_write * 3.75 + c_read * 0.30) / 1_000_000
                        total += cost
                    except:
                        pass
        except:
            pass

print(f"{total:.2f}")
PYEOF
  )

  # Check if we have tier information
  local tier_file="$HOME/.openclaw/.tier-info.json"
  local monthly_limit=100  # Default: Tier 1
  local tier="1 (estimated)"

  if [[ -f "$tier_file" ]]; then
    tier=$(python3 -c "import json; print(json.load(open('$tier_file')).get('tier', '1'))")
    monthly_limit=$(python3 -c "import json; print(json.load(open('$tier_file')).get('monthly_limit', 100))")
  fi

  # Calculate percentage
  local pct
  pct=$(python3 -c "print(int($total_cost / $monthly_limit * 100))")

  # Color based on usage
  local color="$GREEN"
  [[ $pct -gt 50 ]] && color="$YELLOW"
  [[ $pct -gt 80 ]] && color="$RED"

  echo
  info "Current Tier: $tier"
  info "Monthly Limit: \$$monthly_limit"
  echo
  echo -e "${color}Current Usage: \$$total_cost ($pct%)${RESET}"
  echo -e "${DIM}Remaining: \$$(python3 -c "print($monthly_limit - $total_cost)")${RESET}"

  # Progress bar
  local bar_length=50
  local filled=$((pct * bar_length / 100))
  local empty=$((bar_length - filled))

  echo
  printf "["
  printf "%${filled}s" | tr ' ' '█'
  printf "%${empty}s" | tr ' ' '░'
  printf "] %d%%\n" "$pct"

  # Show breakdown by agent
  echo
  header "Top 5 Agents by Cost"
  echo

  # Get agent costs
  python3 << 'PYEOF'
import json
import os
import glob

agents_dir = os.path.expanduser('~/.openclaw/agents')
costs = []

for agent_dir in glob.glob(f"{agents_dir}/*/sessions"):
    agent_id = os.path.basename(os.path.dirname(agent_dir))
    total_cost = 0
    total_tokens = 0

    for session_file in glob.glob(f"{agent_dir}/*.jsonl"):
        try:
            with open(session_file, 'r') as f:
                for line in f:
                    try:
                        data = json.loads(line)
                        usage = data.get('usage', {})

                        # Calculate cost
                        input_tok = usage.get('input_tokens', 0)
                        output_tok = usage.get('output_tokens', 0)
                        cache_read = usage.get('cache_read_input_tokens', 0)
                        cache_write = usage.get('cache_creation_input_tokens', 0)

                        # Sonnet-4-6 pricing
                        cost = (input_tok * 3 + output_tok * 15 + cache_write * 3.75 + cache_read * 0.30) / 1_000_000
                        total_cost += cost
                        total_tokens += input_tok + output_tok + cache_read + cache_write
                    except:
                        pass
        except:
            pass

    if total_cost > 0:
        costs.append((agent_id, total_cost, total_tokens))

# Sort by cost
costs.sort(key=lambda x: x[1], reverse=True)

print(f"{'Agent':<25} {'Cost':<12} {'Total Tokens'}")
print("-" * 60)
for agent_id, cost, tokens in costs[:5]:
    print(f"{agent_id:<25} ${cost:<11.4f} {tokens:,}")
PYEOF

  echo
  dim "Last updated: $(date '+%Y-%m-%d %H:%M:%S')"
  echo
  dim "Tip: Run 'rack monitor dashboard' for real-time monitoring"
  dim "     Run 'rack monitor alerts' to configure cost alerts"
}

# Show interaction log
_monitor_log() {
  local id="${1:-}"
  [[ -z "$id" ]] && id=$(pick_project "Select agent to view logs")

  local agent_dir="$OPENCLAW_AGENTS_DIR/$id/sessions"
  [[ ! -d "$agent_dir" ]] && fail "No sessions found for $id"

  header "Interaction Log — $id"
  echo

  # Show last 20 interactions
  python3 << PYEOF
import json
import glob
import os
from datetime import datetime

agent_dir = "$agent_dir"
interactions = []

for session_file in glob.glob(f"{agent_dir}/*.jsonl"):
    try:
        with open(session_file, 'r') as f:
            for line in f:
                try:
                    data = json.loads(line)
                    usage = data.get('usage', {})
                    timestamp = data.get('timestamp', '')

                    input_tok = usage.get('input_tokens', 0)
                    output_tok = usage.get('output_tokens', 0)
                    cache_read = usage.get('cache_read_input_tokens', 0)
                    cache_write = usage.get('cache_creation_input_tokens', 0)

                    cost = (input_tok * 3 + output_tok * 15 + cache_write * 3.75 + cache_read * 0.30) / 1_000_000

                    interactions.append({
                        'timestamp': timestamp,
                        'input': input_tok,
                        'output': output_tok,
                        'cache_r': cache_read,
                        'cache_w': cache_write,
                        'cost': cost
                    })
                except:
                    pass
    except:
        pass

# Sort by timestamp
interactions.sort(key=lambda x: x['timestamp'], reverse=True)

print(f"{'Timestamp':<20} {'In':<8} {'Out':<8} {'Cache R':<10} {'Cache W':<10} {'Cost'}")
print("-" * 80)

for i in interactions[:20]:
    ts = i['timestamp'][:19] if i['timestamp'] else 'N/A'
    print(f"{ts:<20} {i['input']:<8,} {i['output']:<8,} {i['cache_r']:<10,} {i['cache_w']:<10,} \${i['cost']:.4f}")

if len(interactions) > 20:
    print(f"\n... and {len(interactions) - 20} more interactions")

print(f"\nTotal interactions: {len(interactions)}")
PYEOF
}

# Configure cost alerts
_monitor_alerts() {
  header "Cost Alerts Configuration"
  echo

  local alerts_file="$HOME/.openclaw/.cost-alerts.json"

  # Check if alerts file exists
  if [[ -f "$alerts_file" ]]; then
    info "Current alerts:"
    cat "$alerts_file" | python3 -m json.tool
    echo
  fi

  # Prompt for configuration
  echo "Configure cost alerts:"
  echo
  echo "  1. Daily limit (\$ threshold)"
  echo "  2. Weekly limit (\$ threshold)"
  echo "  3. Monthly limit (\$ threshold)"
  echo "  4. Per-agent limit (\$ threshold)"
  echo "  5. Disable alerts"
  echo

  read -rp "Select option (1-5): " choice

  case "$choice" in
    1)
      read -rp "Daily limit (\$): " daily_limit
      python3 -c "import json; json.dump({'daily_limit': $daily_limit}, open('$alerts_file', 'w'))"
      success "Daily alert set to \$$daily_limit"
      ;;
    2)
      read -rp "Weekly limit (\$): " weekly_limit
      python3 -c "import json; json.dump({'weekly_limit': $weekly_limit}, open('$alerts_file', 'w'))"
      success "Weekly alert set to \$$weekly_limit"
      ;;
    3)
      read -rp "Monthly limit (\$): " monthly_limit
      python3 -c "import json; json.dump({'monthly_limit': $monthly_limit}, open('$alerts_file', 'w'))"
      success "Monthly alert set to \$$monthly_limit"
      ;;
    4)
      read -rp "Per-agent limit (\$): " agent_limit
      python3 -c "import json; json.dump({'agent_limit': $agent_limit}, open('$alerts_file', 'w'))"
      success "Per-agent alert set to \$$agent_limit"
      ;;
    5)
      rm -f "$alerts_file"
      success "Alerts disabled"
      ;;
    *)
      error "Invalid option"
      ;;
  esac
}

# Real-time dashboard
_monitor_dashboard() {
  header "Real-Time Cost Dashboard"
  echo
  info "Press Ctrl+C to exit"
  echo

  while true; do
    clear
    _monitor_status
    sleep 5
  done
}

# Export usage data
_monitor_export() {
  local output_file="${1:-usage-export-$(date +%Y-%m-%d).csv}"

  info "Exporting usage data to $output_file..."

  python3 << PYEOF > "$output_file"
import json
import glob
import os
from datetime import datetime

agents_dir = os.path.expanduser('~/.openclaw/agents')

print("agent_id,timestamp,input_tokens,output_tokens,cache_read,cache_write,cost,model")

for agent_dir in glob.glob(f"{agents_dir}/*/sessions"):
    agent_id = os.path.basename(os.path.dirname(agent_dir))

    for session_file in glob.glob(f"{agent_dir}/*.jsonl"):
        try:
            with open(session_file, 'r') as f:
                for line in f:
                    try:
                        data = json.loads(line)
                        usage = data.get('usage', {})
                        timestamp = data.get('timestamp', '')
                        model = data.get('model', 'unknown')

                        input_tok = usage.get('input_tokens', 0)
                        output_tok = usage.get('output_tokens', 0)
                        cache_read = usage.get('cache_read_input_tokens', 0)
                        cache_write = usage.get('cache_creation_input_tokens', 0)

                        cost = (input_tok * 3 + output_tok * 15 + cache_write * 3.75 + cache_read * 0.30) / 1_000_000

                        print(f"{agent_id},{timestamp},{input_tok},{output_tok},{cache_read},{cache_write},{cost:.6f},{model}")
                    except Exception as e:
                        pass
        except Exception as e:
            pass
PYEOF

  success "Exported to $output_file"
  info "Rows: $(wc -l < "$output_file")"
}
