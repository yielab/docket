#!/usr/bin/env bash
# Global configuration - paths, colors, models, Telegram mappings

# ─── Paths ────────────────────────────────────────────────────────────────────
# Overridable via environment for testing/CI; default to the standard locations.
OPENCLAW_DIR="${OPENCLAW_DIR:-$HOME/.openclaw}"
PROJECTS_DIR="${PROJECTS_DIR:-$OPENCLAW_DIR/workspaces/projects}"
CONFIG_FILE="${CONFIG_FILE:-$OPENCLAW_DIR/openclaw.json}"
LOG_FILE="${LOG_FILE:-/tmp/openclaw/openclaw-$(date +%Y-%m-%d).log}"
SITES_DIR="${SITES_DIR:-$HOME/Sites}"
DEFAULT_MODEL="anthropic/claude-sonnet-4-6"
META_FILE=".docket-meta.json"  # stored inside each project workspace
MODEL_REGISTRY_FILE="${MODEL_REGISTRY_FILE:-$OPENCLAW_DIR/docket-models.json}"

# Version of the SOUL/AGENTS/TOOLS/HEARTBEAT workspace templates emitted by
# _create_workspace. Stamped into each agent's .docket-meta.json at creation /
# rebuild; `docket doctor` flags agents whose stamp is older (prompt drift) and
# suggests `docket maintain <id> rebuild`. Bump this (integer) whenever the
# template text in lib/helpers/workspace.sh changes materially.
TEMPLATE_VERSION="${TEMPLATE_VERSION:-3}"

# ─── Expected Telegram group names per agent ─────────────────────────────────
# Maps agent ID → the Telegram group name the user should create.
# Used by "docket list" to show setup status and by "docket doctor" for auditing.
declare -A TELEGRAM_GROUP_NAMES=(
  [manager]="Manager"
)

# ─── Colors ───────────────────────────────────────────────────────────────────
# Use ANSI-C quoting ($'…') so the variables hold real ESC bytes, not the
# literal 4-char string "\033[…". This makes colors render through ANY emitter
# — bare `echo`, `cat <<HEREDOC`, `printf` — not just `echo -e`.
RED=$'\033[0;31m';  GREEN=$'\033[0;32m';  YELLOW=$'\033[1;33m'
CYAN=$'\033[0;36m'; BLUE=$'\033[0;34m';  BOLD=$'\033[1m';  DIM=$'\033[2m'; RESET=$'\033[0m'
TICK="${GREEN}✓${RESET}"; CROSS="${RED}✗${RESET}"; WARN="${YELLOW}⚠${RESET}"; ARROW="${CYAN}→${RESET}"

# ─── Model rank anchors (deprecated tier names) ──────────────────────────────
# economy/standard/premium are NO LONGER user-facing tiers — the role→model
# policy below is. The anchors remain as (a) the cheap/strong class each role's
# built-in default derives from, (b) the fallback rank list (premium→standard→
# economy), and (c) resolution targets for deprecated tier-name input.
declare -A MODEL_PROFILES=(
  [economy]="anthropic/claude-haiku-4-5"
  [standard]="anthropic/claude-sonnet-4-6"
  [premium]="anthropic/claude-opus-4-6"
)

# ─── Agent taxonomy ───────────────────────────────────────────────────────────
# Specialist agents are shared team members created by `docket install`; project
# agents (kind: project) are created by `docket add` with type repo|task.
DOCKET_SPECIALISTS=(manager programmer reviewer tester knowledge security)

# Roles the model policy knows about: the six specialist roles plus the two
# project-agent types (a project agent's `type` doubles as its policy role).
DOCKET_ROLES=(manager programmer reviewer tester knowledge security repo task)

