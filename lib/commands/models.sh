#!/usr/bin/env bash
# Command: models — view and change rack's tier→model mapping

# ─── Provider presets ─────────────────────────────────────────────────────────
# Pinned from verified OpenClaw 2026.2.23 catalog (see MODEL-AGNOSTIC-NOTES.md).
# Format: preset:tier → model-id  (looked up via _preset_model)
declare -A _MODEL_PRESET_TABLE=(
  # anthropic (default)
  ["anthropic:economy"]="anthropic/claude-haiku-4-5"
  ["anthropic:standard"]="anthropic/claude-sonnet-4-6"
  ["anthropic:premium"]="anthropic/claude-opus-4-6"
  ["anthropic:key"]="ANTHROPIC_API_KEY"
  ["anthropic:cost"]="paid"
  ["anthropic:note"]="Default. Strongest tool-use support."

  # openai
  ["openai:economy"]="openai/gpt-4.1-nano"
  ["openai:standard"]="openai/gpt-4.1-mini"
  ["openai:premium"]="openai/gpt-4.1"
  ["openai:key"]="OPENAI_API_KEY"
  ["openai:cost"]="paid"
  ["openai:note"]="GPT-4.1 family."

  # google
  ["google:economy"]="google/gemini-2.0-flash-lite"
  ["google:standard"]="google/gemini-2.5-flash"
  ["google:premium"]="google/gemini-2.5-flash"
  ["google:key"]="GOOGLE_AI_API_KEY"
  ["google:cost"]="paid"
  ["google:note"]="No distinct premium Gemini model yet; standard=premium."

  # openrouter-free  (zero per-token cost on free-tier models; key still required)
  ["openrouter-free:economy"]="openrouter/google/gemini-flash-1.5-8b"
  ["openrouter-free:standard"]="openrouter/meta-llama/llama-3.3-70b-instruct"
  ["openrouter-free:premium"]="openrouter/deepseek/deepseek-r1"
  ["openrouter-free:key"]="OPENROUTER_API_KEY"
  ["openrouter-free:cost"]="free"
  ["openrouter-free:note"]="Zero per-token cost on free-tier models. Free account at openrouter.ai."

  # openrouter (paid, access to many providers)
  ["openrouter:economy"]="openrouter/google/gemini-flash-1.5-8b"
  ["openrouter:standard"]="openrouter/anthropic/claude-3.5-haiku"
  ["openrouter:premium"]="openrouter/anthropic/claude-3-opus"
  ["openrouter:key"]="OPENROUTER_API_KEY"
  ["openrouter:cost"]="paid"
  ["openrouter:note"]="Unified access to 200+ models via one key."
)

_KNOWN_PRESETS=(anthropic openai google openrouter-free openrouter)

_preset_model() { echo "${_MODEL_PRESET_TABLE[${1}:${2}]:-}"; }

# ─── Helpers ──────────────────────────────────────────────────────────────────

_models_pricing_label() {
  local model="$1"
  local entry="${MODEL_PRICING[$model]:-}"
  if [[ -z "$entry" ]]; then
    echo "n/a"
    return
  fi
  local inp out
  IFS=: read -r inp out _ _ <<< "$entry"
  printf "\$%.2f/\$%.2f" "$inp" "$out"
}

_models_source_label() {
  local role="$1" model="$2"
  local reg_model
  reg_model=$(python3 - "$MODEL_REGISTRY_FILE" "$role" <<'PY' 2>/dev/null
import json, sys
path, role = sys.argv[1], sys.argv[2]
try:
    reg = json.load(open(path))
    print(reg.get('roles', {}).get(role, ''))
except Exception:
    pass
PY
)
  if [[ "$reg_model" == "$model" ]]; then
    echo "user"
  else
    echo "builtin"
  fi
}

_write_registry() {
  # Write overrides to rack-models.json atomically.
  # Args: "role.<role>=model", "tier.<tier>=model" (anchor), "default=model",
  # or "reset".
  python3 - "$MODEL_REGISTRY_FILE" "$@" <<'PY'
import json, sys, os, tempfile

path = sys.argv[1]
args = sys.argv[2:]

ROLES = ('manager', 'programmer', 'reviewer', 'tester', 'knowledge',
         'security', 'repo', 'task')

try:
    reg = json.load(open(path)) if os.path.exists(path) else {}
except Exception:
    reg = {}

if 'reset' in args:
    reg = {}
else:
    for arg in args:
        k, _, v = arg.partition('=')
        if k == 'default':
            reg['default'] = v
        elif k.startswith('role.') and k[5:] in ROLES:
            reg.setdefault('roles', {})[k[5:]] = v
        elif k.startswith('tier.') and k[5:] in ('economy', 'standard', 'premium'):
            reg.setdefault('profiles', {})[k[5:]] = v

# Atomic write
dir_ = os.path.dirname(path) or '.'
fd, tmp = tempfile.mkstemp(dir=dir_)
try:
    with os.fdopen(fd, 'w') as f:
        json.dump(reg, f, indent=2)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)
