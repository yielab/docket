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
      _team_queue "$@"
      ;;
    start)
      _team_start "$@"
      ;;
    done)
      _team_done "$@"
      ;;
    cancel)
      _team_cancel "$@"
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
  echo "  rack team delegate \"<task>\"            Add task (status: pending)"
  echo "  rack team delegate --priority high \"<task>\"  High-priority task"
  echo "  rack team queue                        Show active tasks"
  echo "  rack team queue --all                  Include done + cancelled"
  echo "  rack team start <task-id>              pending → in_progress"
  echo "  rack team done <task-id>               pending/in_progress → done"
  echo "  rack team cancel <task-id>             pending/in_progress → cancelled"
  echo ""
  echo "  Valid state transitions:"
  echo "    pending ──start──→ in_progress ──done──→ done"
  echo "    pending/in_progress ──cancel──→ cancelled"
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
  echo "  • Model: standard tier | Tools: read (memory), message"
  echo ""

  echo -e "${BOLD}${GREEN}Programmer${RESET}"
  echo "  • Implements code changes from compressed briefs"
  echo "  • Reads <5K tokens per task (file + brief only)"
  echo "  • Signals completion via memory files"
  echo "  • Model: economy (simple) / standard (complex)"
  echo "  • Tools: read, write, edit, exec (sandbox)"
  echo ""

  echo -e "${BOLD}${GREEN}Reviewer (Auditor)${RESET}"
  echo "  • Security + correctness gatekeeper"
  echo "  • 6-point mandatory checklist"
  echo "  • Veto power (bad code doesn't proceed)"
  echo "  • Model: standard tier | Tools: read (diff only)"
  echo ""

  echo -e "${BOLD}${GREEN}Tester (Validator)${RESET}"
  echo "  • Behavior-only validation (doesn't read code!)"
  echo "  • Executes reproduction steps"
  echo "  • Binary verdict: PASS or FAIL"
  echo "  • Model: economy tier | Tools: exec, browser (read-only)"
  echo ""

  echo -e "${BOLD}${GREEN}Knowledge${RESET}"
  echo "  • Memory distillation and indexing"
  echo "  • Pattern extraction from logs"
  echo "  • Architectural decision tracking"
  echo "  • Model: economy tier | Tools: read, memory search"
  echo ""

  echo -e "${BOLD}${GREEN}Security${RESET}"
  echo "  • Deep threat modeling (beyond code review)"
  echo "  • Penetration testing coordination"
  echo "  • Compliance audits (GDPR, HIPAA)"
  echo "  • Model: standard tier | Tools: read, browser"
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
    echo '{"tasks":[]}' | json_atomic_write "$path"
  fi
}

