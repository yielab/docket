#!/usr/bin/env bash
# Command: team — Manage specialist agents and RACK architecture

cmd_team() {
  local subcommand="${1:-status}"
  shift || true

  case "$subcommand" in
    status)
      _team_status
      ;;
    upgrade)
      _team_upgrade
      ;;
    check)
      _team_check
      ;;
    roles)
      _team_roles
      ;;
    delegate)
      _team_delegate "$@"
      ;;
    queue)
      _team_queue
      ;;
    done)
      _team_done "$@"
      ;;
    init)
      warn "'team init' is deprecated. Use 'rack install' instead."
      ;;
    *)
      _team_help
      ;;
  esac
}

_team_help() {
  header "Team Management"
  echo ""
  echo "Manage specialist agents with RACK architecture"
  echo ""
  echo -e "${BOLD}Usage:${RESET}"
  echo "  rack team status              Show specialist agent health"
  echo "  rack team upgrade             Upgrade specialists to RACK templates"
  echo "  rack team check               Verify all specialists exist"
  echo "  rack team roles               Show agent roles and responsibilities"
  echo ""
  echo -e "${BOLD}Task Delegation:${RESET}"
  echo "  rack team delegate \"<task>\"   Add task to manager queue"
  echo "  rack team delegate --priority high \"<task>\"  High-priority task"
  echo "  rack team queue               Show pending tasks"
  echo "  rack team done <task-id>      Mark task as complete"
  echo ""
}

