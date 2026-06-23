#!/usr/bin/env bash
# Command: add

# Core provisioning shared by interactive `docket add` and declarative
# `docket add --from <file>`. Creates the workspace, stamps metadata, registers
# the agent with the daemon, and syncs its session key. Does NOT wire Telegram,
# restart the gateway, or print a summary — callers own those so the declarative
# path can batch a single restart across a whole fleet.
# Args: id type name codebase stack model description [projectKey=default] [budgetUsd] [source=interactive]
_provision_agent() {
  local id="$1" type="$2" name="$3" codebase="$4" stack="$5" model="$6" \
        description="$7" projectkey="${8:-default}" budget="${9:-}" source="${10:-interactive}"

  # Model intent: empty or policy-matching model → follow the role policy
  # (type doubles as the policy role); anything else is an explicit pin.
  local policy_model; policy_model=$(resolve_role_model "$type")
  local model_source="pinned"
  if [[ -z "$model" || "$model" == "$policy_model" ]]; then
    model="$policy_model"
    model_source="policy"
  fi

  _create_workspace "$id" "$type" "$name" "$codebase" "$stack" "$description" "$model"

  # Save metadata (all fields needed for deep reset / regeneration)
  meta_set "$id" "kind"        "project"
  meta_set "$id" "type"        "$type"
  meta_set "$id" "name"        "$name"
  meta_set "$id" "codebase"    "$codebase"
  meta_set "$id" "stack"       "$stack"
  meta_set "$id" "model"       "$model"
  meta_set "$id" "modelSource" "$model_source"
  meta_set "$id" "description" "$description"
  meta_set "$id" "created"     "$(date -Iseconds)"
  meta_set "$id" "sessionKey"  "$(generate_session_key "$id" "$projectkey")"
  meta_set "$id" "projectKey"  "$projectkey"
  [[ -n "$budget" && "$budget" != "0" ]] && meta_set "$id" "budgetUsd" "$budget"

  # Create work directory for task-type projects (no fixed codebase)
  if [[ "$type" == "task" ]]; then
    mkdir -p "$SITES_DIR/$id"
  fi

  # Register agent with openclaw
  openclaw agents add "$id" \
    --workspace "$PROJECTS_DIR/$id" \
    --model "$model" \
    --non-interactive 2>&1 | grep -v "^$" || true
  audit_log "agent.add" "$id model=$model source=$source"

  # Sync session key to OpenClaw config
  local session_key; session_key=$(meta_get "$id" "sessionKey" "agent:${id}:${projectkey}")
  sync_session_key "$id" "$session_key"
  dbg "Session key synced to OpenClaw: $session_key"

  # Surface missing model auth now — agents authenticate via OpenClaw auth
  # profiles (openclaw models auth), not docket secrets. Without a usable
  # profile the agent registers but its first LLM request fails. Non-fatal.
  if ! openclaw_has_model_auth; then
    warn "No usable Claude auth profile — '$id' can't reply until you set one up: docket auth"
  fi
}

# Parse a declarative agent spec file into TSV (one line per agent). Accepts JSON
# (stdlib, always) or YAML (when PyYAML is installed). The document may be a list
# of agents, a `{agents: [...]}` mapping, or a single agent mapping. Emits fields
# in a fixed order; `~` in codebase is expanded. Exit codes: 2 parse/shape error,
# 3 YAML requested but PyYAML missing.
_parse_agent_spec() {
  python3 - "$1" <<'PY'
import sys, json, os
path = sys.argv[1]
try:
    text = open(path).read()
except OSError as e:
    sys.stderr.write("cannot read %s: %s\n" % (path, e)); sys.exit(2)

data = None
try:
    data = json.loads(text)
except Exception:
    try:
        import yaml
    except ImportError:
        sys.stderr.write("PyYAML not installed — use a JSON spec or: pip install pyyaml\n")
        sys.exit(3)
    try:
        data = yaml.safe_load(text)
    except Exception as e:
        sys.stderr.write("parse error: %s\n" % e); sys.exit(2)

if isinstance(data, dict) and "agents" in data:
    agents = data["agents"]
elif isinstance(data, dict):
    agents = [data]
elif isinstance(data, list):
    agents = data
else:
    sys.stderr.write("spec must be a mapping or a list of agents\n"); sys.exit(2)

if not isinstance(agents, list):
    sys.stderr.write("'agents' must be a list\n"); sys.exit(2)

# Fields are joined with the unit separator (\x1f), not a tab: tab is an IFS
# whitespace char, so bash `read` would collapse empty leading/middle fields.
US = "\x1f"

def cell(v):
    return "" if v is None else str(v).replace(US, " ").replace("\n", " ")

out = []
for a in agents:
    if not isinstance(a, dict):
        continue
    cb = a.get("codebase", "") or ""
    if cb:
        cb = os.path.expanduser(str(cb))
    fields = [a.get("id", ""), a.get("type", "task") or "task", a.get("name", ""),
              cb, a.get("stack", ""), a.get("model", ""), a.get("description", ""),
              a.get("telegram", ""), a.get("budgetUsd", ""),
              a.get("projectKey", "default") or "default"]
    out.append(US.join(cell(f) for f in fields))
sys.stdout.write("\n".join(out))
PY
}