# ─── Role→model policy (the user-facing model concept) ───────────────────────
# Each role's built-in default derives from a class anchor, chosen for token
# efficiency: cheap = high-volume / low reasoning-density work, strong =
# reasoning-dense work. Stronger models (opus-class) are an explicit per-agent
# pin (`docket profile <id> <provider/model>`), never a standing default.
declare -A ROLE_CLASS=(
  [manager]="cheap"     [reviewer]="cheap" [tester]="cheap"
  [knowledge]="cheap"   [task]="cheap"
  [programmer]="strong" [security]="strong" [repo]="strong"
)

declare -A ROLE_WHY=(
  [manager]="high-volume coordination, shallow reasoning"
  [reviewer]="triage and review, low reasoning density"
  [tester]="run tests and report"
  [knowledge]="retrieval and summarization"
  [task]="project default for task agents"
  [programmer]="code generation"
  [security]="audit depth"
  [repo]="project default for repo agents"
)

# Filled from the class anchors by _init_role_models, then overlaid by the
# user registry's `roles:` map in load_model_registry.
declare -A ROLE_MODELS=()

_init_role_models() {
  local role
  for role in "${DOCKET_ROLES[@]}"; do
    case "${ROLE_CLASS[$role]:-strong}" in
      cheap)  ROLE_MODELS[$role]="${MODEL_PROFILES[economy]}" ;;
      *)      ROLE_MODELS[$role]="${MODEL_PROFILES[standard]}" ;;
    esac
  done
}

# Resolve a role to its policy model. Unknown role → DEFAULT_MODEL.
resolve_role_model() {
  local role="$1"
  echo "${ROLE_MODELS[$role]:-$DEFAULT_MODEL}"
}

is_role() { [[ -n "${ROLE_CLASS[${1:-}]:-}" ]]; }

is_specialist() {
  local s
  for s in "${DOCKET_SPECIALISTS[@]}"; do [[ "$s" == "${1:-}" ]] && return 0; done
  return 1
}

# Workspace dir for any agent — project agents live under $PROJECTS_DIR,
# specialists directly under $OPENCLAW_DIR/workspaces. Defaults to the project
# location for ids that don't exist yet (creation path).
agent_workspace_dir() {
  local id="$1"
  if [[ -d "$PROJECTS_DIR/$id" ]]; then
    echo "$PROJECTS_DIR/$id"
  elif is_specialist "$id" && [[ -d "$OPENCLAW_DIR/workspaces/$id" ]]; then
    echo "$OPENCLAW_DIR/workspaces/$id"
  else
    echo "$PROJECTS_DIR/$id"
  fi
}

# ─── Model pricing (input:output:cache_read:cache_write per million tokens) ──
# Covers all built-in presets. Unknown models report "n/a" — never $0.00.
# Field order matches _estimate_cost(): cache_READ before cache_WRITE.
#
# These prices are a hand-maintained SNAPSHOT, not a live feed. Recorded spend in
# `docket cost` comes from the daemon's session logs and does NOT use this table;
# this table only powers comparative *estimates* (e.g. "cost on a cheaper model").
# Treat estimates as directional. Update procedure: internal-docs/MODEL-AGNOSTIC-NOTES.md.
# Bump MODEL_PRICING_AS_OF whenever you edit a price so the CLI can flag staleness.
MODEL_PRICING_AS_OF="2026-06-11"   # OpenClaw 2026.2.23 catalog
declare -A MODEL_PRICING=(
  # Anthropic
  ["anthropic/claude-haiku-4-5"]="0.80:4.00:0.08:1.00"
  ["anthropic/claude-haiku-3-5"]="0.80:4.00:0.08:1.00"
  ["anthropic/claude-sonnet-4-6"]="3.00:15.00:0.30:3.75"
  ["anthropic/claude-sonnet-4-5"]="3.00:15.00:0.30:3.75"
  ["anthropic/claude-opus-4-6"]="15.00:75.00:1.50:18.75"
  # OpenAI
  ["openai/gpt-4.1-nano"]="0.10:0.40::"
  ["openai/gpt-4.1-mini"]="0.40:1.60::"
  ["openai/gpt-4.1"]="2.00:8.00::"
  ["openai/gpt-4o"]="2.50:10.00::"
  # Google
  ["google/gemini-2.0-flash-lite"]="0.075:0.30::"
  ["google/gemini-2.5-flash"]="0.15:0.60::"
  ["google/gemini-2.5-flash-lite"]="0.10:0.40::"
)

