#!/usr/bin/env bash
# Global configuration - paths, colors, models, Telegram mappings

# ─── Paths ────────────────────────────────────────────────────────────────────
OPENCLAW_DIR="$HOME/.openclaw"
PROJECTS_DIR="$OPENCLAW_DIR/workspaces/projects"
CONFIG_FILE="$OPENCLAW_DIR/openclaw.json"
LOG_FILE="/tmp/openclaw/openclaw-$(date +%Y-%m-%d).log"
SITES_DIR="$HOME/Sites"
DEFAULT_MODEL="anthropic/claude-sonnet-4-6"
META_FILE=".rack-meta.json"  # stored inside each project workspace

# ─── Expected Telegram group names per agent ─────────────────────────────────
# Maps agent ID → the Telegram group name the user should create.
# Used by "rack list" to show setup status and by "rack doctor" for auditing.
declare -A TELEGRAM_GROUP_NAMES=(
  [coreapp]="Core App"
  [sensorapp]="Sensor App"
  [corpbot]="Corp Bot"
  [demo]="Demo Project"
  [marketing]="Example Marketing"
  [sideproject]="Side Project"
  [manager]="Manager"
)

# ─── Colors ───────────────────────────────────────────────────────────────────
RED='\033[0;31m';  GREEN='\033[0;32m';  YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BLUE='\033[0;34m';  BOLD='\033[1m';  DIM='\033[2m'; RESET='\033[0m'
TICK="${GREEN}✓${RESET}"; CROSS="${RED}✗${RESET}"; WARN="${YELLOW}⚠${RESET}"; ARROW="${CYAN}→${RESET}"

# ─── Model profiles ───────────────────────────────────────────────────────────
# Map tier names to full model identifiers
declare -A MODEL_PROFILES=(
  [economy]="anthropic/claude-haiku-4-5"
  [standard]="anthropic/claude-sonnet-4-6"
  [premium]="anthropic/claude-opus-4-6"
)

# ─── Model pricing (input:output:cache_write:cache_read per million tokens) ──
declare -A MODEL_PRICING=(
  ["anthropic/claude-haiku-4-5"]="0.80:4.00:0.08:1.00"
  ["anthropic/claude-haiku-3-5"]="0.80:4.00:0.08:1.00"
  ["anthropic/claude-sonnet-4-6"]="3.00:15.00:0.30:3.75"
  ["anthropic/claude-sonnet-4-5"]="3.00:15.00:0.30:3.75"
  ["anthropic/claude-opus-4-6"]="15.00:75.00:1.50:18.75"
)

# ─── Cost enforcement thresholds ─────────────────────────────────────────────
RUNAWAY_TURNS_THRESHOLD=200   # sessions with more turns than this trigger a warning
RUNAWAY_COST_THRESHOLD=20     # sessions costing more than this (USD) trigger a warning

# Resolve a profile name to a model ID, or return the input as-is if already a model
resolve_model() {
  local input="$1"
  if [[ -n "${MODEL_PROFILES[$input]:-}" ]]; then
    echo "${MODEL_PROFILES[$input]}"
  else
    echo "$input"
  fi
}

# Get the profile name for a model ID (or "custom" if not a standard profile)
model_to_profile() {
  local model="$1"
  for profile in "${!MODEL_PROFILES[@]}"; do
    if [[ "${MODEL_PROFILES[$profile]}" == "$model" ]]; then
      echo "$profile"
      return
    fi
  done
  echo "custom"
}