# Declarative provisioning: provision every agent described in a spec file.
# Idempotent — agents whose workspace already exists are skipped, so a fleet
# file is safe to re-apply. Restarts the gateway once at the end iff any agent
# was Telegram-wired.
_add_from_file() {
  local spec="$1"
  [[ -n "$spec" ]] || error "Usage: docket add --from <agents.yaml|agents.json>"
  [[ -f "$spec" ]] || error "Spec file not found: $spec"
  command -v python3 >/dev/null 2>&1 || error "python3 is required to parse spec files."

  local parsed rc
  parsed=$(_parse_agent_spec "$spec"); rc=$?
  if [[ "$rc" -ne 0 ]]; then
    error "Could not parse $spec (exit $rc). Provide valid JSON, or install PyYAML for .yaml."
  fi
  [[ -z "$parsed" ]] && error "No agents defined in $spec"

  header "Declarative provisioning — $spec"
  echo ""

  local added=0 skipped=0 wired=0
  local id type name codebase stack model description telegram budget projectkey
  while IFS=$'\x1f' read -r id type name codebase stack model description telegram budget projectkey; do
    # Skip blank lines from the parser.
    [[ -z "$id" && -z "$name" ]] && continue

    [[ -z "$id" ]] && id=$(slugify "$name")
    id=$(slugify "$id")
    [[ -z "$name" ]] && name="$id"
    [[ -z "$type" ]] && type="task"
    [[ -z "$model" ]] && model=$(resolve_role_model "$type")
    [[ -z "$projectkey" ]] && projectkey="default"
    [[ -z "$description" ]] && description="No description provided."

    if [[ "$type" != "repo" && "$type" != "task" ]]; then
      fail "  $id: invalid type '$type' (expected repo|task) — skipped"
      continue
    fi
    if [[ -d "$PROJECTS_DIR/$id" ]]; then
      warn "  $id: already exists — skipped"
      skipped=$(( skipped + 1 ))
      continue
    fi

    # Auto-detect stack for repo agents when the codebase exists and none given.
    if [[ "$type" == "repo" && -z "$stack" && -n "$codebase" && -d "$codebase" ]]; then
      stack=$(detect_stack "$codebase")
    fi
    if [[ "$type" == "repo" && -n "$codebase" && ! -d "$codebase" ]]; then
      warn "  $id: codebase path not found ($codebase) — provisioning anyway"
    fi

    _provision_agent "$id" "$type" "$name" "$codebase" "$stack" "$model" \
      "$description" "$projectkey" "$budget" "declarative"
    added=$(( added + 1 ))

    if [[ -n "$telegram" ]]; then
      _wire_group "$id" "$telegram"
      wired=$(( wired + 1 ))
    fi
    success "  Provisioned: $id ($type, $model)${budget:+, budget \$$budget}"
  done <<< "$parsed"

  [[ "$wired" -gt 0 ]] && restart_gateway

  echo ""
  success "Done — $added added, $skipped skipped."
}

