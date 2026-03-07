#!/usr/bin/env bash
# Command: billing

cmd_billing() {
  header "Billing & Credits Status"
  echo ""

  # Check if Anthropic API key is configured
  local api_key
  api_key=$(python3 -c "
import json, os
config = json.load(open(os.path.expanduser('~/.openclaw/openclaw.json')))
providers = config.get('providers', {})
for name, cfg in providers.items():
    if 'anthropic' in name.lower() and 'apiKey' in cfg:
        print(cfg['apiKey'])
        break
" 2>/dev/null || echo "")

  if [[ -z "$api_key" ]]; then
    fail "No Anthropic API key configured"
    echo ""
    echo -e "${YELLOW}To configure:${RESET}"
    echo "  ${GREEN}openclaw config set \"providers.anthropic:claude.apiKey\" \"sk-ant-api03-YOUR-KEY\"${RESET}"
    echo ""
    echo -e "${DIM}Get your API key at: https://console.anthropic.com/settings/keys${RESET}"
    exit 1
  fi

  # Mask API key for display
  local masked_key="${api_key:0:12}...${api_key: -4}"
  success "API Key configured: $masked_key"
  echo ""

  # Try to check balance via Anthropic API
  # Note: Anthropic doesn't have a public /balance endpoint
  # We'll show usage instead and link to console

  echo -e "${BOLD}Current Usage (from local sessions):${RESET}"
  echo ""

  # Get usage from rack cost
  local total_cost
  total_cost=$(python3 -c "
import os, json, glob
total = 0.0
sessions_dirs = glob.glob(os.path.expanduser('~/.openclaw/agents/*/sessions'))
for sessions_dir in sessions_dirs:
    for session_file in glob.glob(os.path.join(sessions_dir, '*.jsonl')):
        try:
            with open(session_file) as f:
                for line in f:
                    try:
                        data = json.loads(line.strip())
                        if 'usage' in data and 'cost' in data['usage']:
                            total += float(data['usage']['cost'])
                    except:
                        pass
        except:
            pass
print(f'{total:.4f}')
" 2>/dev/null || echo "0.0000")

  if [[ "$total_cost" == "0.0000" ]]; then
    echo -e "  ${DIM}No usage data found${RESET}"
    echo -e "  ${DIM}(Sessions may be in different format or no API calls yet)${RESET}"
  else
    echo -e "  ${CYAN}Total Cost (All Time):${RESET} \$$total_cost"

    # Calculate daily average (rough estimate)
    local days_active
    days_active=$(find ~/.openclaw/agents/*/sessions -name "*.jsonl" 2>/dev/null | wc -l)
    if [[ "$days_active" -gt 0 ]]; then
      local avg_per_day
      avg_per_day=$(python3 -c "print(f'{${total_cost}/${days_active}:.4f}')" 2>/dev/null || echo "0.0000")
      echo -e "  ${DIM}Average per Session:${RESET} \$$avg_per_day"
    fi
  fi

  echo ""
  echo -e "${BOLD}Balance Check:${RESET}"
  echo -e "  ${YELLOW}⚠${RESET}  Anthropic API doesn't expose balance via API"
  echo -e "  ${CYAN}→${RESET}  Check your balance manually at:"
  echo ""
  echo -e "  ${GREEN}https://console.anthropic.com/settings/billing${RESET}"
  echo ""

  # Show current usage this month (from rack cost)
  echo -e "${BOLD}Usage This Month:${RESET}"
  echo ""

  # Use rack cost command
  if command -v rack &>/dev/null; then
    rack cost 2>/dev/null | grep -E "^[a-z-]+.*\$" | head -10 || echo -e "  ${DIM}No usage data${RESET}"
  else
    echo -e "  ${DIM}Run 'rack cost' to see usage breakdown${RESET}"
  fi

  echo ""
  echo -e "${BOLD}Recommendations:${RESET}"
  echo ""

  # Get total cost as number for comparison
  local cost_num
  cost_num=$(echo "$total_cost" | awk '{print $1}')

  if (( $(echo "$cost_num < 1.0" | bc -l 2>/dev/null || echo 0) )); then
    success "Usage is very low - you're being efficient!"
    echo -e "  ${DIM}Current rate: ~\$${total_cost}/month${RESET}"
    echo -e "  ${DIM}Recommended credits: \$20 (will last ~18+ months)${RESET}"
  elif (( $(echo "$cost_num < 10.0" | bc -l 2>/dev/null || echo 0) )); then
    echo -e "  ${YELLOW}✓${RESET} Moderate usage"
    echo -e "  ${DIM}Recommended credits: \$50 (will last several months)${RESET}"
  else
    warn "High usage detected"
    echo -e "  ${DIM}Recommended credits: \$100+ for sustained usage${RESET}"
    echo -e "  ${DIM}Consider using 'economy' profile for non-critical agents${RESET}"
  fi

  echo ""
  echo -e "${BOLD}Quick Actions:${RESET}"
  echo ""
  echo -e "  ${GREEN}1.${RESET} Add credits: ${CYAN}https://console.anthropic.com/settings/billing${RESET}"
  echo -e "  ${GREEN}2.${RESET} Check balance: ${CYAN}https://console.anthropic.com/settings/billing${RESET}"
  echo -e "  ${GREEN}3.${RESET} View usage: ${GREEN}rack cost${RESET}"
  echo -e "  ${GREEN}4.${RESET} Reduce costs: ${GREEN}rack profile <agent> economy${RESET}"
  echo ""
  echo -e "${DIM}After adding credits, restart gateway:${RESET}"
  echo -e "  ${GREEN}systemctl --user restart openclaw-gateway.service${RESET}"
}
