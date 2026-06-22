#!/usr/bin/env bash
# Command: policies — manage and test guardrail policies.
#
# docket policies list               List installed policies
# docket policies show <id>          Show one policy
# docket policies init               Install baseline policies to $POLICIES_DIR
# docket policies test <hook> <role> "<text>"   Dry-run the evaluator

cmd_policies() {
  local subcommand="${1:-list}"
  shift || true
  case "$subcommand" in
    list)           _policies_list ;;
    show)           _policies_show "$@" ;;
    init)           _policies_init ;;
    test)           _policies_test "$@" ;;
    -h|--help)      _policies_help ;;
    *)              _policies_help ;;
  esac
}

_policies_help() {
  header "docket policies"
  echo ""
  echo "  docket policies list                        List installed policies"
  echo "  docket policies show <id>                   Show one policy"
  echo "  docket policies init                        Install baseline policies"
  echo "  docket policies test <hook> <role> \"<text>\" Dry-run evaluator"
  echo ""
  echo "  Policy directory: $POLICIES_DIR"
  echo "  Hooks: pre_input | pre_tool_call | pre_output"
  echo "  Actions: allow | warn | redact | require_approval | block"
  echo ""
}

_policies_list() {
  header "Guardrail Policies"
  echo ""

  if [[ ! -d "$POLICIES_DIR" ]] || [[ -z "$(ls "$POLICIES_DIR"/*.json 2>/dev/null)" ]]; then
    warn "No policies installed."
    info "Run: docket policies init"
    echo ""
    return 0
  fi

  printf "  %-30s %-16s %-16s %s\n" "ID" "HOOK" "ACTION" "DESCRIPTION"
  printf "  %s\n" "$(printf '─%.0s' {1..80})"

  for f in "$POLICIES_DIR"/*.json; do
    [[ -f "$f" ]] || continue
    python3 - "$f" <<'PY'
import json, sys
try:
    p = json.load(open(sys.argv[1]))
    pid  = p.get("id", "?")[:28]
    hook = p.get("hook", "?")[:14]
    act  = p.get("action", "?")[:14]
    desc = p.get("description", "")[:45]
    print(f"  {pid:<30} {hook:<16} {act:<16} {desc}")
except Exception as e:
    print(f"  [parse error: {e}]")
PY
  done
  echo ""
  dim "  Policy files in $POLICIES_DIR"
  echo ""
}

_policies_show() {
  local id="${1:-}"
  [[ -z "$id" ]] && error "Usage: docket policies show <id>"

  local found=""
  for f in "$POLICIES_DIR"/*.json; do
    [[ -f "$f" ]] || continue
    fid=$(python3 -c "import json; print(json.load(open('$f')).get('id',''))" 2>/dev/null)
    [[ "$fid" == "$id" ]] && { found="$f"; break; }
  done

  if [[ -z "$found" ]]; then
    fail "Policy not found: $id"
    return 1
  fi

  python3 -m json.tool "$found"
}

_policies_init() {
  local template_dir="$LIB_DIR/templates/policies"

  if [[ ! -d "$template_dir" ]]; then
    fail "Policy templates not found at $template_dir"
    return 1
  fi

  mkdir -p "$POLICIES_DIR" || error "Cannot create policies dir: $POLICIES_DIR"
  chmod 700 "$POLICIES_DIR" 2>/dev/null || true

  local installed=0 skipped=0
  for f in "$template_dir"/*.json; do
    [[ -f "$f" ]] || continue
    local dest="$POLICIES_DIR/$(basename "$f")"
    if [[ -f "$dest" ]]; then
      dim "  skip (exists): $(basename "$f")"
      skipped=$((skipped + 1))
    else
      cp "$f" "$dest"
      chmod 600 "$dest" 2>/dev/null || true
      success "installed: $(basename "$f")"
      installed=$((installed + 1))
    fi
  done

  echo ""
  if [[ "$installed" -gt 0 ]]; then
    success "Installed $installed baseline polic$(( installed == 1 ? 'y' : 'ies' ))."
  fi
  [[ "$skipped" -gt 0 ]] && dim "Skipped $skipped (already present). Delete to reinstall."
  echo ""
  info "Policies active at: $POLICIES_DIR"
  info "Test: docket policies test pre_tool_call programmer \"rm -rf /tmp\""
}

_policies_test() {
  local hook="${1:-}" role="${2:-}" text="${3:-}"
  if [[ -z "$hook" || -z "$role" || -z "$text" ]]; then
    error "Usage: docket policies test <hook> <role> \"<text>\""
  fi

  local valid_hooks="pre_input pre_tool_call pre_output"
  local ok=0
  for h in $valid_hooks; do [[ "$h" == "$hook" ]] && ok=1; done
  [[ "$ok" -eq 0 ]] && error "Unknown hook '$hook'. Valid: $valid_hooks"

  info "Evaluating policies (dry-run, no traces emitted)..."
  local action
  action=$(policy_test "$hook" "$role" "$text")

  echo ""
  printf "  Hook:   %s\n" "$hook"
  printf "  Role:   %s\n" "$role"
  printf "  Text:   %.80s\n" "$text"
  echo ""

  case "$action" in
    allow)            printf "  Result: ${GREEN}allow${RESET}\n" ;;
    warn)             printf "  Result: ${YELLOW}warn${RESET}\n" ;;
    redact)           printf "  Result: ${YELLOW}redact${RESET}\n" ;;
    require_approval) printf "  Result: ${CYAN}require_approval${RESET}\n" ;;
    block)            printf "  Result: ${RED}block${RESET}\n" ;;
    *)                printf "  Result: %s\n" "$action" ;;
  esac
  echo ""
}