except Exception as e:
    os.unlink(tmp)
    sys.stderr.write(str(e) + '\n')
    sys.exit(1)
PY
}

# ─── Subcommand: list ─────────────────────────────────────────────────────────

_models_list() {
  local fmt="  %-12s  %-38s  %-14s  %-8s  %s\n"
  header "Role→model policy"
  echo ""
  printf "$fmt" "ROLE" "MODEL" "PRICE" "SOURCE" "WHY"
  printf "$fmt" "----" "-----" "-----" "------" "---"
  local role
  for role in "${RACK_ROLES[@]}"; do
    local model="${ROLE_MODELS[$role]:-$DEFAULT_MODEL}"
    local price
    price=$(_models_pricing_label "$model")
    local source
    source=$(_models_source_label "$role" "$model")
    printf "$fmt" "$role" "$model" "$price" "$source" "${ROLE_WHY[$role]:-}"
  done
  echo ""
  printf "  %-12s  %s\n" "default" "$DEFAULT_MODEL"
  printf "  %-12s  %s\n" "fallback" "${MODEL_PROFILES[premium]} → ${MODEL_PROFILES[standard]} → ${MODEL_PROFILES[economy]}"
  echo ""
  printf "  Registry file: %s\n" "${MODEL_REGISTRY_FILE}"
  if [[ -f "$MODEL_REGISTRY_FILE" ]]; then
    printf "  (user overrides active)\n"
  else
    printf "  (no user overrides — using built-in defaults)\n"
  fi
  echo ""
  echo "Change: rack models set <role|default> <provider/model>"
  echo "Preset: rack models preset [anthropic|openai|google|openrouter-free|openrouter]"
  echo "Pin one agent instead: rack profile <id> <provider/model>   (back: rack profile <id> default)"
}

# ─── Subcommand: set ──────────────────────────────────────────────────────────

_models_set() {
  local key="$1" model="$2"
  [[ -z "$key" || -z "$model" ]] && \
    error "Usage: rack models set <role|default> <provider/model>
Roles: ${RACK_ROLES[*]}"

  local validated
  validated=$(validate_model "$model") || exit 1

  local -a writes=()
  local -a touched_roles=()
  if [[ "$key" == "default" ]]; then
    writes+=("default=${validated}")
  elif is_role "$key"; then
    writes+=("role.${key}=${validated}")
    touched_roles+=("$key")
  elif [[ -n "${MODEL_PROFILES[$key]:-}" ]]; then
    # Deprecated tier key: update the rank anchor and every role in that class.
    warn "Tier names are deprecated — the role policy is the source of truth."
    local role
    case "$key" in
      economy)
        for role in "${RACK_ROLES[@]}"; do
          [[ "${ROLE_CLASS[$role]}" == "cheap" ]] && { writes+=("role.${role}=${validated}"); touched_roles+=("$role"); }
        done
        ;;
      standard)
        for role in "${RACK_ROLES[@]}"; do
          [[ "${ROLE_CLASS[$role]}" == "strong" ]] && { writes+=("role.${role}=${validated}"); touched_roles+=("$role"); }
        done
        ;;
      premium)
        info "premium is a fallback anchor only — no role uses it by default. Pin an agent instead: rack profile <id> <provider/model>"
        ;;
    esac
    writes+=("tier.${key}=${validated}")
    [[ "${#touched_roles[@]}" -gt 0 ]] && \
      info "Mapped to role(s): ${touched_roles[*]}"
  else
    error "Unknown key '$key'. Use a role (${RACK_ROLES[*]}) or 'default'."
  fi

  _write_registry "${writes[@]}" || error "Failed to write registry."

  # Apply to live arrays
  load_model_registry

  success "$key → $validated"
  if [[ "${MODEL_PRICING[$validated]:-}" == "" ]]; then
    info "No pricing data for $validated — cost will show as n/a."
  fi
  audit_log "models.set" "${key}=${validated}"

  # Live policy: re-resolve every policy-following agent (pins untouched).
  if [[ "${#touched_roles[@]}" -gt 0 ]]; then
    echo ""
    info "Re-resolving policy-following agents..."
    reapply_role_policy
    restart_gateway_if_dirty
  fi
}

# ─── Subcommand: preset ───────────────────────────────────────────────────────