# ── Schema-validated, locked delegate ─────────────────────────────────────
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
  [[ -z "$description" ]] && \
    error "Usage: rack team delegate [--priority high|normal|low] \"<task description>\""

  # Schema: validate priority
  case "$priority" in
    high|normal|low) ;;
    *) error "Invalid priority '$priority'. Use: high | normal | low" ;;
  esac

  # Schema: description length limit
  if [[ ${#description} -gt 500 ]]; then
    error "Description too long (${#description} chars). Limit: 500."
  fi

  _ensure_task_list
  local path; path=$(_task_list_path)

  local task_id; task_id="task-$(date +%s%N 2>/dev/null | cut -c1-13 || date +%s)"
  local created; created=$(date -Iseconds)

  with_rack_lock _team_delegate_write "$path" "$task_id" "$description" "$priority" "$created"

  rack_audit "team.delegate" "{\"id\":\"$task_id\",\"priority\":\"$priority\"}"
  success "Task queued: [$task_id] $description"
  echo "  Priority: $priority"
  echo "  Queue: $(_team_queue_count) task(s) pending"
  echo ""
  info "View queue: rack team queue"
}

_team_delegate_write() {
  local path="$1" task_id="$2" desc="$3" pri="$4" created="$5"
  python3 - "$path" "$task_id" "$desc" "$pri" "$created" <<'PY' | json_atomic_write "$path"
import sys, json
path, tid, desc, pri, created = sys.argv[1:]
data = json.load(open(path))
data.setdefault("tasks", []).append({
    "id": tid, "description": desc, "priority": pri,
    "created": created, "startedAt": None, "completedAt": None,
    "status": "pending"
})
print(json.dumps(data, indent=2))
PY
}

_team_queue_count() {
  local path; path=$(_task_list_path)
  [[ ! -f "$path" ]] && echo "0" && return
  python3 -c "
import json
data = json.load(open('$path'))
print(sum(1 for t in data.get('tasks',[]) if t.get('status') in ('pending','in_progress')))
" 2>/dev/null || echo "0"
}

_team_queue() {
  local show_all=0
  while [[ $# -gt 0 ]]; do
    case "$1" in --all|-a) show_all=1; shift ;; *) shift ;; esac
  done

  _ensure_task_list
  local path; path=$(_task_list_path)

  header "Manager Task Queue"
  echo ""

  SHOW_ALL="$show_all" python3 - "$path" <<'PY'
import json, os, sys
path = sys.argv[1]
show_all = os.environ.get("SHOW_ALL") == "1"
tasks = json.load(open(path)).get("tasks", [])
pri_order = {"high": 0, "normal": 1, "low": 2}

def fmt_row(t, prefix=""):
    tid   = t.get("id","?")[:14]
    pri   = t.get("priority","normal")
    cdate = t.get("created","?")[:19].replace("T"," ")
    desc  = t.get("description","")
    return f"  {prefix}{tid:<16}  {pri:<8}  {cdate:<22}  {desc}"

active = [t for t in tasks if t.get("status") in ("pending","in_progress")]
done   = [t for t in tasks if t.get("status") == "done"]
canc   = [t for t in tasks if t.get("status") == "cancelled"]

if not active:
    print("  No active tasks.")
else:
    active.sort(key=lambda t: (0 if t["status"]=="in_progress" else 1,
                               pri_order.get(t.get("priority","normal"),1)))
    print(f"  {'ID':<16}  {'PRI':<8}  {'CREATED':<22}  DESCRIPTION")
    print("  " + "─"*80)
    for t in active:
        prefix = "▶ " if t["status"] == "in_progress" else "  "
        print(fmt_row(t, prefix.strip()))

print()
line = f"  Pending: {sum(1 for t in active if t['status']=='pending')}"
line += f"   In progress: {sum(1 for t in active if t['status']=='in_progress')}"
line += f"   Done: {len(done)}"
if canc: line += f"   Cancelled: {len(canc)}"
print(line)

if show_all and (done or canc):
    print()
    print(f"  {'ID':<16}  {'STATUS':<12}  {'COMPLETED':<22}  DESCRIPTION")
    print("  " + "─"*80)
    for t in done + canc:
        tid   = t.get("id","?")[:14]
        st    = t.get("status","?")
        cdate = (t.get("completedAt") or t.get("created","?"))[:19].replace("T"," ")
        desc  = t.get("description","")
        print(f"  {tid:<16}  {st:<12}  {cdate:<22}  {desc}")
PY

  echo ""
  info "Mark done: rack team done <id>  |  Start: rack team start <id>  |  Cancel: rack team cancel <id>"
  [[ "$show_all" -eq 0 ]] && dim "  Show completed/cancelled: rack team queue --all"
}

# ── State transitions (all locked + atomic) ────────────────────────────────
# Valid transitions: pending→in_progress, pending→done, in_progress→done,
#                   pending→cancelled, in_progress→cancelled

_team_transition_write() {
  local path="$1" tid="$2" new_state="$3"
  local now; now=$(date -Iseconds)
  python3 - "$path" "$tid" "$new_state" "$now" <<'PY' | json_atomic_write "$path"
import sys, json
path, tid, new_state, now = sys.argv[1:]
ALLOWED = {
    "in_progress": {"pending"},
    "done":        {"pending", "in_progress"},
    "cancelled":   {"pending", "in_progress"},
}
data = json.load(open(path))
found = False
for t in data.get("tasks", []):
    if t["id"] == tid or t["id"].startswith(tid):
        cur = t.get("status", "pending")
        if cur not in ALLOWED.get(new_state, set()):
            # emit a sentinel to stdout — json_atomic_write will receive invalid JSON and abort
            # so instead we write file unchanged and emit the sentinel via stderr path
            import sys as _sys
            _sys.stderr.write(f"INVALID_TRANSITION|{cur}\n")
            print(json.dumps(data, indent=2))
            found = True
            break
        t["status"] = new_state
        if new_state == "in_progress":
            t["startedAt"] = now
        elif new_state in ("done", "cancelled"):
            t["completedAt"] = now
        print(json.dumps(data, indent=2))
        import sys as _sys
        _sys.stderr.write(f"OK|{t['description']}\n")
        found = True
        break
if not found:
    import sys as _sys
    _sys.stderr.write("NOTFOUND|\n")
    print(json.dumps(data, indent=2))
PY
}

_team_start() {
  local result
  result=$(_team_transition_result "in_progress" "${1:-}") || return 1
  success "Task → in_progress: ${result#*|}"
}

_team_done() {
  local result
  result=$(_team_transition_result "done" "${1:-}") || return 1
  success "Task → done: ${result#*|}"
}

_team_cancel() {
  local result
  result=$(_team_transition_result "cancelled" "${1:-}") || return 1
  success "Task → cancelled: ${result#*|}"
}

# Performs the transition and prints the sentinel line; returns 1 on error.
_team_transition_result() {
  local new_state="$1" task_id="$2"
  [[ -z "$task_id" ]] && error "Usage: rack team $new_state <task-id>"
  _ensure_task_list
  local path; path=$(_task_list_path)
  local now; now=$(date -Iseconds)
  local sentinel_file; sentinel_file=$(mktemp)
  local ok=0
  with_rack_lock _team_transition_write "$path" "$task_id" "$new_state" 2>"$sentinel_file" || ok=1
  local sentinel; sentinel=$(cat "$sentinel_file"); rm -f "$sentinel_file"
  if [[ "$sentinel" == NOTFOUND* || "$sentinel" == INVALID_TRANSITION* ]]; then
    local detail="${sentinel#*|}"
    if [[ "$sentinel" == INVALID_TRANSITION* ]]; then
      fail "  Cannot move '$task_id' to $new_state (current status: $detail)"
    else
      fail "  Task '$task_id' not found"
    fi
    return 1
  fi
  rack_audit "team.$new_state" "{\"id\":\"$task_id\"}"
  echo "$sentinel"
}