cmd_add() {
  # Declarative path: docket add --from <file>
  local from=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --from)   from="${2:-}"; shift 2 ;;
      --from=*) from="${1#--from=}"; shift ;;
      *)        shift ;;
    esac
  done
  if [[ -n "$from" ]]; then
    _add_from_file "$from"
    return $?
  fi

  header "Add Project Agent"
  echo ""

  # Type
  echo -e "${BOLD}Project type:${RESET}"
  echo "  1) repo   — codebase in ~/Sites (active development)"
  echo "  2) task   — web research, files, automation (no fixed codebase)"
  echo ""
  read -rp "Type [1/2]: " TYPE_INPUT
  case "$TYPE_INPUT" in
    1|repo) PROJECT_TYPE="repo" ;;
    2|task) PROJECT_TYPE="task" ;;
    *) error "Invalid. Use 1 or 2." ;;
  esac

  # Display name + slug
  echo ""
  read -rp "Display name (e.g. 'My Website'): " DISPLAY_NAME
  [[ -z "$DISPLAY_NAME" ]] && error "Display name required."

  DEFAULT_SLUG=$(slugify "$DISPLAY_NAME")
  read -rp "Agent ID [$DEFAULT_SLUG]: " AGENT_ID_INPUT
  AGENT_ID="${AGENT_ID_INPUT:-$DEFAULT_SLUG}"
  AGENT_ID=$(slugify "$AGENT_ID")

  [[ -d "$PROJECTS_DIR/$AGENT_ID" ]] && error "Project '$AGENT_ID' already exists. Use: docket repair $AGENT_ID"

  # Codebase
  CODEBASE_PATH=""
  DETECTED_STACK=""
  if [[ "$PROJECT_TYPE" == "repo" ]]; then
    # Best-effort fuzzy match: first dir under $SITES_DIR whose name contains the
    # slugified display name (case-insensitive). Glob loop instead of ls|grep so
    # odd filenames and regex metacharacters are handled literally.
    local _needle _base
    _needle=$(echo "$DISPLAY_NAME" | tr ' ' '-' | tr '[:upper:]' '[:lower:]')
    CLOSEST=""
    for _d in "$SITES_DIR"/*/; do
      [[ -d "$_d" ]] || continue
      _base=$(basename "$_d")
      if [[ "${_base,,}" == *"$_needle"* ]]; then CLOSEST="$_base"; break; fi
    done
    DEFAULT_PATH="$SITES_DIR/${CLOSEST:-$DISPLAY_NAME}"
    read -rp "Codebase path [$DEFAULT_PATH]: " PATH_INPUT
    CODEBASE_PATH="${PATH_INPUT:-$DEFAULT_PATH}"
    if [[ -d "$CODEBASE_PATH" ]]; then
      DETECTED_STACK=$(detect_stack "$CODEBASE_PATH")
      info "Detected stack: $DETECTED_STACK"
    else
      warn "Path not found: $CODEBASE_PATH"
    fi
  fi

  read -rp "Description: " DESCRIPTION
  [[ -z "$DESCRIPTION" ]] && DESCRIPTION="No description provided."

  TECH_STACK=""
  if [[ "$PROJECT_TYPE" == "repo" ]]; then
    read -rp "Stack [${DETECTED_STACK:-unknown}]: " STACK_INPUT
    TECH_STACK="${STACK_INPUT:-$DETECTED_STACK}"
  fi

  # Default comes from the role policy for this agent type; accepting it means
  # the agent follows the policy, typing a model ID pins it.
  ROLE_DEFAULT=$(resolve_role_model "$PROJECT_TYPE")
  read -rp "Model [policy: $ROLE_DEFAULT]: " MODEL_INPUT
  if [[ -n "$MODEL_INPUT" ]]; then
    MODEL=$(validate_model "$MODEL_INPUT") || exit 1
  else
    MODEL="$ROLE_DEFAULT"
  fi

  # Telegram
  echo ""
  header "Telegram group (Enter to skip)"
  _show_unbound_groups
  read -rp "Group ID (e.g. -1001234567890): " TG_GROUP_ID

  # Build workspace, stamp metadata, register, sync session key.
  _provision_agent "$AGENT_ID" "$PROJECT_TYPE" "$DISPLAY_NAME" \
    "$CODEBASE_PATH" "$TECH_STACK" "$MODEL" "$DESCRIPTION" "default" "" "interactive"
  success "Agent '$AGENT_ID' registered"

  # Telegram
  if [[ -n "${TG_GROUP_ID:-}" ]]; then
    _wire_group "$AGENT_ID" "$TG_GROUP_ID"
    restart_gateway
  else
    _print_wire_instructions "$AGENT_ID"
  fi

  _print_summary "$AGENT_ID" "$PROJECT_TYPE" "$CODEBASE_PATH" "${TG_GROUP_ID:-}"
}