_models_preset() {
  local preset="${1:-}"

  if [[ -z "$preset" ]]; then
    header "Provider presets"
    echo ""
    printf "  %-18s  %-8s  %-20s  %s\n" "PRESET" "COST" "KEY NEEDED" "DESCRIPTION"
    printf "  %-18s  %-8s  %-20s  %s\n" "------" "----" "----------" "-----------"
    for p in "${_KNOWN_PRESETS[@]}"; do
      local cost="${_MODEL_PRESET_TABLE[${p}:cost]:-?}"
      local key="${_MODEL_PRESET_TABLE[${p}:key]:-none}"
      local note="${_MODEL_PRESET_TABLE[${p}:note]:-}"
      local marker=""
      [[ "$p" == "anthropic" ]] && marker=" (default)"
      printf "  %-18s  %-8s  %-20s  %s\n" "${p}${marker}" "$cost" "$key" "$note"
    done
    echo ""
    echo "Apply: rack models preset <name>"
    echo ""
    echo "Free options: openrouter-free (zero per-token cost, free account at openrouter.ai)"
    return
  fi

  # Validate preset name
  local valid=0
  for p in "${_KNOWN_PRESETS[@]}"; do [[ "$p" == "$preset" ]] && valid=1 && break; done
  [[ "$valid" -eq 0 ]] && error "Unknown preset '$preset'. Valid: ${_KNOWN_PRESETS[*]}"

  local econ std prem key cost note
  econ=$(_preset_model "$preset" economy)
  std=$(_preset_model  "$preset" standard)
  prem=$(_preset_model "$preset" premium)
  key="${_MODEL_PRESET_TABLE[${preset}:key]:-}"
  cost="${_MODEL_PRESET_TABLE[${preset}:cost]:-paid}"
  note="${_MODEL_PRESET_TABLE[${preset}:note]:-}"

  # Map the preset's cheap/strong classes onto the role policy.
  local -a writes=("tier.economy=${econ}" "tier.standard=${std}" "tier.premium=${prem}" "default=${std}")
  local role cheap_roles="" strong_roles=""
  for role in "${RACK_ROLES[@]}"; do
    if [[ "${ROLE_CLASS[$role]}" == "cheap" ]]; then
      writes+=("role.${role}=${econ}"); cheap_roles+="$role "
    else
      writes+=("role.${role}=${std}"); strong_roles+="$role "
    fi
  done

  echo ""
  info "Applying preset: $preset"
  echo "  ${cheap_roles% }"
  echo "    → $econ"
  echo "  ${strong_roles% }"
  echo "    → $std"
  echo "  fallback ceiling → $prem"
  if [[ "$cost" == "free" ]]; then
    echo "  cost → free per-token (zero cost on free-tier models)"
  else
    echo "  cost → paid"
  fi
  [[ -n "$note" ]] && echo "  note → $note"
  echo ""

  _write_registry "${writes[@]}" || error "Failed to write registry."
  load_model_registry

  success "Preset '$preset' applied."
  audit_log "models.preset" "$preset"

  # Live policy: re-resolve every policy-following agent (pins untouched).
  echo ""
  info "Re-resolving policy-following agents..."
  reapply_role_policy
  restart_gateway_if_dirty

  # Key check
  if [[ -n "$key" ]]; then
    local key_present=0
    python3 - "$OPENCLAW_DIR/secrets.json" "$key" <<'PY' 2>/dev/null && key_present=1
import json, sys
path, name = sys.argv[1], sys.argv[2]
try:
    s = json.load(open(path))
    sys.exit(0 if name in s else 1)
except Exception:
    sys.exit(1)
PY
    if [[ "$key_present" -eq 0 ]]; then
      echo ""
      warn "API key $key is not stored yet."
      echo "  Add it: rack keys add $key <your-key>"
      if [[ "$preset" == "openrouter-free" || "$preset" == "openrouter" ]]; then
        echo "  Get one: https://openrouter.ai/keys (free account available)"
      fi
    fi
  fi

  echo ""
  info "Pinned agents kept their model. Pin or unpin one agent:"
  echo "  rack profile <id> <provider/model>   # pin"
  echo "  rack profile <id> default            # follow the role policy again"
}

# ─── Subcommand: reset ────────────────────────────────────────────────────────

_models_reset() {
  if [[ ! -f "$MODEL_REGISTRY_FILE" ]]; then
    info "No user overrides found (already using built-in defaults)."
    return
  fi

  echo ""
  warn "This will remove all user model overrides and restore the built-in role policy (Anthropic defaults)."
  echo ""
  read -r -p "Continue? [y/N] " _confirm
  if [[ "$_confirm" != "y" && "$_confirm" != "Y" ]]; then
    info "Aborted."
    return
  fi

  _write_registry "reset" || error "Failed to write registry."
  rm -f "$MODEL_REGISTRY_FILE"
  load_model_registry
  success "Restored built-in model defaults."
  audit_log "models.reset" "restored-built-ins"

  echo ""
  info "Re-resolving policy-following agents..."
  reapply_role_policy
  restart_gateway_if_dirty
}

# ─── Entry point ──────────────────────────────────────────────────────────────

cmd_models() {
  local sub="${1:-list}"
  shift || true

  case "$sub" in
    list|ls|"")  _models_list "$@" ;;
    set)         _models_set "$@" ;;
    preset)      _models_preset "$@" ;;
    reset)       _models_reset "$@" ;;
    *)
      error "Unknown models subcommand '$sub'.
Usage:
  rack models                            # show role→model policy
  rack models set <role> <model>         # change a role's model (roles: ${RACK_ROLES[*]})
  rack models preset [name]              # list or apply a provider preset
  rack models reset                      # restore built-in defaults"
      ;;
  esac
}
