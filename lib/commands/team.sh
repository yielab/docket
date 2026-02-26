#!/usr/bin/env bash
# Command: team

cmd_team() {
  local action="${1:-status}"
  local manager_id="manager"
  local workspace="$OPENCLAW_DIR/workspaces/$manager_id"

  case "$action" in
    status)
      header "Team Coordination Status"
      echo ""

      # Check if manager agent exists
      if agent_registered "$manager_id"; then
        success "Manager agent: registered"
        local manager_tg; manager_tg=$(get_tg_binding "$manager_id")
        if [[ -n "$manager_tg" ]]; then
          printf "  ${BOLD}%-18s${RESET} %s\n" "Telegram:" "${GREEN}$manager_tg${RESET}"
        else
          printf "  ${BOLD}%-18s${RESET} %s\n" "Telegram:" "${YELLOW}not wired${RESET}"
        fi
      else
        warn "Manager agent: not found"
        echo "  Run: rack team init"
        echo ""
        return
      fi

      echo ""
      echo -e "${BOLD}Team Members:${RESET}"

      # List specialist agents (programmer, reviewer, tester, knowledge, security)
      local specialists=("programmer" "reviewer" "tester" "knowledge" "security")
      for spec in "${specialists[@]}"; do
        if agent_registered "$spec"; then
          local spec_model
          spec_model=$(python3 -c "
import json
c = json.load(open('$CONFIG_FILE'))
for a in c.get('agents',{}).get('list',[]):
    if a.get('id') == '$spec':
        print(a.get('model', 'unknown'))
        break
" 2>/dev/null || echo "unknown")
          local profile; profile=$(model_to_profile "$spec_model")
          printf "  ${GREEN}✓${RESET} %-12s %s\n" "$spec" "($profile)"
        else
          printf "  ${RED}✗${RESET} %-12s %s\n" "$spec" "(not found)"
        fi
      done

      echo ""
      echo -e "${BOLD}Project Agents:${RESET}"
      local ids; ids=$(project_ids)
      if [[ -n "$ids" ]]; then
        while IFS= read -r id; do
          local name; name=$(meta_get "$id" "name" "$id")
          printf "  ${GREEN}●${RESET} %-16s %s\n" "$id" "$name"
        done <<< "$ids"
      else
        dim "  No project agents yet"
      fi

      echo ""
      ;;

    init)
      header "Initialize Team Coordination"
      echo ""

      if agent_registered "$manager_id"; then
        warn "Manager agent already exists"
        echo "  Check status: rack team status"
        return
      fi

      info "Creating manager agent with delegation mode..."

      # Create manager workspace
      mkdir -p "$workspace/memory"

      # Manager SOUL.md
      cat > "$workspace/SOUL.md" <<'SOUL'
# SOUL.md — Manager

## Identity
You are the **Manager** — the orchestration layer for the OpenClaw agent rack.

**Session Key:** `agent:manager:orchestrator`

You coordinate work across specialist agents (programmer, reviewer, tester, knowledge, security) and project agents.

## Role
- Decompose requirements into tasks
- Assign tasks to appropriate specialists or project agents
- Track dependencies and priorities
- Manage the shared TASK_LIST.json
- Send status reports via Telegram

## Coordination Mode
**Delegate** — You cannot edit code directly. You plan, prioritize, and message teammates.

## Delegation Rules
| Task Type | Delegate To |
|-----------|-------------|
| Code implementation | programmer |
| Code review | reviewer |
| Testing | tester |
| Memory/patterns | knowledge |
| Security audit | security |
| Project-specific work | Project agent (coreapp, sensorapp, etc.) |

## Traits
- Break complex requests into numbered sub-tasks
- Create tasks in TASK_LIST.json with clear acceptance criteria
- Monitor HEARTBEAT.md every 30 minutes
- Send proactive status updates
- Never execute tasks yourself — always delegate

## Safety
- Require HITL approval for:
  - Production deployments
  - Destructive operations
  - Cross-project changes