# ─── Local providers (free, no API key required) ──────────────────────────────
# The OpenClaw daemon does not support Ollama/llama.cpp local endpoints.
# "Local" in docket means OpenRouter free-tier — zero per-token cost, but an
# OpenRouter API key (free to create at openrouter.ai) is still needed.
# This list is used to suppress provider-key warnings for truly keyless providers.
LOCAL_PROVIDERS=()

# ─── Model registry overlay ──────────────────────────────────────────────────
# Reads $MODEL_REGISTRY_FILE if it exists and overlays DEFAULT_MODEL,
# MODEL_PROFILES (rank anchors), ROLE_MODELS, and MODEL_PRICING. Called once at
# the end of this file. A legacy registry with only a `profiles:` key still
# works: roles re-derive from the overridden anchors, then any `roles:` entries
# overlay on top. Corrupt registry → warn on stderr, keep built-in defaults.
load_model_registry() {
  if [[ ! -f "$MODEL_REGISTRY_FILE" ]]; then
    _init_role_models
    return 0
  fi

  local errfile overlay
  errfile=$(mktemp)
  overlay=$(python3 - "$MODEL_REGISTRY_FILE" 2>"$errfile" <<'PY'
import json, sys, re
path = sys.argv[1]
try:
    reg = json.load(open(path))
except Exception as e:
    sys.stderr.write(f"docket-models.json is corrupt ({e}) — using built-in defaults\n")
    sys.exit(0)

ID_RE = re.compile(r'^[a-z0-9_-]+/[A-Za-z0-9._:/-]+$')
out = []

if isinstance(reg.get('default'), str) and ID_RE.match(reg['default']):
    out.append('default\t' + reg['default'])

for tier in ('economy', 'standard', 'premium'):
    m = reg.get('profiles', {}).get(tier)
    if isinstance(m, str) and ID_RE.match(m):
        out.append(f'profile\t{tier}\t{m}')

for role, m in reg.get('roles', {}).items():
    if isinstance(m, str) and ID_RE.match(m):
        out.append(f'role\t{role}\t{m}')

for key, p in reg.get('pricing', {}).items():
    if ID_RE.match(key) and isinstance(p, dict):
        inp = p.get('input', '')
        outp = p.get('output', '')
        if inp and outp:
            cw = p.get('cacheWrite', '')
            cr = p.get('cacheRead', '')
            out.append(f'pricing\t{key}\t{inp}:{outp}:{cw}:{cr}')

print('\n'.join(out))
PY
  ) || true

  if [[ -s "$errfile" ]]; then
    echo "⚠  docket-models.json: $(cat "$errfile")" >&2
    rm -f "$errfile"
    _init_role_models
    return 0
  fi
  rm -f "$errfile"

  # Pass 1: default model, rank anchors, pricing.
  while IFS=$'\t' read -r kind a b; do
    [[ -z "$kind" ]] && continue
    case "$kind" in
      default)  DEFAULT_MODEL="$a" ;;
      profile)  MODEL_PROFILES["$a"]="$b" ;;
      pricing)  MODEL_PRICING["$a"]="$b" ;;
    esac
  done <<< "$overlay"

  # Re-derive built-in role defaults from the (possibly overridden) anchors,
  # then pass 2: explicit per-role overrides win.
  _init_role_models
  while IFS=$'\t' read -r kind a b; do
    [[ "$kind" == "role" ]] || continue
    if is_role "$a"; then
      ROLE_MODELS["$a"]="$b"
    else
      echo "⚠  docket-models.json: unknown role '$a' ignored (valid: ${DOCKET_ROLES[*]})" >&2
    fi
  done <<< "$overlay"
}

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

# Apply user registry overrides (no-op if the file doesn't exist)
load_model_registry