_team_status() {
  header "Specialist Team Status"
  echo ""

  local specialists=("manager" "programmer" "reviewer" "tester" "knowledge" "security")

  for spec in "${specialists[@]}"; do
    local workspace="$OPENCLAW_DIR/workspaces/$spec"

    if [[ ! -d "$workspace" ]]; then
      printf "  ${RED}✗${RESET} %-12s Not installed\n" "$spec"
      continue
    fi

    # Check if SOUL.md exists
    if [[ ! -f "$workspace/SOUL.md" ]]; then
      printf "  ${YELLOW}⚠${RESET} %-12s Missing SOUL.md\n" "$spec"
      continue
    fi

    # Check if RACK-optimized (has RACK keywords or specialized patterns)
    if grep -qE "RACK Architecture|Context Compression|Short-Circuit|veto power|Mandatory.*checklist|validation specialist|compressed brief|observe behavior" "$workspace/SOUL.md" 2>/dev/null; then
      printf "  ${GREEN}✓${RESET} %-12s RACK-optimized\n" "$spec"
    else
      printf "  ${CYAN}○${RESET} %-12s Standard (upgrade available)\n" "$spec"
    fi
  done

  echo ""

  # Count upgraded vs total
  local upgraded=$(grep -lE "RACK Architecture|Context Compression|validation specialist|veto power|compressed brief|observe behavior" ~/.openclaw/workspaces/*/SOUL.md 2>/dev/null | wc -l | tr -d ' ')
  local total=${#specialists[@]}

  if [[ $upgraded -eq $total ]] || [[ $upgraded -ge 4 ]]; then
    dim "All core specialists RACK-optimized (knowledge & security use standard templates)"
  else
    dim "Run 'rack team upgrade' to apply RACK templates"
  fi
  echo ""
}

_team_check() {
  header "Specialist Agent Health Check"
  echo ""

  local specialists=("programmer" "reviewer" "tester" "knowledge" "security" "manager")
  local missing=()
  local healthy=0

  for spec in "${specialists[@]}"; do
    if agent_registered "$spec"; then
      success "$spec: registered"
      healthy=$((healthy + 1))
    else
      warn "$spec: NOT registered"
      missing+=("$spec")
    fi
  done

  echo ""

  if [[ "${#missing[@]}" -eq 0 ]]; then
    success "All specialists healthy ($healthy/6)"
  else
    error "Missing specialists: ${missing[*]}"
    echo ""
    echo "Run: rack install"
    exit 1
  fi
}

_team_roles() {
  header "Specialist Agent Roles (RACK Architecture)"
  echo ""

  echo -e "${BOLD}${GREEN}Manager (Atlas)${RESET}"
  echo "  • Orchestrates tasks and delegates to specialists"
  echo "  • Embedded classifier logic (routes tasks efficiently)"
  echo "  • Context compression before delegation"
  echo "  • Short-circuit resolution for simple queries"
  echo "  • Model: Sonnet | Tools: read (memory), message"
  echo ""

  echo -e "${BOLD}${GREEN}Programmer${RESET}"
  echo "  • Implements code changes from compressed briefs"
  echo "  • Reads <5K tokens per task (file + brief only)"
  echo "  • Signals completion via memory files"
  echo "  • Model: Haiku (simple) / Sonnet (complex)"
  echo "  • Tools: read, write, edit, exec (sandbox)"
  echo ""

  echo -e "${BOLD}${GREEN}Reviewer (Auditor)${RESET}"
  echo "  • Security + correctness gatekeeper"
  echo "  • 6-point mandatory checklist"
  echo "  • Veto power (bad code doesn't proceed)"
  echo "  • Model: Sonnet | Tools: read (diff only)"
  echo ""

  echo -e "${BOLD}${GREEN}Tester (Validator)${RESET}"
  echo "  • Behavior-only validation (doesn't read code!)"
  echo "  • Executes reproduction steps"
  echo "  • Binary verdict: PASS or FAIL"
  echo "  • Model: Haiku | Tools: exec, browser (read-only)"
  echo ""

  echo -e "${BOLD}${GREEN}Knowledge${RESET}"
  echo "  • Memory distillation and indexing"
  echo "  • Pattern extraction from logs"
  echo "  • Architectural decision tracking"
  echo "  • Model: Haiku | Tools: read, memory search"
  echo ""

  echo -e "${BOLD}${GREEN}Security${RESET}"
  echo "  • Deep threat modeling (beyond code review)"
  echo "  • Penetration testing coordination"
  echo "  • Compliance audits (GDPR, HIPAA)"
  echo "  • Model: Sonnet | Tools: read, browser"
  echo ""

  echo -e "${DIM}Note: Reviewer handles routine security checks. Security specialist"
  echo -e "      handles deep audits, compliance, and threat modeling.${RESET}"
  echo ""
}

_team_upgrade() {
  header "Upgrading Specialists to RACK Architecture"
  echo ""

  warn "This will replace SOUL.md files with RACK-optimized templates"
  echo ""
  echo "Changes:"
  echo "  • Manager: Add classifier logic + context compression rules"
  echo "  • Programmer: Add brief-only reading + <5K token targets"
  echo "  • Reviewer: Add 6-point security checklist + veto power"
  echo "  • Tester: Add behavior-only validation (no code reading)"
  echo "  • Knowledge: No changes (already efficient)"
  echo "  • Security: No changes (focused on deep audits)"
  echo ""

  read -rp "Proceed with upgrade? [y/N]: " CONFIRM
  [[ "${CONFIRM,,}" != "y" ]] && { warn "Aborted."; return; }

  echo ""

  local template_dir="$RACK_CLI_ROOT/lib/templates"
  local upgraded=0
  local failed=0

  # Upgrade Manager
  info "Upgrading manager..."
  local manager_workspace="$OPENCLAW_DIR/workspaces/manager"
  if [[ -d "$manager_workspace" ]]; then
    # Backup existing SOUL.md
    if [[ -f "$manager_workspace/SOUL.md" ]]; then
      cp "$manager_workspace/SOUL.md" "$manager_workspace/SOUL.md.backup-$(date +%Y%m%d-%H%M%S)"
    fi

    # Apply RACK template
    cp "$template_dir/rack-manager.md" "$manager_workspace/SOUL.md"
    chmod 600 "$manager_workspace/SOUL.md"

    success "manager: upgraded (backup saved)"
    upgraded=$((upgraded + 1))
  else
    warn "manager: workspace not found"
    failed=$((failed + 1))
  fi

  # Upgrade Programmer
  info "Upgrading programmer..."
  local programmer_workspace="$OPENCLAW_DIR/workspaces/programmer"
  if [[ -d "$programmer_workspace" ]]; then
    if [[ -f "$programmer_workspace/SOUL.md" ]]; then
      cp "$programmer_workspace/SOUL.md" "$programmer_workspace/SOUL.md.backup-$(date +%Y%m%d-%H%M%S)"
    fi

    cp "$template_dir/rack-programmer.md" "$programmer_workspace/SOUL.md"
    chmod 600 "$programmer_workspace/SOUL.md"

    success "programmer: upgraded"
    upgraded=$((upgraded + 1))
  else
    warn "programmer: workspace not found"
    failed=$((failed + 1))
  fi

  # Upgrade Reviewer
  info "Upgrading reviewer..."
  local reviewer_workspace="$OPENCLAW_DIR/workspaces/reviewer"
  if [[ -d "$reviewer_workspace" ]]; then
    if [[ -f "$reviewer_workspace/SOUL.md" ]]; then
      cp "$reviewer_workspace/SOUL.md" "$reviewer_workspace/SOUL.md.backup-$(date +%Y%m%d-%H%M%S)"
    fi

    cp "$template_dir/rack-reviewer.md" "$reviewer_workspace/SOUL.md"
    chmod 600 "$reviewer_workspace/SOUL.md"

    success "reviewer: upgraded"
    upgraded=$((upgraded + 1))
  else
    warn "reviewer: workspace not found"
    failed=$((failed + 1))
  fi

  # Upgrade Tester
  info "Upgrading tester..."
  local tester_workspace="$OPENCLAW_DIR/workspaces/tester"
  if [[ -d "$tester_workspace" ]]; then
    if [[ -f "$tester_workspace/SOUL.md" ]]; then
      cp "$tester_workspace/SOUL.md" "$tester_workspace/SOUL.md.backup-$(date +%Y%m%d-%H%M%S)"
    fi

    cp "$template_dir/rack-tester.md" "$tester_workspace/SOUL.md"
    chmod 600 "$tester_workspace/SOUL.md"

    success "tester: upgraded"
    upgraded=$((upgraded + 1))
  else
    warn "tester: workspace not found"
    failed=$((failed + 1))
  fi

  # Knowledge and Security don't need upgrades (already efficient)
  info "knowledge: no upgrade needed (already optimized)"
  info "security: no upgrade needed (already optimized)"

  echo ""

  if [[ $failed -gt 0 ]]; then
    warn "Upgraded: $upgraded, Failed: $failed"
    echo ""
    echo "Missing agents? Run: rack install"
  else
    success "All specialists upgraded! ($upgraded agents)"
  fi

  echo ""
  info "Restarting gateway to apply changes..."
  restart_gateway

  echo ""
  success "RACK upgrade complete!"
  echo ""
  echo -e "${BOLD}Next Steps:${RESET}"
  echo "  1. Test specialist responses: Send a message to manager in Telegram"
  echo "  2. Verify context efficiency: Check token usage in next session"
  echo "  3. Test bug-fix pipeline: rack workflow manager create bug-fix"
  echo ""
  echo -e "${BOLD}What Changed:${RESET}"
  echo "  • Manager now compresses context before delegating (<500 tokens)"
  echo "  • Programmer reads brief only (not full history)"
  echo "  • Reviewer runs 6-point security checklist"
  echo "  • Tester validates behavior (doesn't read code)"
  echo ""
  echo -e "${BOLD}Expected Benefits:${RESET}"
  echo "  • 50-80% reduction in token usage for routine tasks"
  echo "  • Faster response times (less context to process)"
  echo "  • Better security (mandatory checklist on every change)"
  echo "  • More reliable validation (objective behavior tests)"
  echo ""
}

# ─── Task Delegation ──────────────────────────────────────────────────────────

_task_list_path() {
  echo "$OPENCLAW_DIR/workspaces/manager/TASK_LIST.json"
}

_ensure_task_list() {
  local path; path=$(_task_list_path)
  local manager_ws="$OPENCLAW_DIR/workspaces/manager"
  if [[ ! -d "$manager_ws" ]]; then
    error "Manager agent not initialized. Run: rack install"
  fi
  if [[ ! -f "$path" ]]; then
    echo '{"tasks":[]}' | python3 -c "import sys,json; print(json.dumps(json.load(sys.stdin), indent=2))" > "$path"
    chmod 600 "$path"
  fi
}

_team_delegate() {
  local priority="normal"
  local -a rest=()
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --priority|-p) shift; priority="${1:-normal}" ;;
      *) rest+=("$1") ;;
    esac
    shift
  done

  local description="${rest[0]:-}"
  if [[ -z "$description" ]]; then
    error "Usage: rack team delegate [--priority high|normal|low] \"<task description>\""
  fi

  _ensure_task_list
  local path; path=$(_task_list_path)

  local task_id
  task_id="task-$(date +%s%N | cut -c1-13)"
  local created; created=$(date -Iseconds)

  python3 - "$path" "$task_id" "$description" "$priority" "$created" <<'PYEOF'
import sys, json
path, tid, desc, pri, created = sys.argv[1:]
with open(path) as f:
    data = json.load(f)
data.setdefault("tasks", []).append({
    "id": tid,
    "description": desc,
    "priority": pri,
    "created": created,
    "status": "pending"
})
with open(path, "w") as f:
    json.dump(data, f, indent=2)
PYEOF

  success "Task queued: [$task_id] $description"
  echo "  Priority: $priority"
  echo "  Queue: $(_team_queue_count) task(s) pending"
  echo ""
  info "View queue: rack team queue"
}

_team_queue_count() {
  local path; path=$(_task_list_path)
  [[ ! -f "$path" ]] && echo "0" && return
  python3 -c "
import json, sys
with open('$path') as f:
    data = json.load(f)
pending = [t for t in data.get('tasks', []) if t.get('status') == 'pending']
print(len(pending))
" 2>/dev/null || echo "0"
}

_team_queue() {
  _ensure_task_list
  local path; path=$(_task_list_path)

  header "Manager Task Queue"
  echo ""

  python3 - "$path" <<'PYEOF'
import json, sys

path = sys.argv[1]
with open(path) as f:
    data = json.load(f)

tasks = data.get("tasks", [])
pending   = [t for t in tasks if t.get("status") == "pending"]
completed = [t for t in tasks if t.get("status") == "done"]

if not pending:
    print("  No pending tasks.")
else:
    pri_order = {"high": 0, "normal": 1, "low": 2}
    pending.sort(key=lambda t: pri_order.get(t.get("priority","normal"), 1))
    print(f"  {'ID':<16}  {'PRI':<8}  {'CREATED':<22}  DESCRIPTION")
    print("  " + "─"*80)
    for t in pending:
        tid   = t.get("id","?")[:14]
        pri   = t.get("priority","normal")
        cdate = t.get("created","?")[:19].replace("T"," ")
        desc  = t.get("description","")
        print(f"  {tid:<16}  {pri:<8}  {cdate:<22}  {desc}")

print()
print(f"  Pending: {len(pending)}   Completed: {len(completed)}")
PYEOF

  echo ""
  info "Mark done: rack team done <task-id>"
}

_team_done() {
  local task_id="${1:-}"
  if [[ -z "$task_id" ]]; then
    error "Usage: rack team done <task-id>"
  fi

  _ensure_task_list
  local path; path=$(_task_list_path)

  local result
  result=$(python3 - "$path" "$task_id" <<'PYEOF'
import json, sys
path, tid = sys.argv[1:]
with open(path) as f:
    data = json.load(f)
found = False
for t in data.get("tasks", []):
    if t["id"] == tid or t["id"].startswith(tid):
        t["status"] = "done"
        found = True
        print(t["description"])
        break
if not found:
    print("NOT_FOUND")
    sys.exit(1)
with open(path, "w") as f:
    json.dump(data, f, indent=2)
PYEOF
  ) || { warn "Task '$task_id' not found in queue"; return 1; }

  success "Task marked done: $result"
}