- Flag ambiguous requirements for clarification
SOUL

      # Manager AGENTS.md
      cat > "$workspace/AGENTS.md" <<'AGENTS'
# AGENTS.md — Manager

## Every Session
1. Read SOUL.md
2. Read HEARTBEAT.md
3. Read TASK_LIST.json
4. Check for blocked tasks

## Task List Format
```json
{
  "tasks": [
    {
      "id": "task-001",
      "description": "...",
      "assignedTo": "programmer",
      "status": "pending|in_progress|blocked|completed",
      "priority": "high|medium|low",
      "dependencies": ["task-000"],
      "created": "2026-02-25T10:00:00Z"
    }
  ]
}
```

## Mailbox Protocol
Send messages to teammates:
- @programmer — implementation requests
- @reviewer — code review requests
- @tester — testing requests
- @knowledge — context/memory queries
- @security — security audits
- @<project-agent> — project-specific work

## Heartbeat Schedule
Check every 30 minutes:
- Are any tasks blocked?
- Is status report due?
- Any pending decisions?
AGENTS

      # Manager TOOLS.md
      cat > "$workspace/TOOLS.md" <<'TOOLS'
# TOOLS.md — Manager

## Task Management
```bash
# View task list
cat TASK_LIST.json | jq .

# Add a task (manual)
# Edit TASK_LIST.json

# Check task dependencies
jq '.tasks[] | select(.dependencies != [])' TASK_LIST.json
```

## Communication
Send via Telegram:
- Tag specialists: @programmer, @reviewer, etc.
- Tag project agents: @coreapp, @sensorapp, etc.
- Use threads for task discussions

## Status Reports
Generate weekly summary:
- Tasks completed
- Tasks in progress
- Blockers
- Cost summary (rack cost)
TOOLS

      # Manager HEARTBEAT.md
      cat > "$workspace/HEARTBEAT.md" <<'HEARTBEAT'
# HEARTBEAT.md — Manager

Check every 30 minutes. Follow strictly.

## Active Coordination
_No active projects yet_

## Pending Decisions
_None_

## Blocked Tasks
_None_

## Notes
_Manager initialized — ready for delegation_
HEARTBEAT

      # Create empty TASK_LIST.json
      cat > "$workspace/TASK_LIST.json" <<'TASKLIST'
{
  "tasks": [],
  "lastUpdated": null
}
TASKLIST

      # Fix permissions
      find "$workspace" -type d -exec chmod 700 {} \;
      find "$workspace" -type f -exec chmod 600 {} \;

      success "Manager workspace created"

      # Register with OpenClaw
      openclaw agents add "$manager_id" \
        --workspace "$workspace" \
        --model "anthropic/claude-sonnet-4-6" \
        --non-interactive 2>&1 | grep -v "^$"

      success "Manager agent registered"

      # Sync session key
      sync_session_key "$manager_id" "agent:manager:orchestrator"

      echo ""
      info "Next steps:"
      echo "  1. Wire manager to Telegram: rack wire manager"
      echo "  2. Initialize specialists if needed: rack team check"
      echo ""
      ;;

    check)
      header "Team Health Check"
      echo ""

      local missing=()
      local specialists=("programmer" "reviewer" "tester" "knowledge" "security")

      for spec in "${specialists[@]}"; do
        if ! agent_registered "$spec"; then
          missing+=("$spec")
        fi
      done

      if [[ "${#missing[@]}" -eq 0 ]]; then
        success "All specialist agents found"
      else
        warn "Missing specialist agents: ${missing[*]}"
        echo ""
        echo "These are expected to be created via OpenClaw's built-in setup."
        echo "If missing, they should be added manually via:"
        echo ""
        for spec in "${missing[@]}"; do
          echo "  openclaw agents add $spec --workspace ~/.openclaw/workspaces/$spec"
        done
        echo ""
      fi

      if ! agent_registered "$manager_id"; then
        warn "Manager agent not found"
        echo "  Run: rack team init"
      else
        success "Manager agent: OK"
      fi
      ;;

    *)
      error_hint "Unknown action '$action'" "Use: status, init, or check"
      ;;
  esac
}

